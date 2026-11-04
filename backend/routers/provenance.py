"""Clinical Evidence & Provenance endpoints (read-only data lineage)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routers.analysis import get_bearer_token, get_current_user
from services import provenance_service as prov
from services import supabase_client as db

router = APIRouter(prefix="/api", tags=["provenance"])

MAX_AI_ITEMS = 10
MAX_TEXT = 12000


class AiItem(BaseModel):
    provenance: dict
    text: str = Field(max_length=MAX_TEXT)


class ProvenanceRequest(BaseModel):
    ai_items: List[AiItem] = Field(default_factory=list, max_length=MAX_AI_ITEMS)


def _study(study_id: str, user_id: str, token: str) -> dict:
    # RLS-scoped lookup: a study that belongs to another user is simply "not found".
    record = db.get_analysis(user_id, token, study_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return record


@router.get("/provenance/{study_id}")
def get_provenance(study_id: str, user_id: str = Depends(get_current_user), token: str = Depends(get_bearer_token)):
    return prov.attach_ai_observations(prov.build_study_provenance(_study(study_id, user_id, token)), study_id, [])


@router.post("/provenance/{study_id}")
def post_provenance(study_id: str, req: ProvenanceRequest, user_id: str = Depends(get_current_user),
                    token: str = Depends(get_bearer_token)):
    """Same as GET, plus verification of the AI provenance blocks the client holds for this session."""
    base = prov.build_study_provenance(_study(study_id, user_id, token))
    return prov.attach_ai_observations(base, study_id, [i.model_dump() for i in req.ai_items])
