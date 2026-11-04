"""AI visual observations on the uploaded image itself (OpenRouter vision model).

Distinct from advice.py/chat.py: those reason over the *computed* record (measurements,
classification). This one sends the actual image pixels to a vision-language model and
asks what it can literally see — a second, independent read of the film, not a
restatement of numbers this platform's own (simulated) pipeline already produced.
"""

import base64
import os
from typing import Optional

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import store
from routers.analysis import get_current_user
from services import openrouter_client as orc
from services import provenance_service as prov
from services import supabase_client as db

router = APIRouter(prefix="/api", tags=["vision"])

SYSTEM = (
    "You are a radiology-education assistant describing a knee X-ray or MRI for a "
    "clinician's reference. Point out visually notable features you can actually see: "
    "joint space width and symmetry, bone alignment, any visible spurring or sclerosis "
    "patterns, soft-tissue shadows, and image positioning or quality. Be specific about "
    "what is visually present, not what it might mean diagnostically, and say so plainly "
    "if part of the image is unclear rather than guessing.\n\n"
    "You are not a diagnostic tool: never state a diagnosis, a severity grade, or a "
    "treatment recommendation — that judgment belongs to the clinician viewing this "
    "image, not to you.\n\n"
    "Output plain text only, no markdown syntax: no asterisks, no headers, no numbered "
    "lists. For any list use a line starting with a plain hyphen and a space. Keep it to "
    "a short paragraph or two, and end with one sentence noting these are visual "
    "observations, not a diagnosis."
)


class VisionRequest(BaseModel):
    filename: str  # the original ("none" variant) image filename
    record: Optional[dict] = None
    language: Optional[str] = None
    include_provenance: bool = False  # opt-in: default response is unchanged


# OpenRouter image inputs accept only these four types; anything else stored
# (BMP/TIFF from the wider upload set, e.g. an unconverted sidecar) is decoded
# and re-encoded as PNG with the existing OpenCV dependency before sending.
_OPENROUTER_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _sniff_mime(data: bytes) -> Optional[str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    return None


def _to_png_data_uri(data: bytes) -> str:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise HTTPException(status_code=400, detail="Stored image could not be decoded.")
    ok, buf = cv2.imencode(".png", arr)
    if not ok:
        raise HTTPException(status_code=500, detail="Could not convert the stored image for the vision model.")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _bytes_to_data_uri(data: bytes, declared_type: Optional[str] = None) -> str:
    mime = _sniff_mime(data) or declared_type or "image/png"
    if mime in _OPENROUTER_IMAGE_TYPES:
        return "data:{};base64,{}".format(mime, base64.b64encode(data).decode())
    return _to_png_data_uri(data)


def _resolve_image_data_uri(filename: str) -> str:
    """Inline the actual image bytes rather than pass a URL for OpenRouter to
    fetch — a local dev backend (127.0.0.1) isn't reachable from OpenRouter's
    servers, but our own backend can always reach Supabase storage, in dev or
    prod alike. Mirrors the local-file-then-Supabase lookup report.py's
    /api/images/{filename} already uses.
    """
    local_path = os.path.join(store.IMAGE_DIR, filename)
    if os.path.exists(local_path):
        with open(local_path, "rb") as fh:
            return _bytes_to_data_uri(fh.read())

    url = db.get_image_url(filename)
    if not url:
        raise HTTPException(status_code=404, detail="Image not found.")
    try:
        resp = httpx.get(url, timeout=20.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail="Could not fetch the stored image: {}".format(e))

    return _bytes_to_data_uri(resp.content, resp.headers.get("content-type"))


@router.post("/vision")
def analyze_image_visually(req: VisionRequest, user_id: str = Depends(get_current_user)):
    data_uri = _resolve_image_data_uri(req.filename)

    context = ""
    if req.record:
        patient = req.record.get("patient", {})
        context = " Context: age {}, sex {}, {} knee, {}.".format(
            patient.get("age"), patient.get("sex"),
            patient.get("affected_side"), patient.get("imaging_type"),
        )

    system = SYSTEM + orc.language_instruction(req.language)
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe what you can see in this knee image." + context},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        },
    ]

    try:
        observations = orc.chat(messages, model=orc.vision_model(), max_tokens=orc.VISION_MAX_TOKENS, temperature=0.4)
    except orc.OpenRouterError as e:
        raise HTTPException(status_code=502, detail=str(e))

    text = orc.strip_markdown(observations)
    if not req.include_provenance:
        return {"observations": text}
    # Opt-in: server-signed lineage of this generation (no text, no prompt, no image data).
    study_id = (req.record or {}).get("analysis_id")
    return {
        "observations": text,
        "provenance": prov.ai_provenance("visual_scan", text, study_id, "OpenRouter", orc.vision_model(), req.filename),
    }
