"""Clinical Evidence & Provenance: where does each displayed result come from?

Data lineage only. Every item is built from fields that exist in the stored analysis record
(or from the server-issued metadata of an AI call). Nothing is inferred, no confidence is
invented, and there is no model "explanation": a field that was not recorded is reported as
unavailable.

Two kinds of source:
- Persisted study data (patient metadata, meniscus/bone measurements, implant sizing, quality):
  built here from the record.
- AI observations (Visual Scan, Food Advice): the text is not persisted by the platform, so the
  server issues a signed provenance block at generation time (`ai_provenance`). Clients hand it
  back and `verify_ai_provenance` proves it was issued by this server for exactly that text.
"""

import datetime
import hashlib
import hmac
import json
import os
import secrets
from typing import Dict, List, Optional

# Signing key for AI provenance blocks. Set PROVENANCE_SECRET in production; otherwise a random
# per-process key is used, so blocks signed before a restart are reported as "unverifiable".
_SECRET = (os.environ.get("PROVENANCE_SECRET") or "").encode("utf-8") or secrets.token_bytes(32)
_SECRET_CONFIGURED = bool(os.environ.get("PROVENANCE_SECRET"))

AI_LIMITATIONS = [
    "AI-generated text, not a clinical conclusion",
    "Requires independent clinical review",
    "Not a diagnosis; may contain errors or omissions",
]

