"""Local translation tests with a MOCKED engine (no model, no network, no OpenRouter).

Run from repo root:  python -m pytest tests/test_translation.py -q
Real-model checks live in tests/translation_smoke.py.
"""

import os
import sys
import unittest
from unittest import mock

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient

from main import app
from routers.analysis import get_current_user
from services import local_translation_service as lts

SAMPLE = (
    "The medial joint space appears narrowed (about 2.4 mm), KL grade 3.\n"
    "\n"
    "- Alignment looks neutral on the left knee.\n"
    "- Possible osteophytes. No obvious swelling.\n"
    "These are visual observations, not a diagnosis."
)


def fake_translator(segments, tag, retry=False):
    """Pretend translation: prefixes the tag, keeps placeholders intact."""
    return ["[{}] {}".format(tag, s) for s in segments]


class ProtectionTests(unittest.TestCase):
    def test_round_trip(self):
        prot, orig = lts.protect("Thickness 2.4 mm, KL grade 3, left knee, 2024-03-05, age 61.")
        self.assertNotIn("2.4", prot)
        self.assertEqual(lts.restore(prot, orig), "Thickness 2.4 mm, KL grade 3, left knee, 2024-03-05, age 61.")

    def test_missing_placeholder_rejected(self):
        prot, orig = lts.protect("Gap 2.4 mm and 3.1 mm")
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.restore(prot.replace("0019", ""), orig)

    def test_duplicated_placeholder_rejected(self):
        prot, orig = lts.protect("Gap 2.4 mm")
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.restore(prot + " " + prot, orig)

    def test_altered_placeholder_rejected(self):
        prot, orig = lts.protect("Gap 2.4 mm")
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.restore(prot.replace("0009", "0059"), orig)


class RetryTests(unittest.TestCase):
    def test_degenerate_output_is_retried_then_accepted(self):
        calls = []

        def tr(segs, tag, retry=False):
            calls.append(retry)
            return ["a........................."] * len(segs) if not retry else ["ok " + s for s in segs]

        self.assertEqual(lts.translate_text("Hello there.", "ta", tr), "ok Hello there.")
        self.assertEqual(calls, [False, True])

    def test_lost_value_retried_then_rejected(self):
        tr = lambda segs, tag, retry=False: ["no placeholders" for _ in segs]
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.translate_text("Gap is 2.4 mm.", "hi", tr)

    def test_years_not_frozen_so_model_can_translate_them(self):
        prot, orig = lts.protect("a 61 year old")
        self.assertEqual(orig, ["61"])


class GlossaryTests(unittest.TestCase):
    def kept(self, text):
        prot, orig = lts.protect(text)
        return orig

    def test_compound_clinical_phrases_are_single_units(self):
        o = self.kept("Medial joint space narrowing, subchondral sclerosis and marginal osteophytes.")
        self.assertEqual([x.lower() for x in o],
                         ["medial joint space narrowing", "subchondral sclerosis", "marginal osteophytes"])

    def test_listed_terms_protected(self):
        text = ("medial meniscus, lateral meniscus, femur, tibia, varus, valgus, Kellgren-Lawrence grade, "
                "MRI, X-ray, AP view, medial compartment, lateral compartment, osteoarthritis (OA)")
        prot, orig = lts.protect(text)
        low = [o.lower() for o in orig]
        for term in ("medial meniscus", "lateral meniscus", "femur", "tibia", "varus", "valgus",
                     "kellgren-lawrence", "mri", "x-ray", "ap view", "medial compartment",
                     "lateral compartment", "osteoarthritis", "oa"):
            self.assertIn(term, low)

    def test_everyday_words_are_not_protected(self):
        self.assertEqual(self.kept("The weather was pleasant, so we walked to the market."), [])
        self.assertEqual(self.kept("swelling, knee pain and diet"), [])

    def test_restored_text_keeps_source_casing(self):
        prot, orig = lts.protect("Medial joint space narrowing is seen.")
        self.assertEqual(lts.restore(prot, orig), "Medial joint space narrowing is seen.")


