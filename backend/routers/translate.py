"""Local translation of already-generated AI text (never calls OpenRouter).

Registered unconditionally: the heavy engine is imported lazily by the service,
so when torch/model weights are absent (e.g. Vercel) this router answers 503
instead of preventing the app from starting.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routers.analysis import get_current_user
from services import local_translation_service as lts

router = APIRouter(prefix="/api", tags=["translate"])

CONTENT_TYPES = {"visual_observations", "food_advice", "clinician_note", "chat_message"}


class TranslateRequest(BaseModel):
    text: str
    target_language: str
    content_type: Optional[str] = None


@router.get("/translate/status")
def translate_status(user_id: str = Depends(get_current_user)):
    s = lts.is_available()
    return {
        "available": s["available"],
        "languages": sorted(lts.SUPPORTED_CODES),
        "terminology_version": lts.TERMINOLOGY_VERSION,
        "pipeline_version": lts.PIPELINE_VERSION,
    }


@router.post("/translate")
def translate(req: TranslateRequest, user_id: str = Depends(get_current_user)):
    if req.target_language not in lts.SUPPORTED_CODES:
        raise HTTPException(status_code=400, detail="Unsupported target language.")
    if req.content_type is not None and req.content_type not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported content type.")
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Nothing to translate.")
    if len(req.text) > lts.MAX_CHARS:
        raise HTTPException(status_code=413, detail="Text exceeds the {} character limit.".format(lts.MAX_CHARS))

    try:
        out = lts.translate(req.text, req.target_language)
    except lts.TranslationUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except lts.TranslationIntegrityError:
        raise HTTPException(
            status_code=422,
            detail="Translation was rejected because it could not preserve the original values.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except lts.TranslationError:
        raise HTTPException(status_code=500, detail="Translation failed.")

    # pipeline_version lets clients discard translations made by an older pipeline (dictionary,
    # negation input rewrite, formatting repair, semantic rules). terminology_version is kept for compatibility.
    return {
        "translated_text": out,
        "source_language": "en",
        "target_language": req.target_language,
        "terminology_version": lts.TERMINOLOGY_VERSION,
        "pipeline_version": lts.PIPELINE_VERSION,
    }
