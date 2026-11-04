"""Guided-demo support. Everything here is synthetic, read-only and never saved to any user's history.

- Cases are the bundled reference samples, analysed in memory with the normal builder (nothing is
  written to Supabase or to the History table).
- "Cached demonstration" AI text is pre-written fixture text tied to a sample's source hash and the
  fixture version; it is never presented as live inference.
- Authentication is unchanged: every endpoint needs a logged-in (and MFA-verified) session.
"""

import hashlib
import json
import os
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

import store
from routers.analysis import get_current_user
from services import analysis_builder as builder
from services import image_processor as ip
from services import longitudinal_service as lg
from services import provenance_service as prov
from services import sample_registry as sr
from services.seed import image_hash

router = APIRouter(prefix="/api/demo", tags=["demo"])

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "demo")
FIXTURE_VERSION = "demo-fixture-1"
SYNTHETIC_LABEL = "Synthetic demonstration data - not a real patient."

_record_cache: Dict[str, Dict] = {}


def _load(name: str) -> Dict:
    with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sample_or_404(source: str) -> Dict:
    sample = sr.get(source)
    if sample is None:
        raise HTTPException(status_code=404, detail="Demo case not found.")
    return sample


def _build_case(source: str) -> Dict:
    if source in _record_cache:
        return _record_cache[source]
    sample = _sample_or_404(source)
    data = sr.read_image(source)
    img = ip.load_image(data)
    record = builder.build_from_sample(
        sample, sample["image_file"], {"name": "{} (synthetic demo case)".format(source), "imaging_type": "X-ray"},
        image_hash(data), img, store.IMAGE_DIR)
    record["demo"] = True
    record["synthetic"] = True
    record["demo_label"] = SYNTHETIC_LABEL
    _record_cache[source] = record
    return record


@router.get("/cases")
def cases(user_id: str = Depends(get_current_user)):
    items = []
    for s in sr.all_samples():
        p = s["patient"]
        items.append({
            "source": s["source"],
            "label": "{} - KL {} / {}".format(s["source"], s["kl_grade"], s["oa_classification"]),
            "age": p["age"], "sex": p["sex"], "side": p["side"],
            "kl_grade": s["kl_grade"], "classification": s["oa_classification"],
            "modality": "X-ray",
            "image_url": "/api/samples/{}/image".format(s["source"]),
            "demonstrates": ["Quantitative analysis (meniscus + bone measurements)", "Implant sizing",
                             "AI Visual Scan on a real knee radiograph"],
            "synthetic": True,
        })
    return {"label": SYNTHETIC_LABEL, "count": len(items), "items": items}


@router.get("/cases/{source}")
def case(source: str, user_id: str = Depends(get_current_user)):
    try:
        return _build_case(source)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="The demo case could not be prepared (image processing failed).")


@router.get("/cases/{source}/provenance")
def case_provenance(source: str, user_id: str = Depends(get_current_user)):
    return prov.attach_ai_observations(prov.build_study_provenance(_build_case(source)),
                                       _build_case(source)["analysis_id"], [])


def cached_ai_for(source: str) -> Dict:
    """Pre-generated demo text, valid only for the exact source data and fixture version."""
    sample = _sample_or_404(source)
    fixtures = _load("cached_ai.json")
    entry = (fixtures.get("cases") or {}).get(source)
    base = {"mode": "cached", "label": "Pre-generated synthetic demonstration result.", "source": source}
    if not entry:
        return {**base, "valid": False, "reason": "No cached demonstration result exists for this case."}
    if fixtures.get("fixture_version") != FIXTURE_VERSION:
        return {**base, "valid": False, "reason": "The cached result was made for a different fixture version."}
    if entry.get("source_md5") != sample.get("md5"):
        return {**base, "valid": False, "reason": "The source image changed after this result was prepared."}
    backbone = (sample.get("inference") or {}).get("backbone")
    if entry.get("analysis_backbone") != backbone:
        return {**base, "valid": False, "reason": "The analysis model changed after this result was prepared."}
    return {**base, "valid": True, "reason": None, "fixture_version": FIXTURE_VERSION,
            "visual_scan": entry["visual_scan"], "food_advice": entry["food_advice"],
            "provenance": {"type": "pre_generated_demo_fixture", "generated_by": fixtures.get("generated_by"),
                           "content_sha256": hashlib.sha256(entry["visual_scan"].encode("utf-8")).hexdigest(),
                           "model": None, "live": False}}


