"""Provenance, longitudinal comparison, clinician review and guided-demo backend tests.

Synthetic data only. Supabase is replaced by an in-memory fake (RLS-like: a user only sees their own
studies); no OpenRouter or other external service is called.

    .venv/Scripts/python -m pytest tests/test_clinical_workflow.py -q
"""

import copy
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

import cv2
import numpy as np
from fastapi.testclient import TestClient

from main import app
from routers import demo as demo_router
from routers.analysis import get_bearer_token, get_current_user
from services import analysis_builder as builder
from services import longitudinal_service as lg
from services import openrouter_client as orc
from services import provenance_service as prov
from services import review_service as rv
from services import sample_registry as sr
from services import supabase_client as db
from services.seed import image_hash


# ------------------------------------------------------------------------------ test data
def sample_record(source="OAI_sample_03", name="Pat Example", tmp=None):
    sample = sr.get(source)
    data = sr.read_image(source)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return builder.build_from_sample(sample, sample["image_file"], {"name": name, "imaging_type": "X-ray"},
                                     image_hash(data), img, tmp or tempfile.mkdtemp())


def simulated_record(name="Sim Patient", side="Left", seed=1, tmp=None):
    rng = np.random.RandomState(seed)
    img = (rng.rand(320, 320, 3) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img)
    data = buf.tobytes()
    patient = {"name": name, "age": 61, "sex": "Female", "imaging_type": "X-ray", "affected_side": side}
    return builder.build_simulated(img, image_hash(data), "upload.png", patient, img, tmp or tempfile.mkdtemp())


def study(i, date, side="Left", name="Series P", sex="Female", age=60, modality="X-ray", mean=3.5,
          ant=3.6, mid=3.4, post=3.5, slope=8.0, method="M1", image_hash_="h", unit_ok=True):
    return {
        "analysis_id": "s%d" % i, "created_at": date, "image_hash": image_hash_ + str(i),
        "patient": {"name": name, "age": age, "sex": sex, "imaging_type": modality, "affected_side": side},
        "provenance": {"method": method},
        "meniscus": {"measurements": [
            {"location": "anterior_horn", "thickness_mm": ant}, {"location": "mid_body", "thickness_mm": mid},
            {"location": "posterior_horn", "thickness_mm": post}],
            "assessment": {"mean_thickness_mm": mean, "min_thickness_mm": min(ant, mid, post), "classification": "Mild OA"},
            "kl_grade": {"grade": 1}},
        "bone_measurements": {"femoral_ml_mm": 65.0, "femoral_ap_mm": 56.0, "tibial_ml_mm": 67.0,
                              "tibial_ap_mm": 43.0, "tibial_slope_deg": slope},
        "images": {"variants": {"none": "img%d.png" % i}},
    }


class FakeDb:
    """In-memory stand-in for the RLS-scoped analyses table."""

    def __init__(self):
        self.rows = {}  # (user_id, analysis_id) -> record

    def put(self, user_id, record):
        self.rows[(user_id, record["analysis_id"])] = record

    def get_analysis(self, user_id, token, analysis_id):
        return copy.deepcopy(self.rows.get((user_id, analysis_id)))

    def list_analyses_for_patient(self, user_id, token, name, limit=50):
        return [copy.deepcopy(r) for (u, _), r in self.rows.items() if u == user_id and r["patient"]["name"] == name][:limit]


class ApiTestCase(unittest.TestCase):
    user = "user-1"

    def setUp(self):
        self.fake = FakeDb()
        self.patches = [
            mock.patch.object(db, "get_analysis", self.fake.get_analysis),
            mock.patch.object(db, "list_analyses_for_patient", self.fake.list_analyses_for_patient),
        ]
        for p in self.patches:
            p.start()
        self.tmp = tempfile.mkdtemp()
        rv._store_cache.clear()
        rv._store_cache["file"] = rv.FileReviewStore(os.path.join(self.tmp, "reviews.jsonl"))
        self.env = mock.patch.dict(os.environ, {"REVIEW_STORE": "file"})
        self.env.start()
        self.as_user(self.user)
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        app.dependency_overrides.clear()

    def as_user(self, uid):
        app.dependency_overrides[get_current_user] = lambda: uid
        app.dependency_overrides[get_bearer_token] = lambda: "token-" + uid


