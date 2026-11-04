"""Generate the SYNTH-KNEE-006 demonstration case from the two radiographs supplied by the project owner.

Workflow (the one the app itself uses):
  1. upload the baseline X-ray            -> POST /api/analyze  -> first analysis record
  2. upload the follow-up X-ray           -> POST /api/analyze  -> second analysis record
  3. open Longitudinal Comparison         -> /api/demo/longitudinal?series_id=SYNTH-KNEE-006
Both uploads go through the real endpoint (auth stubbed, nothing saved to any account), so validation, decoding,
preprocessing, ROI detection, quality assessment and the quantitative path are exactly the existing ones. The
only values supplied by hand are the form fields a user would type: patient ID, examination date, imaging view,
and the synthetic age/sex/side/modality the form requires.

Honest limitation, repeated in the stored records: images that are not one of the shipped reference samples take
the platform's DETERMINISTIC SIMULATION path, so meniscus/bone/implant numbers are hash-seeded from the image
bytes and are not measured from the radiographic anatomy. ROI detection and image quality are computed from pixels.

Images (kept unmodified in backend/data/demo/synth_knee_006/):
  baseline  baseline_right_knee_standing.webp   single right knee, 'STANDING'
  follow-up followup_bilateral_ap_standing.png  bilateral 'AP STANDING' film; the pipeline selects the right knee
            (the viewer's left, labelled R) from affected_side=Right

Usage (repo root):  .venv/Scripts/python tools/make_synth_knee_006.py
"""

import json
import os
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from fastapi.testclient import TestClient

import store
from main import app
from routers.analysis import get_bearer_token, get_current_user
from services import supabase_client as db

OUT_DIR = os.path.join(ROOT, "backend", "data", "demo", "synth_knee_006")
PATIENT_ID = "SYNTH-KNEE-006"
VIEW = "AP standing"

EXAMS = [
    # record file, image file, examination date, synthetic age, role, analysis id
    {"file": "baseline.json", "image": "baseline_right_knee_standing.webp", "mime": "image/webp", "date": "2022-03-14",
     "age": 54, "role": "Baseline examination", "id": "synth006-baseline"},
    {"file": "followup.json", "image": "followup_bilateral_ap_standing.png", "mime": "image/png", "date": "2025-03-20",
     "age": 57, "role": "Follow-up examination", "id": "synth006-followup"},
]
FORM = {"name": PATIENT_ID, "sex": "Female", "imaging_type": "X-ray", "affected_side": "Right"}

LABEL = ("SYNTHETIC DEMONSTRATION DATA. Patient SYNTH-KNEE-006 is fictional: its age, sex and examination dates were "
         "chosen for the demo, and the two radiographs are images supplied for the demo, not verified films of one person.")
NOTES = [
    "Both images were uploaded through the app's normal analysis path (POST /api/analyze) and each has its own stored record.",
    "These images are not reference samples, so the meniscus, bone and implant numbers come from the platform's deterministic "
    "simulation (hash-seeded from the image bytes), not from measuring the anatomy. Image quality and the knee region are "
    "computed from the pixels.",
    "The anatomical side (Right) was read from the images: the fibula lies to the viewer's left of the tibia and the "
    "follow-up film labels that knee R. The follow-up is a bilateral film; the pipeline picks the right knee.",
    "A difference between the two measurement sets is a descriptive number only and says nothing about disease progression.",
]


def run() -> list:
    records = []
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(store, "IMAGE_DIR", tmp), \
            mock.patch.object(db, "save_analysis", lambda *a, **k: None):
        app.dependency_overrides[get_current_user] = lambda: "demo-generator"
        app.dependency_overrides[get_bearer_token] = lambda: "demo-generator"
        client = TestClient(app)
        try:
            for exam in EXAMS:
                with open(os.path.join(OUT_DIR, exam["image"]), "rb") as fh:
                    data = fh.read()
                res = client.post(
                    "/api/analyze",
                    files={"file": (exam["image"], data, exam["mime"])},
                    data={**FORM, "age": str(exam["age"]), "synthetic_patient_id": PATIENT_ID,
                          "examined_date": exam["date"], "imaging_view": VIEW},
                )
                if res.status_code != 200:
                    raise RuntimeError("{}: {} {}".format(exam["image"], res.status_code, res.text))
                rec = res.json()
                run_at = rec["created_at"]
                rec["images"].pop("variants_data", None)  # large base64; the original is served from /api/demo/images
                rec.update({
                    "analysis_id": exam["id"], "demo": True, "synthetic": True, "analysis_run_at": run_at,
                    "demo_image_url": "/api/demo/images/" + exam["image"], "case_role": exam["role"],
                    "demo_label": LABEL, "demo_notes": NOTES,
                })
                records.append((exam, rec))
        finally:
            app.dependency_overrides.clear()
    return records


def main() -> None:
    for exam, rec in run():
        with open(os.path.join(OUT_DIR, exam["file"]), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1)
        a = rec["meniscus"]["assessment"]
        print("wrote", exam["file"], rec["patient"]["affected_side"], rec["examined_at"], a["mean_thickness_mm"], a["classification"],
              "roi detected:", rec["images"]["roi"]["detected"], "quality:", rec["quality"]["score_pct"])


if __name__ == "__main__":
    main()
