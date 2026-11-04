"""SYNTH-KNEE-006: one synthetic patient, two examinations, two different radiographs.

Checks that the two stored records belong together by explicit ID only, that their numbers come from the
existing pipeline (not typed in), that the existing comparison logic discovers and compares them, and that
unrelated synthetic patients - even namesakes with identical sex/side/modality - are never compared.

    .venv/Scripts/python -m pytest tests/test_synth_knee_006.py -q
"""

import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, HERE)

from fastapi.testclient import TestClient

from main import app
from routers import demo as demo_router
from routers.analysis import get_current_user
from services import longitudinal_service as lg
from services import sample_registry as sr
from test_clinical_workflow import ApiTestCase, study

SYNTH_DIR = os.path.join(ROOT, "backend", "data", "demo", "synth_knee_006")
PID = "SYNTH-KNEE-006"


def load(name):
    with open(os.path.join(SYNTH_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def generator():
    spec = importlib.util.spec_from_file_location("make_synth_knee_006", os.path.join(ROOT, "tools", "make_synth_knee_006.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE, FOLLOW = load("baseline.json"), load("followup.json")


class StoredRecordsTests(unittest.TestCase):
    def test_two_separate_files_each_a_complete_independent_record(self):
        for name in ("baseline.json", "followup.json"):
            self.assertTrue(os.path.isfile(os.path.join(SYNTH_DIR, name)))
        for rec in (BASE, FOLLOW):
            for key in ("analysis_id", "meniscus", "bone_measurements", "implant", "quality", "uncertainty", "images", "patient"):
                self.assertIn(key, rec)

    def test_both_reference_the_same_explicit_synthetic_patient_id(self):
        self.assertEqual(BASE["synthetic_patient_id"], PID)
        self.assertEqual(FOLLOW["synthetic_patient_id"], PID)
        self.assertNotEqual(BASE["analysis_id"], FOLLOW["analysis_id"])

    def test_the_two_supplied_images_are_present_distinct_and_hash_to_the_stored_hashes(self):
        files = {r["analysis_id"]: os.path.join(SYNTH_DIR, os.path.basename(r["demo_image_url"])) for r in (BASE, FOLLOW)}
        data = {k: open(v, "rb").read() for k, v in files.items()}
        self.assertNotEqual(data["synth006-baseline"], data["synth006-followup"])
        self.assertEqual(BASE["image_hash"], hashlib.sha256(data["synth006-baseline"]).hexdigest())
        self.assertEqual(FOLLOW["image_hash"], hashlib.sha256(data["synth006-followup"]).hexdigest())
        self.assertNotEqual(BASE["demo_image_url"], FOLLOW["demo_image_url"])
        self.assertTrue(files["synth006-baseline"].endswith(".webp"))
        self.assertTrue(files["synth006-followup"].endswith(".png"))

    def test_images_are_not_any_of_the_five_existing_shipped_samples(self):
        shipped_sha, shipped_md5 = set(), set()
        for s in sr.all_samples():
            raw = sr.read_image(s["source"])
            shipped_sha.add(hashlib.sha256(raw).hexdigest())
            shipped_md5.add(hashlib.md5(raw).hexdigest())
        for rec in (BASE, FOLLOW):
            self.assertNotIn(rec["image_hash"], shipped_sha)
            self.assertNotIn("sample_source", rec)  # not the reference-sidecar path
            raw = open(os.path.join(SYNTH_DIR, os.path.basename(rec["demo_image_url"])), "rb").read()
            self.assertNotIn(hashlib.md5(raw).hexdigest(), shipped_md5)

    def test_same_side_modality_and_view_with_distinct_ordered_examination_dates(self):
        self.assertEqual(BASE["patient"]["affected_side"], "Right")
        self.assertEqual(BASE["patient"]["affected_side"], FOLLOW["patient"]["affected_side"])
        self.assertEqual(BASE["patient"]["imaging_type"], FOLLOW["patient"]["imaging_type"])
        self.assertEqual(BASE["imaging_view"], FOLLOW["imaging_view"])
        self.assertEqual((BASE["examined_at"][:10], FOLLOW["examined_at"][:10]), ("2022-03-14", "2025-03-20"))
        self.assertLess(lg.exam_time(BASE), lg.exam_time(FOLLOW))

    def test_follow_up_bilateral_film_selects_the_right_knee_on_the_viewers_left(self):
        roi = FOLLOW["images"]["roi"]
        self.assertTrue(roi["detected"])
        self.assertLessEqual(roi["x"] + roi["w"], 0.6 * FOLLOW["images"]["width"])  # left half = patient's right knee

    def test_clearly_labelled_synthetic_and_honest_about_where_the_numbers_come_from(self):
        for rec in (BASE, FOLLOW):
            self.assertTrue(rec["synthetic"] and rec["demo"])
            self.assertIn("SYNTHETIC DEMONSTRATION DATA", rec["demo_label"])
            self.assertIn("not verified films of one person", rec["demo_label"])
            notes = " ".join(rec["demo_notes"])
            self.assertIn("deterministic simulation", notes)
            self.assertIn("progression", notes)

    def test_records_came_from_the_real_analyze_endpoint_and_regenerate_identically(self):
        fresh = generator().run()
        for (exam, rec), stored in zip(fresh, (BASE, FOLLOW)):
            for key in ("meniscus", "bone_measurements", "implant", "quality", "uncertainty", "patient", "provenance",
                        "image_hash", "overlay_colors", "synthetic_patient_id", "examined_at", "imaging_view"):
                self.assertEqual(rec[key], stored[key], "{} differs for {}".format(key, exam["file"]))
            self.assertEqual(rec["images"]["roi"], stored["images"]["roi"])

    def test_the_two_records_have_independently_computed_different_results(self):
        self.assertNotEqual(BASE["meniscus"]["assessment"]["mean_thickness_mm"], FOLLOW["meniscus"]["assessment"]["mean_thickness_mm"])
        self.assertNotEqual(BASE["quality"]["score_pct"], FOLLOW["quality"]["score_pct"])

    def test_existing_shipped_samples_are_unmodified(self):
        for s in sr.all_samples():
            with open(os.path.join(sr.SAMPLES_DIR, s["image_file"]), "rb") as fh:
                self.assertEqual(hashlib.md5(fh.read()).hexdigest(), s["md5"], s["source"])


class IdentityRuleTests(unittest.TestCase):
    def pair(self, **b_overrides):
        b = copy.deepcopy(FOLLOW)
        b.update(b_overrides)
        return BASE, b

    def test_records_with_the_same_explicit_id_are_associated_and_comparable(self):
        res = lg.compare(BASE, FOLLOW)
        self.assertTrue(res["comparability"]["comparable"], res["comparability"]["blocking_reasons"])
        self.assertIn("NOT inferred from name or sex", res["identity_basis"])
        self.assertTrue(res["measurements"])

    def test_identity_does_not_depend_on_name_or_sex(self):
        b = copy.deepcopy(FOLLOW)
        b["patient"] = dict(b["patient"], name="A Completely Different Name", sex="Male")
        self.assertTrue(lg.compare(BASE, b)["comparability"]["comparable"])

    def test_namesake_with_a_different_id_is_a_different_patient(self):
        decoy = copy.deepcopy(FOLLOW)
        decoy["synthetic_patient_id"] = "SYNTH-KNEE-007"  # identical name, sex, side, modality, view
        res = lg.compare(BASE, decoy)
        self.assertFalse(res["comparability"]["comparable"])
        self.assertTrue(any("explicit patient ID" in r for r in res["comparability"]["blocking_reasons"]))
        self.assertEqual(res["measurements"], [])

    def test_record_without_an_id_cannot_be_matched_to_an_id_bearing_record_by_name(self):
        no_id = copy.deepcopy(FOLLOW)
        no_id.pop("synthetic_patient_id")
        self.assertFalse(lg.compare(BASE, no_id)["comparability"]["comparable"])
        self.assertFalse(lg.compare(no_id, BASE)["comparability"]["comparable"])

    def test_unrelated_synthetic_patients_are_never_compared(self):
        unrelated = load_series_study()
        for a, b in ((BASE, unrelated), (unrelated, FOLLOW)):
            self.assertFalse(lg.compare(a, b)["comparability"]["comparable"])
        self.assertFalse(lg.compare(BASE, study(9, "2022-01-01T00:00:00", name=PID, side="Left"))["comparability"]["comparable"])

    def test_old_name_rule_is_unchanged_for_records_without_ids(self):
        self.assertTrue(lg.compare(study(1, "2023-01-10T10:00:00"), study(2, "2024-01-10T10:00:00"))["comparability"]["comparable"])
        self.assertFalse(lg.compare(study(1, "2023-01-10T10:00:00"), study(2, "2024-01-10T10:00:00", name="Other"))["comparability"]["comparable"])

    def test_examination_time_not_analysis_time_decides_order(self):
        b, f = copy.deepcopy(BASE), copy.deepcopy(FOLLOW)
        b["created_at"], f["created_at"] = "2030-01-01T00:00:00", "2020-01-01T00:00:00"  # analysis order reversed
        self.assertTrue(lg.compare(b, f)["comparability"]["comparable"])
        self.assertFalse(lg.compare(f, b)["comparability"]["comparable"])

    def test_imaging_view_mismatch_is_rejected_and_a_matching_view_is_not_warned_about(self):
        prev, cur = self.pair(imaging_view="lateral")
        self.assertFalse(lg.compare(prev, cur)["comparability"]["comparable"])
        ok = lg.compare(BASE, FOLLOW)["comparability"]
        self.assertFalse(any("imaging view" in w.lower() for w in ok["warnings"]))

    def test_side_and_modality_still_enforced(self):
        prev, cur = self.pair()
        cur["patient"] = dict(cur["patient"], affected_side="Left")
        self.assertFalse(lg.compare(prev, cur)["comparability"]["comparable"])
        prev, cur = self.pair()
        cur["patient"] = dict(cur["patient"], imaging_type="MRI")
        self.assertFalse(lg.compare(prev, cur)["comparability"]["comparable"])


def load_series_study():
    with open(os.path.join(ROOT, "backend", "data", "demo", "longitudinal_demo.json"), encoding="utf-8") as fh:
        return json.load(fh)["studies"][-1]


class SynthEndpointTests(ApiTestCase):
    def get(self):
        return self.client.get("/api/demo/longitudinal?series_id=" + PID).json()

    def test_series_listing_includes_both_demo_series(self):
        ids = [s["series_id"] for s in self.client.get("/api/demo/longitudinal/series").json()["items"]]
        self.assertEqual(ids, ["DEMO-SERIES-001", PID])

    def test_existing_demo_series_response_is_unchanged(self):
        d = self.client.get("/api/demo/longitudinal").json()
        self.assertEqual(d["series_id"], "DEMO-SERIES-001")
        self.assertTrue(d["series"]["trend_available"])
        self.assertTrue(d["image_url"].endswith("/OAI_sample_03/image"))

    def test_existing_endpoint_discovers_and_compares_the_two_records(self):
        d = self.get()
        cmp_ = d["comparison"]
        self.assertTrue(cmp_["comparability"]["comparable"])
        self.assertEqual(cmp_["previous"]["study_id"], "synth006-baseline")
        self.assertEqual(cmp_["current"]["study_id"], "synth006-followup")
        self.assertEqual({s["study_id"] for s in d["timeline"]["studies"]}, {"synth006-baseline", "synth006-followup"})
        self.assertIn("NOT inferred from name or sex", cmp_["identity_basis"])

    def test_previous_and_current_images_are_two_different_images_side_by_side(self):
        cmp_ = self.get()["comparison"]
        self.assertNotEqual(cmp_["previous"]["image_url"], cmp_["current"]["image_url"])
        self.assertEqual(cmp_["previous"]["image_view"], cmp_["current"]["image_view"])
        self.assertEqual(cmp_["previous"]["synthetic_patient_id"], PID)
        for url in (cmp_["previous"]["image_url"], cmp_["current"]["image_url"]):
            self.assertEqual(self.client.get(url).status_code, 200)  # the images are actually served

    def test_differences_are_computed_from_the_stored_values(self):
        by_id = {m["id"]: m for m in self.get()["comparison"]["measurements"]}
        for mid, spec in [(m[0], m[3]) for m in lg.MEASUREMENTS]:
            p, c = lg.get_value(BASE, spec), lg.get_value(FOLLOW, spec)
            row = by_id[mid]
            self.assertEqual((row["previous"], row["current"]), (p, c))
            self.assertEqual(row["difference"], c - p)
            self.assertEqual(row["percentage_difference"], (c - p) / p * 100)

    def test_only_two_examinations_so_no_trend_is_shown(self):
        s = self.get()["series"]
        self.assertFalse(s["trend_available"])
        self.assertEqual(len(s["points"]), 2)

    def test_unrelated_synthetic_patient_is_rejected_in_the_same_response(self):
        ex = self.get()["rejected_example"]
        self.assertFalse(ex["comparability"]["comparable"])
        self.assertTrue(any("explicit patient ID" in r for r in ex["comparability"]["blocking_reasons"]))

    def test_discovery_runs_over_the_pool_not_a_hard_coded_pair(self):
        third = copy.deepcopy(BASE)
        third.update(analysis_id="synth006-extra", examined_at="2023-06-01T00:00:00", image_hash="third-image")
        decoy = copy.deepcopy(FOLLOW)
        decoy.update(analysis_id="decoy", synthetic_patient_id="SYNTH-KNEE-007", examined_at="2023-01-01T00:00:00", image_hash="decoy-image")
        pool = demo_router.demo_pool() + [third, decoy]
        with mock.patch.object(demo_router, "demo_pool", return_value=pool):
            d = self.get()
        ids = {s["study_id"] for s in d["timeline"]["studies"]}
        self.assertIn("synth006-extra", ids)      # same explicit id: discovered
        self.assertNotIn("decoy", ids)            # same name/sex/side, other id: not even a candidate
        self.assertEqual(d["comparison"]["previous"]["study_id"], "synth006-extra")  # latest earlier comparable study
        self.assertEqual(len(d["series"]["points"]), 3)
        self.assertTrue(d["series"]["trend_available"])

    def test_no_progression_claim_and_labelled_synthetic(self):
        d = self.get()
        self.assertIn("SYNTHETIC DEMONSTRATION DATA", d["label"])
        text = json.dumps(d).lower()
        self.assertIn("not a statement of disease progression", text)
        for w in ("progressed", "deteriorat", "worsened", "improved"):
            self.assertNotIn(w, text)
        self.assertTrue(any("progression" in n for n in d["notes"]))

    def test_unknown_series_is_404_and_login_is_required(self):
        self.assertEqual(self.client.get("/api/demo/longitudinal?series_id=nope").status_code, 404)
        app.dependency_overrides.clear()
        self.assertEqual(TestClient(app).get("/api/demo/longitudinal?series_id=" + PID).status_code, 401)

    def test_real_comparison_endpoint_applies_the_same_identity_rule(self):
        a, b = copy.deepcopy(BASE), copy.deepcopy(FOLLOW)
        decoy = copy.deepcopy(FOLLOW)
        decoy.update(analysis_id="decoy", synthetic_patient_id="SYNTH-KNEE-007")
        for r in (a, b, decoy):
            self.fake.put(self.user, r)
        ok = self.client.post("/api/longitudinal/compare", json={"previous_id": a["analysis_id"], "current_id": b["analysis_id"]}).json()
        bad = self.client.post("/api/longitudinal/compare", json={"previous_id": a["analysis_id"], "current_id": "decoy"}).json()
        self.assertTrue(ok["comparability"]["comparable"])
        self.assertFalse(bad["comparability"]["comparable"])

    def test_no_openrouter_request(self):
        from services import openrouter_client as orc
        with mock.patch.object(orc.httpx, "post", side_effect=AssertionError("OpenRouter called")):
            self.assertEqual(self.client.get("/api/demo/longitudinal?series_id=" + PID).status_code, 200)


# ---------------------------------------------------------------------------- upload flow
import cv2
import numpy as np

from routers.analysis import get_bearer_token
from services import supabase_client as sbc


def _png(seed=3, size=360):
    img = (np.random.RandomState(seed).rand(size, size, 3) * 255).astype(np.uint8)
    return cv2.imencode(".png", img)[1].tobytes()


class UploadFlowTests(unittest.TestCase):
    """Baseline upload -> first record; follow-up upload -> second record; both paired by the explicit ID."""

    def setUp(self):
        self.saved = []
        self.p = mock.patch.object(sbc, "save_analysis", lambda uid, tok, rec: self.saved.append(rec))
        self.p.start()
        app.dependency_overrides[get_current_user] = lambda: "user-1"
        app.dependency_overrides[get_bearer_token] = lambda: "tok"
        self.client = TestClient(app)

    def tearDown(self):
        self.p.stop()
        app.dependency_overrides.clear()

    def upload(self, data=None, name="x.png", mime="image/png", **extra):
        form = {"name": "P", "age": "55", "sex": "Female", "imaging_type": "X-ray", "affected_side": "Right"}
        form.update(extra)
        return self.client.post("/api/analyze", files={"file": (name, data or _png(), mime)}, data=form)

    def test_optional_longitudinal_fields_are_stored_on_the_record(self):
        r = self.upload(synthetic_patient_id="SYNTH-KNEE-006", examined_date="2022-03-14", imaging_view="AP standing")
        self.assertEqual(r.status_code, 200)
        rec = r.json()
        self.assertEqual((rec["synthetic_patient_id"], rec["examined_at"], rec["imaging_view"]),
                         ("SYNTH-KNEE-006", "2022-03-14T00:00:00", "AP standing"))
        self.assertTrue(rec["synthetic"])
        self.assertEqual(self.saved[-1]["synthetic_patient_id"], "SYNTH-KNEE-006")  # persisted via the normal save path

    def test_omitting_the_fields_leaves_the_record_exactly_as_before(self):
        rec = self.upload().json()
        for k in ("synthetic_patient_id", "examined_at", "imaging_view", "synthetic"):
            self.assertNotIn(k, rec)

    def test_webp_uploads_are_accepted_and_analysed(self):
        img = (np.random.RandomState(1).rand(300, 300, 3) * 255).astype(np.uint8)
        data = cv2.imencode(".webp", img)[1].tobytes()
        self.assertEqual(self.upload(data, "knee.webp", "image/webp").status_code, 200)

    def test_invalid_metadata_is_rejected(self):
        self.assertEqual(self.upload(synthetic_patient_id="x").status_code, 400)
        self.assertEqual(self.upload(synthetic_patient_id="bad id!").status_code, 400)
        self.assertEqual(self.upload(examined_date="14/03/2022").status_code, 400)
        self.assertEqual(self.upload(examined_date="2022-02-30").status_code, 400)
        self.assertEqual(self.upload(examined_date="2999-01-01").status_code, 400)
        self.assertEqual(self.upload(imaging_view="sideways").status_code, 400)

    def test_two_uploads_give_two_independent_records_that_the_comparison_pairs_by_id(self):
        base = self.upload(_png(1), synthetic_patient_id="SYNTH-KNEE-006", examined_date="2022-03-14", imaging_view="AP standing").json()
        follow = self.upload(_png(2), synthetic_patient_id="SYNTH-KNEE-006", examined_date="2025-03-20", imaging_view="AP standing").json()
        self.assertNotEqual(base["analysis_id"], follow["analysis_id"])
        self.assertNotEqual(base["image_hash"], follow["image_hash"])
        cmp_ = lg.compare(base, follow)
        self.assertTrue(cmp_["comparability"]["comparable"], cmp_["comparability"]["blocking_reasons"])
        # same name "P" but another ID is a different patient
        other = self.upload(_png(3), synthetic_patient_id="SYNTH-KNEE-007", examined_date="2025-03-20", imaging_view="AP standing").json()
        self.assertFalse(lg.compare(base, other)["comparability"]["comparable"])


class IdDiscoveryTests(ApiTestCase):
    """History lookup for a study that has an explicit ID uses the ID, not the patient name."""

    def setUp(self):
        super().setUp()

        def by_id(uid, tok, pid, limit=50):
            return [copy.deepcopy(r) for (u, _), r in self.fake.rows.items() if u == uid and r.get("synthetic_patient_id") == pid]

        self.p2 = mock.patch.object(sbc, "list_analyses_by_patient_id", by_id)
        self.p2.start()

    def tearDown(self):
        self.p2.stop()
        super().tearDown()

    def test_records_with_the_same_id_are_found_even_under_a_different_name_and_namesakes_are_not(self):
        a, b = copy.deepcopy(BASE), copy.deepcopy(FOLLOW)
        b["patient"] = dict(b["patient"], name="Typed Differently")
        namesake = copy.deepcopy(FOLLOW)
        namesake.update(analysis_id="namesake", synthetic_patient_id="SYNTH-KNEE-007")
        for r in (a, b, namesake):
            self.fake.put(self.user, r)
        cand = self.client.get("/api/longitudinal/{}/candidates".format(b["analysis_id"])).json()
        self.assertEqual({s["study_id"] for s in cand["studies"]}, {a["analysis_id"], b["analysis_id"]})
        self.assertIn("NOT inferred from name or sex", cand["identity_basis"])

    def test_supabase_query_filters_on_the_json_field_and_is_bounded(self):
        calls = []

        class T:
            def select(self, *a):
                calls.append(("select", a))
                return self

            def eq(self, *a):
                calls.append(("eq", a))
                return self

            def filter(self, *a):
                calls.append(("filter", a))
                return self

            def order(self, *a, **k):
                return self

            def limit(self, n):
                calls.append(("limit", n))
                return self

            def execute(self):
                return mock.Mock(data=[{"record": {"analysis_id": "x"}}])

        client = mock.Mock()
        client.table.return_value = T()
        self.p2.stop()
        try:
            with mock.patch.object(sbc, "_client_for", return_value=client):
                out = sbc.list_analyses_by_patient_id("u1", "tok", "SYNTH-KNEE-006", 5000)
        finally:
            self.p2.start()
        self.assertEqual(out, [{"analysis_id": "x"}])
        self.assertIn(("filter", ("record->>synthetic_patient_id", "eq", "SYNTH-KNEE-006")), calls)
        self.assertIn(("eq", ("user_id", "u1")), calls)
        self.assertIn(("limit", 100), calls)  # capped


if __name__ == "__main__":
    unittest.main()