# ============================================================================ provenance
class ProvenanceServiceTests(unittest.TestCase):
    def test_reference_case_values_match_the_record_exactly(self):
        rec = sample_record()
        out = prov.build_study_provenance(rec)
        by_id = {p["finding_id"]: p for p in out["provenance"]}
        for m in rec["meniscus"]["measurements"]:
            item = by_id["meniscus:" + m["location"]]
            self.assertEqual(item["value"], m["thickness_mm"])
            self.assertEqual(item["unit"], "mm")
            self.assertEqual(item["side"], rec["patient"]["affected_side"])
            self.assertEqual(item["generated_at"], rec["created_at"])
            self.assertEqual(item["study_id"], rec["analysis_id"])
            self.assertEqual(item["source"]["type"], "quantitative_analysis")
        self.assertEqual(by_id["meniscus:mean"]["value"], rec["meniscus"]["assessment"]["mean_thickness_mm"])
        self.assertEqual(by_id["bone:tibial_slope_deg"]["value"], rec["bone_measurements"]["tibial_slope_deg"])
        self.assertEqual(by_id["bone:tibial_slope_deg"]["unit"], "deg")

    def test_origin_is_stated_honestly_for_sidecar_and_simulation(self):
        self.assertEqual(prov.build_study_provenance(sample_record())["origin"]["type"], "reference_case_sidecar")
        sim = prov.build_study_provenance(simulated_record())
        self.assertEqual(sim["origin"]["type"], "deterministic_simulation")
        self.assertIn("not the output of a trained", sim["origin"]["note"])

    def test_implant_is_a_dimensional_match_with_no_fit_claim(self):
        out = prov.build_study_provenance(sample_record())
        imp = next(p for p in out["provenance"] if p["finding_id"] == "implant:primary")
        text = json.dumps(imp)
        self.assertIn("no biomechanical or fit validation", text)
        self.assertEqual(imp["match_pct_meaning"], "distance-to-centroid mapping")

    def test_no_fabricated_confidence_or_explainability_fields(self):
        text = json.dumps(prov.build_study_provenance(sample_record())).lower()
        for banned in ("heatmap", "grad-cam", "bounding_box", "saliency_map", "chain_of_thought"):
            self.assertNotIn(banned, text)
        self.assertNotIn('"confidence":', text)

    def test_missing_provenance_is_reported_unavailable_not_invented(self):
        rec = sample_record()
        rec.pop("quality", None)
        rec["bone_measurements"].pop("tibial_slope_deg")
        rec.pop("created_at")
        out = prov.build_study_provenance(rec)
        fields = {u["field"] for u in out["unavailable"]}
        self.assertTrue({"image_view", "algorithm_version", "quality", "bone.tibial_slope_deg", "analysis_timestamp"} <= fields)
        self.assertNotIn("bone:tibial_slope_deg", {p["finding_id"] for p in out["provenance"]})

    def test_missing_image_reference_is_tolerated(self):
        rec = sample_record()
        rec["images"] = {}
        out = prov.build_study_provenance(rec)
        self.assertIsNone(out["images"]["original"])
        self.assertFalse(out["images"]["overlay_available"])

    def test_mixed_ai_and_quantitative_items_stay_distinct(self):
        rec = sample_record()
        base = prov.build_study_provenance(rec)
        p = prov.ai_provenance("visual_scan", "Joint space looks symmetric.", rec["analysis_id"], "OpenRouter", "m/x", "img.png")
        out = prov.attach_ai_observations(base, rec["analysis_id"], [{"provenance": p, "text": "Joint space looks symmetric."}])
        self.assertEqual(out["ai_observations"][0]["category"], "ai_observation")
        self.assertTrue(out["ai_observations"][0]["verified"])
        self.assertEqual(out["ai_observations"][0]["source"], {"type": "vision_model", "provider": "OpenRouter", "model": "m/x"})
        self.assertNotIn("ai_observation", {i["category"] for i in out["provenance"]})
        self.assertNotIn("content_snapshot", json.dumps(out["ai_observations"]))

    def test_ai_provenance_tamper_and_wrong_study_detected(self):
        p = prov.ai_provenance("visual_scan", "text", "study-A", "OpenRouter", "m", "i.png")
        self.assertTrue(prov.verify_ai_provenance(p, "text")["valid"])
        self.assertFalse(prov.verify_ai_provenance(p, "other text")["valid"])
        forged = dict(p, model="a-better-model")
        self.assertFalse(prov.verify_ai_provenance(forged, "text")["valid"])
        self.assertFalse(prov.verify_ai_provenance({"kind": "x"}, "t")["valid"])
        out = prov.attach_ai_observations(prov.build_study_provenance(sample_record()), "study-B", [{"provenance": p, "text": "text"}])
        self.assertFalse(out["ai_observations"][0]["verified"])

    def test_no_ai_observation_is_reported_as_unavailable(self):
        out = prov.attach_ai_observations(prov.build_study_provenance(sample_record()), "x", [])
        self.assertIn("ai_observations", {u["field"] for u in out["unavailable"]})