SECTION_MENISCUS = "meniscus-measurements"
SECTION_IMPLANT = "implant-sizing"
SECTION_QUALITY = "image-quality"
SECTION_IMAGE = "imaging-viewer"
SECTION_AI = "ai-visual-scan"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ AI provenance
def _canonical(p: Dict) -> bytes:
    keys = ("kind", "study_id", "content_sha256", "provider", "model", "generated_at", "source_image")
    return json.dumps({k: p.get(k) for k in keys}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ai_provenance(kind: str, text: str, study_id: Optional[str], provider: str, model: str,
                  source_image: Optional[str] = None) -> Dict:
    """Server-issued, signed description of one AI generation (never contains the text itself)."""
    p = {
        "kind": kind,  # "visual_scan" | "food_advice"
        "study_id": study_id,
        "content_sha256": content_hash(text),
        "provider": provider,
        "model": model,
        "generated_at": _utc_now(),
        "source_image": source_image,
    }
    p["signature"] = hmac.new(_SECRET, _canonical(p), hashlib.sha256).hexdigest()
    return p


def verify_ai_provenance(p: Dict, text: Optional[str] = None) -> Dict:
    """Return {valid, reason}. `text`, when given, must hash to the signed content_sha256."""
    if not isinstance(p, dict) or not p.get("signature"):
        return {"valid": False, "reason": "missing signature"}
    expected = hmac.new(_SECRET, _canonical(p), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(p["signature"])):
        reason = "signature not issued by this server session" if not _SECRET_CONFIGURED else "signature mismatch"
        return {"valid": False, "reason": reason}
    if text is not None and content_hash(text) != p.get("content_sha256"):
        return {"valid": False, "reason": "text does not match the signed content hash"}
    return {"valid": True, "reason": None}


# --------------------------------------------------------------- record -> items
def _origin(record: Dict) -> Dict:
    prov = record.get("provenance") or {}
    if record.get("sample_source"):
        return {
            "type": "reference_case_sidecar",
            "label": "Pre-analysed reference case",
            "algorithm": prov.get("method") or "unavailable",
            "segmentation": prov.get("segmentation") or "unavailable",
            "input": record.get("sample_source"),
            "scale_px_per_mm": prov.get("scale_px_per_mm"),
            "note": "Values are read from the JSON sidecar shipped with the platform; they were not "
                    "computed when this study was opened.",
        }
    return {
        "type": "deterministic_simulation",
        "label": "Deterministic simulation",
        "algorithm": prov.get("method") or "unavailable",
        "segmentation": prov.get("segmentation") or "unavailable",
        "input": "uploaded image (SHA-256 {}...)".format((record.get("image_hash") or "")[:12]) if record.get("image_hash") else "uploaded image",
        "note": "Measurements are hash-seeded simulated values (services/seed.py), not the output of a "
                "trained segmentation model.",
    }


def _item(finding_id, category, title, source, record, section, value=None, unit=None, side=None,
          limitations=None, extra=None) -> Dict:
    item = {
        "finding_id": finding_id,
        "category": category,
        "title": title,
        "source": source,
        "generated_at": record.get("created_at"),
        "study_id": record.get("analysis_id"),
        "section": section,
        "limitations": limitations or [],
        "available": True,
    }
    if value is not None:
        item["value"] = value
    if unit:
        item["unit"] = unit
    if side:
        item["side"] = side
    if extra:
        item.update(extra)
    return item


def build_study_provenance(record: Dict) -> Dict:
    """Provenance for every persisted result of one stored analysis record."""
    patient = record.get("patient") or {}
    side = patient.get("affected_side")
    origin = _origin(record)
    q_src = {"type": "quantitative_analysis", "origin": origin["type"], "algorithm": origin["algorithm"],
             "segmentation": origin["segmentation"], "input": origin["input"]}
    lim_sim = [origin["note"]]
    items: List[Dict] = []
    unavailable: List[Dict] = []

    # --- patient / study metadata (minimal) -------------------------------------------------
    meta = {
        "study_id": record.get("analysis_id"),
        "modality": patient.get("imaging_type"),
        "laterality": side,
        "age": patient.get("age"),
        "sex": patient.get("sex"),
        "analysis_timestamp": record.get("created_at"),
        "source_filename": record.get("source_filename"),
        "image_hash_prefix": (record.get("image_hash") or "")[:16] or None,
        "image_size_px": [(record.get("images") or {}).get("width"), (record.get("images") or {}).get("height")],
        "image_view": None,
    }
    unavailable.append({"field": "image_view", "reason": "The imaging view (e.g. AP/lateral) is not recorded by the platform."})
    unavailable.append({"field": "algorithm_version", "reason": "Only a method description is recorded; no algorithm/model version number is stored."})
    if not record.get("created_at"):
        unavailable.append({"field": "analysis_timestamp", "reason": "No creation timestamp stored for this study."})

    # --- meniscus thickness (quantitative) ---------------------------------------------------
    men = record.get("meniscus") or {}
    for m in men.get("measurements") or []:
        loc = m.get("location")
        if m.get("thickness_mm") is None:
            unavailable.append({"field": "meniscus.{}".format(loc), "reason": "No stored value."})
            continue
        items.append(_item(
            "meniscus:{}".format(loc), "quantitative_measurement",
            "Medial meniscus thickness - {}".format(m.get("label") or loc), q_src, record, SECTION_MENISCUS,
            value=m["thickness_mm"], unit="mm", side=side, limitations=lim_sim))
    assess = men.get("assessment") or {}
    if assess.get("mean_thickness_mm") is not None:
        items.append(_item(
            "meniscus:mean", "quantitative_measurement", "Mean medial meniscus thickness",
            dict(q_src, type="derived_from_measurements", method="arithmetic mean of the stored location thicknesses"),
            record, SECTION_MENISCUS, value=assess["mean_thickness_mm"], unit="mm", side=side,
            limitations=["Derived value; precision follows the underlying measurements"]))
    if assess.get("classification"):
        items.append(_item(
            "oa:classification", "rule_based_classification", "OA classification (rule-based)",
            {"type": "rule_based_classifier", "algorithm": "age/sex-adjusted thickness thresholds (oa_classifier)",
             "thresholds_mm": assess.get("thresholds_mm"), "age_escalated": assess.get("age_escalated"),
             "input": "mean meniscus thickness"},
            record, SECTION_MENISCUS, value=assess["classification"],
            limitations=["Threshold rule applied to the measurement above; not a clinical diagnosis",
                         "Requires independent clinical review"]))
    kl = men.get("kl_grade") or {}
    if kl.get("grade") is not None:
        items.append(_item(
            "oa:kl_grade", "model_or_heuristic_grade", "Kellgren-Lawrence grade (estimated)",
            {"type": "reference_case_sidecar" if record.get("sample_source") else "heuristic_estimate",
             "algorithm": "read from the sidecar" if record.get("sample_source") else "estimate_kl_grade (heuristic from classification, thickness and age)"},
            record, SECTION_MENISCUS, value=kl["grade"], limitations=["Estimated grade; confirm on the image"]))

    # --- bone measurements & implant -------------------------------------------------------------
    bones = record.get("bone_measurements") or {}
    labels = {"femoral_ml_mm": "Femoral width (ML)", "femoral_ap_mm": "Femoral width (AP)",
              "tibial_ml_mm": "Tibial width (ML)", "tibial_ap_mm": "Tibial width (AP)",
              "tibial_slope_deg": "Tibial slope"}
    for key, label in labels.items():
        if bones.get(key) is None:
            unavailable.append({"field": "bone.{}".format(key), "reason": "No stored value."})
            continue
        items.append(_item("bone:{}".format(key), "quantitative_measurement", label, q_src, record, SECTION_IMPLANT,
                           value=bones[key], unit="deg" if key.endswith("_deg") else "mm", side=side, limitations=lim_sim))

    imp = (record.get("implant") or {}).get("primary") or {}
    if imp:
        items.append(_item(
            "implant:primary", "implant_sizing", "Implant size recommendation",
            {"type": "catalogue_matching",
             "algorithm": "Euclidean distance in 4-D (femoral ML/AP, tibial ML/AP) to catalogue size centroids; "
                          "lowest distance wins" if not record.get("sample_source") else
                          "size pick read from the sidecar and cross-checked against catalogue centroids",
             "input": "stored bone measurements"},
            record, SECTION_IMPLANT,
            value="{} {} ({})".format(imp.get("system"), imp.get("size"), imp.get("manufacturer")),
            limitations=["Dimensional match only; no biomechanical or fit validation is performed",
                         "'Match' percentage is a distance-to-centroid mapping, not a probability"],
            extra={"match_pct": imp.get("confidence_pct"), "match_pct_meaning": "distance-to-centroid mapping"}))
    else:
        unavailable.append({"field": "implant", "reason": "No implant sizing stored."})

    # --- image quality -------------------------------------------------------------------------------
    quality = record.get("quality")
    if quality:
        items.append(_item(
            "quality:overall", "image_quality", "Image-quality assessment",
            {"type": "image_heuristics", "algorithm": "sharpness / contrast / resolution / region-detection heuristics (quality.py)",
             "input": "uploaded image"},
            record, SECTION_QUALITY, value=quality.get("score_pct"),
            limitations=["Heuristic computed from the film; not a model posterior"]))
    else:
        unavailable.append({"field": "quality", "reason": "No image-quality assessment stored."})

    images = record.get("images") or {}
    variants = images.get("variants") or {}
    return {
        "study_id": record.get("analysis_id"),
        "study": meta,
        "origin": origin,
        "provenance": items,
        "unavailable": unavailable,
        "images": {
            "original": variants.get("none"),
            "variants": sorted(k for k in variants if k != "none"),
            "overlay_available": any(k != "none" for k in variants),
            "overlay_note": "Segmentation overlays are drawn from the stored zones/polygons; "
                            "there are no saliency maps or pixel-level model explanations.",
        },
        "ai_observations": [],
        "notes": [
            "This panel shows data lineage only. It does not explain why a model produced an answer, "
            "and no model confidence values exist or are shown.",
            "Nothing here is clinically validated.",
        ],
    }


def attach_ai_observations(prov: Dict, study_id: str, ai_items: List[Dict]) -> Dict:
    """Add client-supplied AI provenance blocks after verifying each one for THIS study."""
    out = []
    for entry in (ai_items or [])[:10]:
        p = (entry or {}).get("provenance") or {}
        text = (entry or {}).get("text")
        check = verify_ai_provenance(p, text)
        if p.get("study_id") not in (None, study_id):
            check = {"valid": False, "reason": "provenance was issued for a different study"}
        out.append({
            "finding_id": "ai:{}:{}".format(p.get("kind", "unknown"), (p.get("content_sha256") or "")[:16]),
            "category": "ai_observation",
            "title": "AI Visual Scan observation" if p.get("kind") == "visual_scan" else
                     "AI Food Advice" if p.get("kind") == "food_advice" else "AI-generated text",
            "source": {"type": "vision_model" if p.get("kind") == "visual_scan" else "text_model",
                       "provider": p.get("provider"), "model": p.get("model")},
            "generated_at": p.get("generated_at"),
            "source_image": p.get("source_image"),
            "study_id": study_id,
            "section": SECTION_AI,
            "content_sha256": p.get("content_sha256"),
            "verified": check["valid"],
            "verification_note": check["reason"],
            "limitations": AI_LIMITATIONS,
            "available": True,
        })
    prov["ai_observations"] = out
    if not out:
        prov["unavailable"].append({
            "field": "ai_observations",
            "reason": "No AI observation has been generated in this session for this study "
                      "(AI text is not stored by the platform).",
        })
    return prov
