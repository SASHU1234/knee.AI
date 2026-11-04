"""AI-generated food & diet advice for a patient's knee analysis."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.analysis import get_current_user
from services import openrouter_client as orc
from services import provenance_service as prov

router = APIRouter(prefix="/api", tags=["advice"])


class AdviceRequest(BaseModel):
    record: dict
    language: Optional[str] = None
    include_provenance: bool = False  # opt-in: default response is unchanged


def _build_messages(record: dict, language: Optional[str] = None) -> list:
    patient = record.get("patient", {})
    meniscus = record.get("meniscus", {})
    assessment = meniscus.get("assessment", {})
    kl = meniscus.get("kl_grade", {})

    system = (
        "You are a clinical nutrition assistant helping patients understand food and diet "
        "choices for managing knee osteoarthritis. Given one patient's knee analysis, write "
        "practical, food-focused guidance: anti-inflammatory foods to favor, foods or patterns "
        "to limit, weight-management and hydration notes where relevant to their profile, and "
        "2-3 sample meal ideas. Tailor it to their OA severity, age, and sex.\n\n"
        "Output plain text only. This is a strict rule: never use markdown syntax of any kind - "
        "no asterisks, no **bold**, no # headers, no numbered lists like '1.'. Structure the "
        "answer as short paragraphs, and for any list use a line starting with a plain hyphen "
        "and a space ('- item'), nothing else. End with one sentence noting this is general "
        "guidance, not a substitute for their clinician or a registered dietitian."
    ) + orc.language_instruction(language)
    user = (
        f"Patient: {patient.get('name', 'the patient')}, age {patient.get('age')}, "
        f"sex {patient.get('sex')}, affected knee: {patient.get('affected_side')}.\n"
        f"OA classification: {assessment.get('classification')} "
        f"(KL grade {kl.get('grade')} - {kl.get('description')}).\n"
        f"Mean medial meniscus thickness: {assessment.get('mean_thickness_mm')} mm "
        f"(minimum {assessment.get('min_thickness_mm')} mm across measured locations).\n\n"
        "Give this patient food and diet advice for managing their knee condition."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


@router.post("/advice")
def get_food_advice(req: AdviceRequest, user_id: str = Depends(get_current_user)):
    messages = _build_messages(req.record, req.language)
    try:
        advice = orc.chat(messages, model=orc.advice_model(), max_tokens=orc.ADVICE_MAX_TOKENS)
    except orc.OpenRouterError as e:
        raise HTTPException(status_code=502, detail=str(e))
    text = orc.strip_markdown(advice)
    if not req.include_provenance:
        return {"advice": text}
    # Opt-in: server-signed lineage of this generation (no text, no prompt).
    return {
        "advice": text,
        "provenance": prov.ai_provenance("food_advice", text, req.record.get("analysis_id"), "OpenRouter", orc.advice_model()),
    }