class ProvenanceApiTests(ApiTestCase):
    def test_owner_gets_provenance_other_user_gets_404(self):
        rec = sample_record()
        self.fake.put(self.user, rec)
        r = self.client.get("/api/provenance/" + rec["analysis_id"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["study_id"], rec["analysis_id"])
        self.as_user("intruder")
        self.assertEqual(self.client.get("/api/provenance/" + rec["analysis_id"]).status_code, 404)

    def test_unauthenticated_is_rejected(self):
        app.dependency_overrides.clear()
        self.assertEqual(TestClient(app).get("/api/provenance/abc").status_code, 401)

    def test_post_verifies_ai_blocks(self):
        rec = sample_record()
        self.fake.put(self.user, rec)
        p = prov.ai_provenance("visual_scan", "obs", rec["analysis_id"], "OpenRouter", "m")
        r = self.client.post("/api/provenance/" + rec["analysis_id"], json={"ai_items": [{"provenance": p, "text": "obs"}]})
        self.assertTrue(r.json()["ai_observations"][0]["verified"])
        r = self.client.post("/api/provenance/" + rec["analysis_id"], json={"ai_items": [{"provenance": p, "text": "edited"}]})
        self.assertFalse(r.json()["ai_observations"][0]["verified"])

    def test_vision_response_gains_signed_provenance_only_when_requested(self):
        from routers import vision as vision_router
        rec = sample_record()
        with mock.patch.object(vision_router, "_resolve_image_data_uri", return_value="data:image/png;base64,AAAA"), \
                mock.patch.object(orc, "chat", return_value="Visual observation text."):
            plain = self.client.post("/api/vision", json={"filename": "orig.png", "record": rec}).json()
            full = self.client.post("/api/vision", json={"filename": "orig.png", "record": rec, "include_provenance": True}).json()
        self.assertEqual(plain, {"observations": "Visual observation text."})
        p = full["provenance"]
        self.assertEqual((p["kind"], p["study_id"], p["source_image"], p["provider"]),
                         ("visual_scan", rec["analysis_id"], "orig.png", "OpenRouter"))
        self.assertTrue(prov.verify_ai_provenance(p, full["observations"])["valid"])
        self.assertNotIn("Visual observation text", json.dumps(p))  # lineage never embeds the text

    def test_advice_response_gains_signed_provenance_only_when_requested(self):
        rec = sample_record()
        with mock.patch.object(orc, "chat", return_value="Plain text observation."):
            plain = self.client.post("/api/advice", json={"record": rec}).json()
            r = self.client.post("/api/advice", json={"record": rec, "include_provenance": True})
        self.assertEqual(plain, {"advice": "Plain text observation."})  # default contract is byte-identical
        body = r.json()
        self.assertEqual(body["advice"], "Plain text observation.")  # existing field unchanged
        self.assertEqual(body["provenance"]["kind"], "food_advice")
        self.assertEqual(body["provenance"]["study_id"], rec["analysis_id"])
        self.assertTrue(prov.verify_ai_provenance(body["provenance"], body["advice"])["valid"])


# ========================================================================== longitudinal
class LongitudinalTests(unittest.TestCase):
    A = study(1, "2023-01-10T10:00:00", mean=4.0, ant=4.1, mid=3.9, post=4.0)
    B = study(2, "2024-01-10T10:00:00", mean=3.6, ant=3.7, mid=3.5, post=3.6)

    def test_compatible_pair_compares_with_correct_arithmetic(self):
        res = lg.compare(self.A, self.B)
        self.assertTrue(res["comparability"]["comparable"])
        row = next(m for m in res["measurements"] if m["id"] == "meniscus:mean")
        self.assertEqual(row["previous"], 4.0)
        self.assertEqual(row["current"], 3.6)
        self.assertAlmostEqual(row["difference"], 3.6 - 4.0, places=12)
        self.assertAlmostEqual(row["percentage_difference"], (3.6 - 4.0) / 4.0 * 100, places=12)

    def test_values_are_not_rounded_before_calculation(self):
        a = study(1, "2023-01-10T10:00:00", mean=3.123456789, ant=1, mid=1, post=1)
        b = study(2, "2024-01-10T10:00:00", mean=3.987654321, ant=1, mid=1, post=1)
        row = next(m for m in lg.compare(a, b)["measurements"] if m["id"] == "meniscus:mean")
        self.assertEqual(row["difference"], 3.987654321 - 3.123456789)
        self.assertEqual(row["percentage_difference"], (3.987654321 - 3.123456789) / 3.123456789 * 100)

    def test_different_patient_rejected(self):
        res = lg.compare(self.A, study(2, "2024-01-10T10:00:00", name="Someone Else"))
        self.assertFalse(res["comparability"]["comparable"])
        self.assertEqual(res["measurements"], [])
        self.assertTrue(any("different patients" in r for r in res["comparability"]["blocking_reasons"]))

    def test_name_matching_ignores_case_and_spacing_only(self):
        self.assertTrue(lg.compare(self.A, study(2, "2024-01-10T10:00:00", name="  series   p "))["comparability"]["comparable"])

    def test_sex_mismatch_rejected(self):
        self.assertFalse(lg.compare(self.A, study(2, "2024-01-10T10:00:00", sex="Male"))["comparability"]["comparable"])

    def test_left_versus_right_rejected(self):
        res = lg.compare(self.A, study(2, "2024-01-10T10:00:00", side="Right"))
        self.assertFalse(res["comparability"]["comparable"])
        self.assertTrue(any("side differs" in r for r in res["comparability"]["blocking_reasons"]))

    def test_modality_mismatch_rejected(self):
        self.assertFalse(lg.compare(self.A, study(2, "2024-01-10T10:00:00", modality="MRI"))["comparability"]["comparable"])

    def test_method_mismatch_rejected(self):
        self.assertFalse(lg.compare(self.A, study(2, "2024-01-10T10:00:00", method="M2"))["comparability"]["comparable"])

    def test_imaging_view_unrecorded_is_a_warning_not_silent(self):
        res = lg.compare(self.A, self.B)
        self.assertTrue(any("imaging view" in w for w in res["comparability"]["warnings"]))
        self.assertIn("not verified", " ".join(res["comparability"]["warnings"]) + lg.IDENTITY_BASIS.replace("not independently verified", "not verified"))

    def test_wrong_chronological_order_rejected(self):
        res = lg.compare(self.B, self.A)
        self.assertFalse(res["comparability"]["comparable"])
        self.assertTrue(any("not earlier" in r for r in res["comparability"]["blocking_reasons"]))

    def test_same_timestamp_rejected(self):
        self.assertFalse(lg.compare(self.A, study(2, "2023-01-10T10:00:00"))["comparability"]["comparable"])

    def test_duplicate_image_and_same_study_rejected(self):
        dup = dict(self.B, image_hash=self.A["image_hash"])
        self.assertFalse(lg.compare(self.A, dup)["comparability"]["comparable"])
        self.assertFalse(lg.compare(self.A, self.A)["comparability"]["comparable"])

    def test_decreasing_age_contradicts_one_patient(self):
        self.assertFalse(lg.compare(self.A, study(2, "2024-01-10T10:00:00", age=50))["comparability"]["comparable"])

    def test_missing_values_are_safe(self):
        b = copy.deepcopy(self.B)
        b["bone_measurements"].pop("tibial_slope_deg")
        row = next(m for m in lg.compare(self.A, b)["measurements"] if m["id"] == "bone:tibial_slope_deg")
        self.assertIsNone(row["difference"])
        self.assertFalse(row["available"])

    def test_zero_denominator(self):
        d = lg.difference(0.0, 2.0)
        self.assertEqual(d["difference"], 2.0)
        self.assertIsNone(d["percentage_difference"])
        self.assertIn("undefined", d["note"])
        self.assertIsNone(lg.difference(None, 2.0)["difference"])

    def test_non_numeric_and_bool_values_are_not_numbers(self):
        a = copy.deepcopy(self.A)
        a["meniscus"]["assessment"]["mean_thickness_mm"] = "n/a"
        row = next(m for m in lg.compare(a, self.B)["measurements"] if m["id"] == "meniscus:mean")
        self.assertIsNone(row["previous"])

    def test_no_progression_claim_in_output(self):
        text = json.dumps(lg.compare(self.A, self.B)).lower()
        for word in ("progress", "deteriorat", "improv", "worsen"):
            if word == "progress":
                self.assertIn("not a statement of disease progression", text)
            else:
                self.assertNotIn(word, text.replace("not a statement of disease progression or improvement", ""))

    def test_three_study_series_is_chronological_and_not_interpolated(self):
        c = study(3, "2025-01-10T10:00:00", mean=3.2)
        series = lg.build_series(c, [self.B, self.A], "meniscus:mean")  # supplied out of order
        self.assertEqual([p["examined_at"][:4] for p in series["points"]], ["2023", "2024", "2025"])
        self.assertEqual([p["value"] for p in series["points"]], [4.0, 3.6, 3.2])
        self.assertTrue(series["trend_available"])

    def test_missing_point_stays_missing(self):
        mid = copy.deepcopy(self.B)
        mid["meniscus"]["assessment"].pop("mean_thickness_mm")
        series = lg.build_series(study(3, "2025-01-10T10:00:00", mean=3.2), [mid, self.A], "meniscus:mean")
        self.assertIsNone(series["points"][1]["value"])
        self.assertFalse(series["trend_available"])  # only two real values: no trend is manufactured

    def test_two_studies_give_direct_comparison_not_a_trend(self):
        series = lg.build_series(self.B, [self.A], "meniscus:mean")
        self.assertFalse(series["trend_available"])
        self.assertIn("Direct comparison only", series["note"])

    def test_series_excludes_other_side_other_patient_and_duplicates(self):
        others = [self.A, study(5, "2023-06-01T10:00:00", side="Right"), study(6, "2023-07-01T10:00:00", name="Other"),
                  dict(study(7, "2023-08-01T10:00:00"), image_hash=self.A["image_hash"])]
        series = lg.build_series(self.B, others, "meniscus:mean")
        self.assertEqual({p["study_id"] for p in series["points"]}, {"s1", "s2"})
        self.assertEqual({e["study_id"] for e in series["excluded"]}, {"s5", "s6", "s7"})

    def test_unknown_measurement_rejected(self):
        with self.assertRaises(ValueError):
            lg.build_series(self.A, [], "does:not:exist")

    def test_originals_are_never_mutated(self):
        a, b = copy.deepcopy(self.A), copy.deepcopy(self.B)
        lg.compare(a, b)
        lg.candidate_timeline(b, [a])
        lg.build_series(b, [a], "meniscus:mean")
        self.assertEqual(a, self.A)
        self.assertEqual(b, self.B)


class LongitudinalApiTests(ApiTestCase):
    def test_candidates_compare_and_series_endpoints(self):
        for s in (study(1, "2023-01-10T10:00:00", mean=4.0), study(2, "2024-01-10T10:00:00", mean=3.6),
                  study(3, "2025-01-10T10:00:00", mean=3.2), study(4, "2024-06-01T10:00:00", side="Right")):
            self.fake.put(self.user, s)
        cand = self.client.get("/api/longitudinal/s3/candidates").json()
        by = {s["study_id"]: s for s in cand["studies"]}
        self.assertTrue(by["s1"]["comparable_with_current"])
        self.assertFalse(by["s4"]["comparable_with_current"])
        self.assertEqual([s["study_id"] for s in cand["studies"]], ["s1", "s2", "s4", "s3"])
        cmp_ = self.client.post("/api/longitudinal/compare", json={"previous_id": "s1", "current_id": "s3"}).json()
        self.assertTrue(cmp_["comparability"]["comparable"])
        bad = self.client.post("/api/longitudinal/compare", json={"previous_id": "s4", "current_id": "s3"}).json()
        self.assertFalse(bad["comparability"]["comparable"])
        ser = self.client.get("/api/longitudinal/s3/series?measurement=meniscus:mean").json()
        self.assertTrue(ser["trend_available"])
        self.assertEqual(self.client.get("/api/longitudinal/s3/series?measurement=nope").status_code, 400)

    def test_other_users_studies_are_not_reachable(self):
        self.fake.put("someone-else", study(1, "2023-01-10T10:00:00"))
        self.fake.put(self.user, study(2, "2024-01-10T10:00:00"))
        self.assertEqual(self.client.post("/api/longitudinal/compare", json={"previous_id": "s1", "current_id": "s2"}).status_code, 404)
        cand = self.client.get("/api/longitudinal/s2/candidates").json()
        self.assertEqual([s["study_id"] for s in cand["studies"]], ["s2"])

    def test_unauthenticated_rejected(self):
        app.dependency_overrides.clear()
        self.assertEqual(TestClient(app).post("/api/longitudinal/compare", json={"previous_id": "a", "current_id": "b"}).status_code, 401)


# =================================================================================== review
class ReviewApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.rec = sample_record()
        self.fake.put(self.user, self.rec)
        self.sid = self.rec["analysis_id"]

    def post(self, **kw):
        body = {"study_id": self.sid, "finding_id": "meniscus:mean", "decision": "confirmed"}
        body.update(kw)
        return self.client.post("/api/reviews", json=body)

    def test_findings_start_pending(self):
        data = self.client.get("/api/reviews/" + self.sid).json()
        self.assertTrue(data["findings"])
        self.assertTrue(all(f["state"] == "pending_review" for f in data["findings"]))
        self.assertEqual(data["persistence"], "local_file")
        self.assertIn("not verified", data["reviewer_label"])

    def test_each_decision_is_recorded_with_state_transition(self):
        for i, dec in enumerate(("confirmed", "needs_further_review", "disagreed")):
            r = self.post(decision=dec, comment="note %d" % i)
            self.assertEqual(r.status_code, 200)
            ev = r.json()["review"]
            self.assertEqual(ev["new_state"], dec)
            self.assertEqual(ev["sequence"], i + 1)
        evs = self.client.get("/api/reviews/" + self.sid).json()["events"]
        self.assertEqual([e["previous_state"] for e in evs], ["pending_review", "confirmed", "needs_further_review"])
        self.assertEqual([e["new_state"] for e in evs], ["confirmed", "needs_further_review", "disagreed"])

    def test_reviewer_identity_comes_from_the_session_not_the_body(self):
        r = self.client.post("/api/reviews", json={"study_id": self.sid, "finding_id": "meniscus:mean", "decision": "confirmed",
                                                   "reviewer_id": "attacker", "user_id": "attacker"})
        self.assertEqual(r.json()["review"]["reviewer_id"], self.user)

    def test_unauthenticated_cannot_submit(self):
        app.dependency_overrides.clear()
        r = TestClient(app).post("/api/reviews", json={"study_id": self.sid, "finding_id": "meniscus:mean", "decision": "confirmed"})
        self.assertEqual(r.status_code, 401)

    def test_ownership_enforced(self):
        self.as_user("intruder")
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.client.get("/api/reviews/" + self.sid).status_code, 404)

    def test_validation(self):
        self.assertEqual(self.post(decision="approved").status_code, 400)
        self.assertEqual(self.post(comment="x" * 1001).status_code, 400)
        self.assertEqual(self.post(finding_id="bad id with spaces!").status_code, 400)
        self.assertEqual(self.post(finding_id="meniscus:does_not_exist").status_code, 404)
        self.assertEqual(self.post(request_id="no").status_code, 400)
        self.assertEqual(self.post(expected_previous_state="bogus").status_code, 400)
        self.assertEqual(self.post(comment="x" * 1000).status_code, 200)

    def test_duplicate_request_id_creates_one_event(self):
        a = self.post(request_id="req-00000001").json()["review"]
        b = self.post(request_id="req-00000001").json()["review"]
        self.assertEqual(a["review_id"], b["review_id"])
        self.assertTrue(b.get("duplicate"))
        self.assertEqual(self.client.get("/api/reviews/" + self.sid).json()["total_events"], 1)

    def test_identical_consecutive_submission_is_not_a_new_event(self):
        self.post(comment="same")
        again = self.post(comment="same").json()["review"]
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(self.client.get("/api/reviews/" + self.sid).json()["total_events"], 1)
        self.post(comment="different")
        self.assertEqual(self.client.get("/api/reviews/" + self.sid).json()["total_events"], 2)

    def test_stale_expected_state_is_a_conflict(self):
        self.post(decision="confirmed")
        r = self.post(decision="disagreed", expected_previous_state="pending_review")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.get("/api/reviews/" + self.sid).json()["total_events"], 1)

    def test_concurrent_updates_only_one_wins(self):
        results = []
        barrier = threading.Barrier(6)

        def worker(i):
            barrier.wait()
            c = TestClient(app)
            r = c.post("/api/reviews", json={"study_id": self.sid, "finding_id": "oa:classification", "decision": "confirmed",
                                              "comment": "w%d" % i, "expected_previous_state": "pending_review"})
            results.append(r.status_code)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(results), [200] + [409] * 5)
        evs = [e for e in self.client.get("/api/reviews/" + self.sid).json()["events"] if e["finding_id"] == "oa:classification"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["sequence"], 1)

    def test_history_is_append_only_and_keeps_every_event(self):
        for dec in ("confirmed", "disagreed", "needs_further_review"):
            self.post(decision=dec, comment=dec)
        evs = self.client.get("/api/reviews/" + self.sid).json()["events"]
        self.assertEqual([e["comment"] for e in evs], ["confirmed", "disagreed", "needs_further_review"])
        one = self.client.get("/api/reviews/{}/{}".format(self.sid, evs[0]["review_id"])).json()["review"]
        self.assertEqual(one["decision"], "confirmed")
        self.assertEqual(self.client.get("/api/reviews/{}/nope".format(self.sid)).status_code, 404)

    def test_reviews_never_change_the_stored_analysis(self):
        before = copy.deepcopy(self.fake.rows[(self.user, self.sid)])
        self.post(decision="disagreed", comment="I disagree")
        self.assertEqual(self.fake.rows[(self.user, self.sid)], before)

    def test_ai_observation_review_requires_verifiable_provenance_and_snapshots_the_text(self):
        text = "Medial joint space appears narrowed."
        p = prov.ai_provenance("visual_scan", text, self.sid, "OpenRouter", "m")
        fid = "ai:visual_scan:" + p["content_sha256"][:16]
        r = self.post(finding_id=fid, decision="disagreed", comment="not seen", ai={"provenance": p, "text": text})
        self.assertEqual(r.status_code, 200)
        ev = r.json()["review"]
        self.assertEqual(ev["content_snapshot"], text)
        self.assertEqual(ev["content_sha256"], p["content_sha256"])
        # text edited after signing -> rejected
        self.assertEqual(self.post(finding_id=fid, ai={"provenance": p, "text": text + " edited"}).status_code, 400)
        # no provenance -> rejected
        self.assertEqual(self.post(finding_id=fid).status_code, 400)
        # provenance from another study -> rejected
        other = prov.ai_provenance("visual_scan", text, "another-study", "OpenRouter", "m")
        self.assertEqual(self.post(finding_id=fid, ai={"provenance": other, "text": text}).status_code, 400)
        # wrong finding id for that observation -> rejected
        self.assertEqual(self.post(finding_id="ai:visual_scan:0000000000000000", ai={"provenance": p, "text": text}).status_code, 400)

    def test_report_level_review(self):
        self.assertEqual(self.post(finding_id="report:" + self.sid).status_code, 200)

    def test_pending_and_reviewed_states_in_listing(self):
        self.post(finding_id="meniscus:mean", decision="needs_further_review")
        states = {f["finding_id"]: f["state"] for f in self.client.get("/api/reviews/" + self.sid).json()["findings"]}
        self.assertEqual(states["meniscus:mean"], "needs_further_review")
        self.assertEqual(states["meniscus:mid_body"], "pending_review")

    def test_reviewer_only_sees_own_history(self):
        self.post()
        self.as_user("other")
        self.fake.put("other", dict(self.rec))  # same id, other owner: separate account
        self.assertEqual(self.client.get("/api/reviews/" + self.sid).json()["total_events"], 0)


