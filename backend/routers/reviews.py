"""Clinician review endpoints. Reviewer identity always comes from the authenticated session."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routers.analysis import get_bearer_token, get_current_user
from services import provenance_service as prov
from services import review_service as rv
from services import supabase_client as db

router = APIRouter(prefix="/api", tags=["reviews"])


class AiPayload(BaseModel):
    provenance: dict
    text: str = Field(max_length=rv.MAX_SNAPSHOT)


class ReviewRequest(BaseModel):
    study_id: str = Field(min_length=1, max_length=64)
    finding_id: str = Field(min_length=1, max_length=96)
    decision: str
    comment: Optional[str] = None
    request_id: Optional[str] = Field(default=None, max_length=64)
    expected_previous_state: Optional[str] = None
    ai: Optional[AiPayload] = None  # required when reviewing an AI observation
    # NOTE: no reviewer field - identity is derived from the bearer token


def _study(study_id: str, user_id: str, token: str) -> dict:
    record = db.get_analysis(user_id, token, study_id)  # RLS-scoped ownership check
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return record


def _store(token: str):
    return rv.get_store(lambda: db._client_for(token))


def _reviewable(record: dict) -> list:
    items = []
    for p in prov.build_study_provenance(record)["provenance"]:
        items.append({"finding_id": p["finding_id"], "title": p["title"], "kind": p["category"],
                      "value": p.get("value"), "unit": p.get("unit")})
    sid = record.get("analysis_id")
    items.append({"finding_id": "report:{}".format(sid), "title": "Generated report content", "kind": "report"})
    return items


def _raise(e: rv.ReviewError):
    raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/reviews")
def create_review(req: ReviewRequest, user_id: str = Depends(get_current_user), token: str = Depends(get_bearer_token)):
    record = _study(req.study_id, user_id, token)
    try:
        rv.validate_finding_id(req.finding_id)
        finding = None
        if req.finding_id.startswith("ai:"):
            if req.ai is None:
                raise rv.ReviewError("Reviewing an AI observation requires the observation text and its provenance.")
            check = prov.verify_ai_provenance(req.ai.provenance, req.ai.text)
            if not check["valid"]:
                raise rv.ReviewError("AI provenance could not be verified: {}.".format(check["reason"]))
            if req.ai.provenance.get("study_id") not in (None, req.study_id):
                raise rv.ReviewError("This AI observation belongs to a different study.")
            kind = req.ai.provenance.get("kind")
            expected_id = "ai:{}:{}".format(kind, req.ai.provenance["content_sha256"][:16])
            if req.finding_id != expected_id:
                raise rv.ReviewError("Finding reference does not match the observation.")
            finding = {"finding_id": req.finding_id, "kind": "ai_observation",
                       "title": "AI Visual Scan observation" if kind == "visual_scan" else "AI Food Advice",
                       "content_sha256": req.ai.provenance["content_sha256"], "content_snapshot": req.ai.text}
        else:
            known = {i["finding_id"]: i for i in _reviewable(record)}
            if req.finding_id not in known:
                raise rv.ReviewNotFound("This study has no such reviewable item.")
            item = known[req.finding_id]
            finding = {"finding_id": req.finding_id, "kind": item["kind"], "title": item["title"]}
        event = rv.new_event(req.study_id, user_id, finding, req.decision, req.comment, req.request_id,
                             req.expected_previous_state)
        store = _store(token)
        stored = store.append(user_id, event)
    except rv.ReviewError as e:
        _raise(e)
    stored.pop("expected_previous_state", None)
    return {"review": stored, "persistence": store.name}


@router.get("/reviews/{study_id}")
def list_reviews(study_id: str, user_id: str = Depends(get_current_user), token: str = Depends(get_bearer_token)):
    record = _study(study_id, user_id, token)
    store = _store(token)
    try:
        events = store.list_events(user_id, study_id)
    except rv.ReviewError as e:
        _raise(e)
    out = rv.summarise(events, _reviewable(record))
    out.update({"study_id": study_id, "persistence": store.name, "persistence_note": store.description,
                "decisions": rv.DECISIONS, "reviewer_label": "Reviewer (authenticated account; role not verified)"})
    return out


@router.get("/reviews/{study_id}/{review_id}")
def get_review(study_id: str, review_id: str, user_id: str = Depends(get_current_user),
               token: str = Depends(get_bearer_token)):
    _study(study_id, user_id, token)
    try:
        events = _store(token).list_events(user_id, study_id)
    except rv.ReviewError as e:
        _raise(e)
    for e in events:
        if e["review_id"] == review_id:
            return {"review": e}
    raise HTTPException(status_code=404, detail="Review not found.")
