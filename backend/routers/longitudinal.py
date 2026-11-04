"""Longitudinal comparison endpoints (read-only: stored studies are never modified)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from routers.analysis import get_bearer_token, get_current_user
from services import longitudinal_service as lg
from services import supabase_client as db

router = APIRouter(prefix="/api/longitudinal", tags=["longitudinal"])


class CompareRequest(BaseModel):
    previous_id: str = Field(min_length=1, max_length=64)
    current_id: str = Field(min_length=1, max_length=64)


def _study(study_id: str, user_id: str, token: str) -> dict:
    record = db.get_analysis(user_id, token, study_id)  # RLS-scoped: other users' studies are "not found"
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return record


def _others(current: dict, user_id: str, token: str) -> list:
    """Other studies of the same patient: by the explicit ID when the study has one, else by patient name."""
    pid = lg.explicit_id(current)
    if pid:
        found = db.list_analyses_by_patient_id(user_id, token, pid, 50)
    else:
        found = db.list_analyses_for_patient(user_id, token, (current.get("patient") or {}).get("name"), 50)
    return [r for r in found if r.get("analysis_id") != current.get("analysis_id")]


@router.get("/{study_id}/candidates")
def candidates(study_id: str, user_id: str = Depends(get_current_user), token: str = Depends(get_bearer_token)):
    current = _study(study_id, user_id, token)
    return lg.candidate_timeline(current, _others(current, user_id, token))


@router.post("/compare")
def compare(req: CompareRequest, user_id: str = Depends(get_current_user), token: str = Depends(get_bearer_token)):
    previous = _study(req.previous_id, user_id, token)
    current = _study(req.current_id, user_id, token)
    return lg.compare(previous, current)


@router.get("/{study_id}/series")
def series(study_id: str, measurement: str = Query("meniscus:mean", max_length=40),
           user_id: str = Depends(get_current_user), token: str = Depends(get_bearer_token)):
    current = _study(study_id, user_id, token)
    try:
        return lg.build_series(current, _others(current, user_id, token), measurement)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown measurement.")


@router.get("/measurements")
def measurements(user_id: str = Depends(get_current_user)):
    return {"measurements": [{"id": m[0], "label": m[1], "unit": m[2]} for m in lg.MEASUREMENTS]}