class SupabaseReviewStoreTests(unittest.TestCase):
    """The Supabase backend maps a unique-constraint violation (a concurrent writer) to a 409."""

    class _Table:
        def __init__(self, fail=None, rows=None):
            self.fail, self.rows = fail, rows or []

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def insert(self, ev):
            self.pending = ev
            return self

        def execute(self):
            if getattr(self, "pending", None) is not None:
                if self.fail:
                    raise Exception(self.fail)
                self.pending = None
                return mock.Mock(data=[])
            return mock.Mock(data=self.rows)

    class _Client:
        def __init__(self, table):
            self.t = table

        def table(self, name):
            assert name == "study_reviews"
            return self.t

    def event(self):
        return rv.new_event("s1", "u1", {"finding_id": "x:1", "kind": "k", "title": "t"}, "confirmed", "c", None, None)

    def test_insert_and_conflict_mapping(self):
        ok = rv.SupabaseReviewStore(lambda: self._Client(self._Table()))
        self.assertEqual(ok.append("u1", self.event())["sequence"], 1)
        racing = rv.SupabaseReviewStore(lambda: self._Client(self._Table(fail="duplicate key value violates unique constraint 23505")))
        with self.assertRaises(rv.ReviewConflict):
            racing.append("u1", self.event())

    def test_missing_table_means_store_unavailable(self):
        class Boom(self._Table):
            def execute(self):
                raise Exception("relation study_reviews does not exist")
        s = rv.SupabaseReviewStore(lambda: self._Client(Boom()))
        with self.assertRaises(rv.StoreUnavailable):
            s.list_events("u1", "s1")

    def test_auto_mode_falls_back_to_the_labelled_local_file(self):
        rv._store_cache.clear()
        with mock.patch.dict(os.environ, {"REVIEW_STORE": "auto"}):
            store = rv.get_store(lambda: None)
        self.assertEqual(store.name, "local_file")
        self.assertIn("not a durable clinical record", store.description)
        rv._store_cache.clear()