@router.get("/cases/{source}/cached-ai")
def cached_ai(source: str, user_id: str = Depends(get_current_user)):
    return cached_ai_for(source)


SYNTH_DIR = os.path.join(DATA_DIR, "synth_knee_006")
DEFAULT_SERIES = "DEMO-SERIES-001"
SYNTH_SERIES = "SYNTH-KNEE-006"


def synth_records() -> list:
    """The two stored SYNTH-KNEE-006 examinations (each its own file, produced by tools/make_synth_knee_006.py)."""
    out = []
    for name in ("baseline.json", "followup.json"):
        with open(os.path.join(SYNTH_DIR, name), "r", encoding="utf-8") as fh:
            out.append(json.load(fh))
    return sorted(out, key=lambda r: lg.exam_time(r))


def demo_pool() -> list:
    """Every synthetic examination in the demo dataset. Discovery runs over this pool, never over a hard-coded pair."""
    fx = _load("longitudinal_demo.json")
    return list(fx["studies"]) + [fx["rejected_example"]] + synth_records()


def _claims_same_patient(a: dict, b: dict) -> bool:
    """Candidate filter: same explicit id, or (when neither has one) the same name. The service then verdicts each."""
    ia, ib = lg.explicit_id(a), lg.explicit_id(b)
    if ia or ib:
        return ia == ib
    return lg.normalise_name((a.get("patient") or {}).get("name")) == lg.normalise_name((b.get("patient") or {}).get("name"))


_DEMO_IMAGE_TYPES = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@router.get("/images/{name}")
def demo_image(name: str):
    """The synthetic demo radiographs. Public like /api/samples/{source}/image (an <img> tag cannot send a bearer
    token); only the files that ship in the SYNTH-KNEE-006 folder can be requested."""
    allowed = {f for f in os.listdir(SYNTH_DIR) if os.path.splitext(f)[1].lower() in _DEMO_IMAGE_TYPES}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(os.path.join(SYNTH_DIR, name), media_type=_DEMO_IMAGE_TYPES[os.path.splitext(name)[1].lower()])


@router.get("/longitudinal/series")
def longitudinal_series(user_id: str = Depends(get_current_user)):
    fx = _load("longitudinal_demo.json")
    synth = synth_records()
    return {"items": [
        {"series_id": DEFAULT_SERIES, "label": "Synthetic series DEMO-SERIES-001 (one image reused, authored values)", "studies": len(fx["studies"])},
        {"series_id": SYNTH_SERIES, "label": "Synthetic patient SYNTH-KNEE-006 (two supplied radiographs, uploaded through the normal analysis path)", "studies": len(synth)},
    ]}


@router.get("/longitudinal")
def longitudinal(series_id: str = DEFAULT_SERIES, user_id: str = Depends(get_current_user)):
    fx = _load("longitudinal_demo.json")
    if series_id == SYNTH_SERIES:
        synth = synth_records()
        current = synth[-1]
        others = [r for r in demo_pool() if r["analysis_id"] != current["analysis_id"] and _claims_same_patient(current, r)]
        timeline = lg.candidate_timeline(current, others)
        earlier = [s for s in timeline["studies"] if not s["is_current"] and s.get("relation") == "earlier" and s.get("comparable_with_current")]
        by_id = {r["analysis_id"]: r for r in demo_pool()}
        previous = by_id[earlier[-1]["study_id"]] if earlier else synth[0]
        unrelated = next(r for r in fx["studies"][::-1])  # a different synthetic patient with the same sex/side/modality
        return {
            "label": current["demo_label"], "notes": current["demo_notes"], "synthetic": True, "series_id": SYNTH_SERIES,
            "image_url": None,  # each study carries its own image_url
            "timeline": timeline,
            "comparison": lg.compare(previous, current),
            "series": lg.build_series(current, others, "meniscus:mean"),
            "rejected_example": lg.compare(previous, unrelated),
        }
    if series_id != DEFAULT_SERIES:
        raise HTTPException(status_code=404, detail="Demo series not found.")
    studies = fx["studies"]
    return {
        "label": fx["_label"], "synthetic": True, "series_id": fx["series_id"],
        "image_url": "/api/samples/{}/image".format(fx["image_source"]),
        "timeline": lg.candidate_timeline(studies[-1], studies[:-1]),
        "comparison": lg.compare(studies[0], studies[-1]),
        "series": lg.build_series(studies[-1], studies[:-1], "meniscus:mean"),
        "rejected_example": lg.compare(studies[-1], fx["rejected_example"]),
    }
