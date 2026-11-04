"""Clinician review workflow: append-only decisions about AI/analysis findings.

A review never changes the thing reviewed. Each decision is a new immutable event; the current
state of a finding is the latest event's `new_state` (default `pending_review`). Reviewer identity
is passed in by the router from the authenticated session, never from the request body.

Persistence (see docs/migrations/001_study_reviews.sql):
- `supabase`: table `study_reviews`, append-only under RLS (insert/select only, no update/delete).
- `local_file`: append-only JSONL under the backend storage dir. Used when the Supabase table is
  not available (e.g. the migration has not been applied). The API reports which one is active so the
  UI never presents local development storage as the durable clinical record.
"""

import datetime
import hashlib
import json
import os
import re
import threading
import uuid
from typing import Dict, List, Optional

import store as local_store

DECISIONS = {
    "confirmed": "Confirmed by reviewer",
    "needs_further_review": "Needs further review",
    "disagreed": "Disagreed with observation",
}
PENDING = "pending_review"
STATES = {PENDING, *DECISIONS}
FINDING_ID_RE = re.compile(r"^[A-Za-z0-9:_\-.]{1,96}$")
MAX_COMMENT = 1000
MAX_SNAPSHOT = 12000


class ReviewError(Exception):
    """Base class; `status` is the HTTP status the router should use."""
    status = 400


class ReviewNotFound(ReviewError):
    status = 404


class ReviewConflict(ReviewError):
    status = 409


class StoreUnavailable(ReviewError):
    status = 503


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def validate_finding_id(finding_id: str) -> str:
    if not isinstance(finding_id, str) or not FINDING_ID_RE.match(finding_id):
        raise ReviewError("Invalid finding reference.")
    return finding_id


def clean_comment(comment: Optional[str]) -> str:
    c = (comment or "").strip()
    if len(c) > MAX_COMMENT:
        raise ReviewError("Comment is limited to {} characters.".format(MAX_COMMENT))
    return c