# ====================================================================================== demo
class DemoApiTests(ApiTestCase):
    def test_demo_requires_the_normal_login(self):
        app.dependency_overrides.clear()
        for path in ("/api/demo/cases", "/api/demo/longitudinal", "/api/demo/cases/OAI_sample_03/cached-ai"):
            self.assertEqual(TestClient(app).get(path).status_code, 401, path)

    def test_cases_are_the_bundled_synthetic_samples(self):
        data = self.client.get("/api/demo/cases").json()
        self.assertEqual(data["count"], 5)
        self.assertIn("Synthetic", data["label"])
        self.assertTrue(all(c["synthetic"] for c in data["items"]))

    def test_case_is_built_in_memory_and_flagged_synthetic_and_not_saved(self):
        with mock.patch.object(db, "save_analysis", side_effect=AssertionError("demo must not save")):
            rec = self.client.get("/api/demo/cases/OAI_sample_03").json()
        self.assertTrue(rec["demo"] and rec["synthetic"])
        self.assertEqual(rec["meniscus"]["measurements"][0]["thickness_mm"], sr.get("OAI_sample_03")["meniscus"]["anterior_horn_mm"])
        self.assertEqual(self.client.get("/api/demo/cases/nope").status_code, 404)

    def test_case_provenance_uses_the_same_service(self):
        out = self.client.get("/api/demo/cases/OAI_sample_03/provenance").json()
        self.assertEqual(out["origin"]["type"], "reference_case_sidecar")

    def test_demo_record_goes_through_the_existing_pdf_service(self):
        rec = self.client.get("/api/demo/cases/OAI_sample_03").json()
        r = self.client.post("/api/report", json={"record": rec})  # the app's existing, unchanged endpoint
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_cached_ai_is_labelled_and_valid_for_matching_source(self):
        d = self.client.get("/api/demo/cases/OAI_sample_03/cached-ai").json()
        self.assertTrue(d["valid"])
        self.assertEqual(d["mode"], "cached")
        self.assertIn("Pre-generated synthetic demonstration result", d["label"])
        self.assertFalse(d["provenance"]["live"])
        self.assertIsNone(d["provenance"]["model"])
        self.assertNotIn("signature", d["provenance"])

    def test_cached_ai_is_invalidated_when_source_or_model_or_fixture_changes(self):
        sample = sr.get("OAI_sample_03")
        with mock.patch.dict(sample, {"md5": "0" * 32}):
            d = self.client.get("/api/demo/cases/OAI_sample_03/cached-ai").json()
        self.assertFalse(d["valid"])
        self.assertIn("source image changed", d["reason"])
        self.assertNotIn("visual_scan", d)
        with mock.patch.dict(sample, {"inference": {"backbone": "other model"}}):
            self.assertIn("model changed", self.client.get("/api/demo/cases/OAI_sample_03/cached-ai").json()["reason"])
        with mock.patch.object(demo_router, "FIXTURE_VERSION", "demo-fixture-999"):
            self.assertIn("fixture version", self.client.get("/api/demo/cases/OAI_sample_03/cached-ai").json()["reason"])

    def test_demo_longitudinal_series_is_labelled_synthetic_and_uses_the_real_comparator(self):
        d = self.client.get("/api/demo/longitudinal").json()
        self.assertTrue(d["synthetic"])
        self.assertIn("SYNTHETIC", d["label"])
        self.assertTrue(d["comparison"]["comparability"]["comparable"])
        self.assertTrue(d["series"]["trend_available"])
        self.assertEqual(len(d["series"]["points"]), 3)
        self.assertFalse(d["rejected_example"]["comparability"]["comparable"])
        self.assertTrue(any("side differs" in r for r in d["rejected_example"]["comparability"]["blocking_reasons"]))

    def test_demo_makes_no_openrouter_call(self):
        with mock.patch.object(orc.httpx, "post", side_effect=AssertionError("OpenRouter called")):
            for path in ("/api/demo/cases", "/api/demo/cases/OAI_sample_01", "/api/demo/cases/OAI_sample_01/cached-ai",
                         "/api/demo/longitudinal", "/api/demo/cases/OAI_sample_01/provenance"):
                self.assertEqual(self.client.get(path).status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