class TextShapeTests(unittest.TestCase):
    def test_structure_and_values_preserved(self):
        out = lts.translate_text(SAMPLE, "ta", fake_translator)
        lines = out.split("\n")
        self.assertEqual(len(lines), len(SAMPLE.split("\n")))
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("- "))
        self.assertIn("2.4 mm", out)
        self.assertIn("KL grade 3", out)

    def test_bullets_keep_prefix(self):
        out = lts.translate_text("- one thing.\n- another thing.", "hi", fake_translator)
        for ln in out.split("\n"):
            self.assertTrue(ln.startswith("- "))

    def test_long_text_chunked(self):
        text = " ".join("Sentence number {} is here.".format(i) for i in range(200))
        calls = []

        def tr(segs, tag, retry=False):
            calls.append(len(segs))
            return segs

        lts.translate_text(text, "ml", tr)
        self.assertTrue(all(c <= lts.BATCH_SIZE for c in calls))
        self.assertGreater(sum(calls), 1)

    def test_wrong_count_is_error(self):
        with self.assertRaises(lts.TranslationError):
            lts.translate_text("Hello there.", "te", lambda s, t, retry=False: [])


class ServiceTests(unittest.TestCase):
    def test_english_no_model(self):
        with mock.patch.object(lts, "get_engine", side_effect=AssertionError("model touched")):
            self.assertEqual(lts.translate("Hello", "en"), "Hello")

    def test_invalid_language(self):
        with self.assertRaises(ValueError):
            lts.translate("Hello", "fr")

    def test_empty(self):
        with self.assertRaises(ValueError):
            lts.translate("   ", "ta")

    def test_too_long(self):
        with self.assertRaises(ValueError):
            lts.translate("a" * (lts.MAX_CHARS + 1), "ta")

    def test_engine_created_once(self):
        lts._engine = None
        made = []

        class E:
            def __init__(self):
                made.append(1)

            def __call__(self, segs, tag, retry=False):
                return segs

        with mock.patch.object(lts, "_Engine", E):
            for lang in ("hi", "ta", "ml", "te"):
                lts.translate("Hello there.", lang)
        lts._engine = None
        self.assertEqual(len(made), 1)

    def test_failure_wrapped(self):
        lts._engine = None

        class E:
            def __call__(self, segs, tag, retry=False):
                raise RuntimeError("secret patient text in trace")

        lts._engine = E()
        try:
            with self.assertRaises(lts.TranslationError) as cm:
                lts.translate("Hello there.", "ta")
            self.assertNotIn("secret", str(cm.exception))
        finally:
            lts._engine = None


class RouterTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: "user-1"
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def post(self, **body):
        return self.client.post("/api/translate", json=body)

    def test_requires_auth(self):
        app.dependency_overrides.clear()
        r = TestClient(app).post("/api/translate", json={"text": "x", "target_language": "ta"})
        self.assertEqual(r.status_code, 401)

    def test_english_passthrough(self):
        r = self.post(text="Hello", target_language="en", content_type="food_advice")
        self.assertEqual(r.json(), {"translated_text": "Hello", "source_language": "en", "target_language": "en",
                                    "terminology_version": lts.TERMINOLOGY_VERSION,
                                    "pipeline_version": lts.PIPELINE_VERSION})

    def test_success(self):
        with mock.patch.object(lts, "translate", return_value="வணக்கம்"):
            r = self.post(text="Hello", target_language="ta", content_type="chat_message")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["translated_text"], "வணக்கம்")

    def test_bad_language(self):
        self.assertEqual(self.post(text="Hello", target_language="fr").status_code, 400)

    def test_bad_content_type(self):
        self.assertEqual(self.post(text="Hello", target_language="ta", content_type="x").status_code, 400)

    def test_empty(self):
        self.assertEqual(self.post(text=" ", target_language="ta").status_code, 400)

    def test_too_large(self):
        self.assertEqual(self.post(text="a" * 7000, target_language="ta").status_code, 413)

    def test_unavailable_is_503(self):
        with mock.patch.object(lts, "translate", side_effect=lts.TranslationUnavailable("no model")):
            r = self.post(text="Hello", target_language="ta")
        self.assertEqual(r.status_code, 503)

    def test_integrity_rejected_422(self):
        with mock.patch.object(lts, "translate", side_effect=lts.TranslationIntegrityError("x")):
            self.assertEqual(self.post(text="Hello 2 mm", target_language="ta").status_code, 422)

    def test_inference_error_is_generic_500(self):
        with mock.patch.object(lts, "translate", side_effect=lts.TranslationError("boom")):
            r = self.post(text="Hello", target_language="ta")
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("boom", r.text)

    def test_status(self):
        r = self.client.get("/api/translate/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("available", r.json())

    def test_never_calls_openrouter(self):
        from services import openrouter_client as orc
        with mock.patch.object(orc.httpx, "post", side_effect=AssertionError("OpenRouter called")):
            with mock.patch.object(lts, "translate", return_value="x"):
                self.assertEqual(self.post(text="Hello", target_language="ta").status_code, 200)


if __name__ == "__main__":
    unittest.main()