# ------------------------------------------------------------------------------ stores
class FileReviewStore:
    name = "local_file"
    description = "Stored in a local file on the backend server (development storage; not a durable clinical record)."

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(local_store.STORAGE_DIR, "reviews.jsonl")
        self._lock = threading.Lock()

    def _read(self) -> List[Dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        return out

    def list_events(self, user_id: str, study_id: str) -> List[Dict]:
        return sorted((e for e in self._read() if e["study_id"] == study_id and e["reviewer_id"] == user_id),
                      key=lambda e: (e["created_at"], e["sequence"]))

    def append(self, user_id: str, event: Dict) -> Dict:
        """Atomically (under the lock) assign the sequence, enforce idempotency and optimistic checks."""
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            mine = [e for e in self._read() if e["study_id"] == event["study_id"] and e["reviewer_id"] == user_id]
            return _apply_append(mine, event, lambda ev: self._write(ev))

    def _write(self, ev: Dict) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


class SupabaseReviewStore:
    name = "supabase"
    description = "Stored in the Supabase study_reviews table (append-only, row-level security)."

    def __init__(self, client_factory):
        self._client_factory = client_factory  # () -> authenticated client or None

    def _client(self):
        c = self._client_factory()
        if c is None:
            raise StoreUnavailable("Supabase is not configured.")
        return c

    def list_events(self, user_id: str, study_id: str) -> List[Dict]:
        try:
            rows = (self._client().table("study_reviews").select("*").eq("study_id", study_id)
                    .eq("reviewer_id", user_id).order("created_at").limit(500).execute()).data
        except StoreUnavailable:
            raise
        except Exception as e:
            raise StoreUnavailable("The study_reviews table is not available: {}".format(type(e).__name__))
        return rows

    def append(self, user_id: str, event: Dict) -> Dict:
        mine = self.list_events(user_id, event["study_id"])

        def insert(ev):
            try:
                self._client().table("study_reviews").insert(ev).execute()
            except Exception as e:  # unique violation = concurrent writer won the race
                msg = str(e).lower()
                if "duplicate" in msg or "unique" in msg or "23505" in msg:
                    raise ReviewConflict("The review changed while you were submitting; reload and try again.")
                raise StoreUnavailable("Could not write the review: {}".format(type(e).__name__))
        return _apply_append(mine, event, insert)


def _apply_append(existing: List[Dict], event: Dict, write) -> Dict:
    """Shared append logic. `existing` = this reviewer's events for the study."""
    # idempotency: the same client request id never creates a second event
    rid = event.get("request_id")
    if rid:
        for e in existing:
            if e.get("request_id") == rid:
                dup = dict(e)
                dup["duplicate"] = True
                return dup
    same_finding = [e for e in existing if e["finding_id"] == event["finding_id"]]
    current = same_finding[-1] if same_finding else None
    current_state = current["new_state"] if current else PENDING
    expected = event.pop("expected_previous_state", None)
    if expected is not None and expected != current_state:
        raise ReviewConflict("This finding is now '{}' (you saw '{}'). Reload and review again.".format(current_state, expected))
    # an identical consecutive submission is a duplicate, not a new decision
    if current and current["decision"] == event["decision"] and (current.get("comment") or "") == event["comment"]:
        dup = dict(current)
        dup["duplicate"] = True
        return dup
    event["previous_state"] = current_state
    event["new_state"] = event["decision"]
    event["sequence"] = (current["sequence"] + 1) if current else 1
    write(event)
    return event


_store_cache: Dict[str, object] = {}


def get_store(client_factory, force: Optional[str] = None):
    """Pick the persistence backend. REVIEW_STORE=auto|supabase|file (default auto)."""
    mode = force or os.environ.get("REVIEW_STORE", "auto")
    if mode == "file":
        return _store_cache.setdefault("file", FileReviewStore())
    sb = SupabaseReviewStore(client_factory)
    if mode == "supabase":
        return sb
    if _store_cache.get("probe") is None:  # probe once per process
        try:
            sb._client().table("study_reviews").select("review_id").limit(1).execute()
            _store_cache["probe"] = True
        except Exception:
            _store_cache["probe"] = False
    return sb if _store_cache["probe"] else _store_cache.setdefault("file", FileReviewStore())


# ------------------------------------------------------------------------- operations
def new_event(study_id: str, reviewer_id: str, finding: Dict, decision: str, comment: Optional[str],
              request_id: Optional[str], expected_previous_state: Optional[str]) -> Dict:
    if decision not in DECISIONS:
        raise ReviewError("Decision must be one of: {}.".format(", ".join(sorted(DECISIONS))))
    if expected_previous_state is not None and expected_previous_state not in STATES:
        raise ReviewError("Invalid expected state.")
    if request_id is not None and not re.match(r"^[A-Za-z0-9\-]{8,64}$", request_id):
        raise ReviewError("Invalid request id.")
    snapshot = finding.get("content_snapshot")
    if snapshot is not None and len(snapshot) > MAX_SNAPSHOT:
        raise ReviewError("Reviewed content is too long.")
    return {
        "review_id": uuid.uuid4().hex,
        "study_id": study_id,
        "finding_id": validate_finding_id(finding["finding_id"]),
        "finding_kind": finding.get("kind"),
        "finding_title": (finding.get("title") or "")[:200],
        "content_sha256": finding.get("content_sha256"),
        "content_snapshot": snapshot,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "comment": clean_comment(comment),
        "created_at": _utc_now(),
        "request_id": request_id,
        "expected_previous_state": expected_previous_state,
    }


def summarise(events: List[Dict], reviewable: List[Dict]) -> Dict:
    """Current state per finding + full audit history. `reviewable` = findings that can be reviewed."""
    latest: Dict[str, Dict] = {}
    for e in events:
        latest[e["finding_id"]] = e
    findings = []
    seen = set()
    for item in reviewable:
        fid = item["finding_id"]
        seen.add(fid)
        e = latest.get(fid)
        findings.append({**item, "state": e["new_state"] if e else PENDING,
                         "last_review_id": e["review_id"] if e else None,
                         "last_reviewed_at": e["created_at"] if e else None})
    for fid, e in latest.items():  # reviewed items not in the current list (e.g. earlier AI text)
        if fid not in seen:
            findings.append({"finding_id": fid, "title": e.get("finding_title"), "kind": e.get("finding_kind"),
                             "state": e["new_state"], "last_review_id": e["review_id"],
                             "last_reviewed_at": e["created_at"], "from_history": True})
    return {"findings": findings, "events": events[-200:], "total_events": len(events)}


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
