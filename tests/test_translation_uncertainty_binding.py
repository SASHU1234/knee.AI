"""Final translation-safety regression tests.

1. Uncertainty and approximation must survive (about / approximately / possible / may indicate /
   "no DEFINITE effusion"): a translation may never become more certain than the English.
2. Finding-to-location relationships must not be reversed (medially/laterally, left/right with a
   negation, proximal/distal fibula, medial/lateral compartment comparisons).
3. The cache version fingerprints the whole translation pipeline.
4. RealModelTests: all four languages through the real local IndicTrans2 model, synthetic text only.

No OpenRouter, no external service. A software test is not a clinical validation.

    .venv/Scripts/python -m pytest tests/test_translation_uncertainty_binding.py -q
"""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from services import clinical_semantics as cs
from services import local_translation_service as lts
from services import medical_terminology as mt
from services.clinical_semantics import LEX, semantic_problems

LANGS = ("ta", "hi", "ml", "te")
FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "clinical_semantic_outputs.json"),
                    encoding="utf-8"))["outputs"]


def codes(src, out, lang):
    return semantic_problems(src, out, lang)


# --------------------------------------------------------------- 1. uncertainty / approximation
class ApproximationAndUncertaintyTests(unittest.TestCase):
    CASES = ["Approximately 2.7 mm.", "About 5 degrees.", "Possible medial narrowing.", "No definite effusion.",
             "Findings may indicate early osteoarthritis.", "The joint space is about 3 mm.",
             "The gap measures approximately 2.4 mm."]

    def test_observed_good_translations_are_accepted_in_every_language(self):
        for lang in LANGS:
            for s in self.CASES:
                with self.subTest(lang=lang, s=s):
                    self.assertIn(s, FX[lang])
                    self.assertEqual(codes(s, FX[lang][s], lang), [])

    def test_approximation_dropped_is_rejected(self):
        # the real earlier failure: "about 2.4 mm" came back as "at least 2.4 mm" / bare "2.4 mm"
        wrong = {
            "Approximately 2.7 mm.": {"ta": "2.7 mm.", "hi": "2.7 mm।", "ml": "കുറഞ്ഞത് 2.7 mm.", "te": "కనీసం 2.7 mm."},
            "About 5 degrees.": {"ta": "5 degrees.", "hi": "5 degrees।", "ml": "5 degrees.", "te": "5 degrees."},
            "The joint space is about 3 mm.": {"ta": "joint space 3 mm ஆகும்.", "hi": "joint space 3 mm है।",
                                              "ml": "joint space 3 mm ആണ്.", "te": "joint space 3 mm."},
        }
        for src, outs in wrong.items():
            for lang in LANGS:
                with self.subTest(src=src, lang=lang):
                    self.assertIn("approximation-lost", codes(src, outs[lang], lang))

    def test_about_without_a_number_is_not_treated_as_approximation(self):
        for lang in LANGS:
            self.assertNotIn("approximation-lost", codes("Ask your clinician about this.", "x", lang))

    def test_possible_becoming_certain_is_rejected(self):
        wrong = {"ta": "medial சுருக்கம்.", "hi": "medial संकीर्णता।", "ml": "medial ഇടുങ്ങൽ.", "te": "medial సంకుచితం."}
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertIn("uncertainty-lost", codes("Possible medial narrowing.", wrong[lang], lang))

    def test_may_indicate_becoming_certain_is_rejected(self):
        wrong = {"ta": "கண்டுபிடிப்புகள் osteoarthritis இன் முற்பகுதியைக் குறிக்கின்றன.",
                 "hi": "निष्कर्ष osteoarthritis की शुरुआत का संकेत देते हैं।",
                 "ml": "കണ്ടെത്തലുകൾ osteoarthritis ന്റെ തുടക്കത്തെ സൂചിപ്പിക്കുന്നു.",
                 "te": "ఫలితాలు osteoarthritis ప్రారంభాన్ని సూచిస్తాయి."}
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertIn("uncertainty-lost", codes("Findings may indicate early osteoarthritis.", wrong[lang], lang))

    def test_no_definite_effusion_must_not_become_plain_no_effusion(self):
        wrong = {"ta": "effusion இல்லை.", "hi": "कोई effusion नहीं।", "ml": "effusion ഇല്ല.", "te": "effusion లేదు."}
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertIn("qualifier-lost", codes("No definite effusion.", wrong[lang], lang))

    def test_no_definite_effusion_must_not_turn_into_a_positive_finding(self):
        wrong = {"ta": "திட்டவட்டமான effusion உள்ளது.", "hi": "निश्चित effusion मौजूद है।",
                 "ml": "കൃത്യമായ effusion ഉണ്ട്.", "te": "ఖచ్చితమైన effusion ఉంది."}
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertIn("negation-lost", codes("No definite effusion.", wrong[lang], lang))

    def test_no_is_never_read_as_number_in_the_model_input(self):
        self.assertEqual(lts.prepare_source("No definite effusion."), "Not any definite effusion.")


# ----------------------------------------------------------- 2. finding <-> location relationships
class RelationshipTests(unittest.TestCase):
    def test_medially_laterally_binding(self):
        src = "Narrowing medially, sclerosis laterally."
        for lang in LANGS:
            good = FX[lang][src]
            self.assertEqual(codes(src, good, lang), [], good)
            # reversed locations
            rev = good.replace("medially", "\0").replace("laterally", "medially").replace("\0", "laterally")
            self.assertTrue(codes(src, rev, lang), "locations swapped but accepted: " + rev)
            # swapped findings: clause order reversed => sclerosis now sits with 'medially'
            first, second = [p.strip() for p in good.rstrip(".").rstrip("।").split(",", 1)]
            swapped = "{}, {}.".format(second, first)
            self.assertTrue(codes(src, swapped, lang), "findings swapped but accepted: " + swapped)

    def test_adverbs_stay_in_english(self):
        for lang in LANGS:
            out = FX[lang]["Narrowing medially, sclerosis laterally."]
            self.assertIn("medially", out)
            self.assertIn("laterally", out)

    def test_left_narrowing_right_no_narrowing(self):
        src = "Left knee shows narrowing; right knee shows no narrowing."
        for lang in LANGS:
            good = FX[lang][src]
            self.assertEqual(codes(src, good, lang), [], good)
            left_part, right_part = [p.strip() for p in good.split(";", 1)]
            # sides swapped (clauses reversed): the negation now belongs to the left knee
            self.assertTrue(codes(src, "{}; {}".format(right_part, left_part), lang))
            # negation lost entirely
            neg_words = LEX[lang]["neg"] + LEX[lang].get("neg_weak", [])
            stripped = right_part
            for w in neg_words:
                stripped = stripped.replace(w, "")
            self.assertTrue(codes(src, "{}; {}".format(left_part, stripped), lang))
            # left/right words exchanged
            lw, rw = LEX[lang]["left"][0], LEX[lang]["right"][0]
            exch = good.replace(lw, "\0").replace(rw, lw).replace("\0", rw)
            self.assertTrue(codes(src, exch, lang), "left/right exchanged but accepted")

    def test_proximal_versus_distal_fibula(self):
        for src in ("The proximal fibula shows narrowing and the distal fibula shows sclerosis.",
                    "The proximal fibula is intact, the distal fibula is fractured.",
                    "The proximal fibula is intact but the distal fibula shows a fracture."):
            for lang in LANGS:
                good = FX[lang][src]
                self.assertEqual(codes(src, good, lang), [], good)
                swapped = good.replace("proximal fibula", "\0").replace("distal fibula", "proximal fibula").replace("\0", "distal fibula")
                self.assertTrue(codes(src, swapped, lang), "proximal/distal swapped but accepted: " + swapped)

    def test_findings_bound_to_the_right_fibula_segment(self):
        src = "The proximal fibula shows sclerosis and the distal fibula shows narrowing."
        # same protected terms in a different order = finding moved to the other segment
        for lang in LANGS:
            good = "proximal fibula sclerosis distal fibula"  # neutral stand-in carrying the right order
            bad = "proximal fibula distal fibula sclerosis"
            self.assertEqual([p for p in codes(src, good, lang) if p.startswith("finding-location")], [])
            self.assertIn("finding-location-order-unconfirmed", codes(src, bad, lang))

    def test_medial_versus_lateral_compartment_comparisons(self):
        for src, other in (("The medial compartment is narrower than the lateral compartment.",
                            "The lateral compartment is narrower than the medial compartment."),
                           ("The lateral compartment is wider than the medial compartment.", None)):
            for lang in LANGS:
                good = FX[lang][src]
                self.assertEqual(codes(src, good, lang), [])
                swapped = good.replace("medial compartment", "\0").replace("lateral compartment", "medial compartment").replace("\0", "lateral compartment")
                self.assertTrue(codes(src, swapped, lang), "roles swapped but accepted")
                if other:
                    # the model output for the opposite sentence must NOT validate against this one
                    self.assertTrue(codes(src, FX[lang][other], lang))

    def test_unreliable_complex_comparison_is_rejected_not_guessed(self):
        # "more marked laterally than medially": the model's wording cannot be confirmed
        src = "Narrowing is more marked laterally than medially."
        raw = {"ta": "குறுகிய அளவு medially ஐ விட laterally ஆகும்.", "hi": "medially की तुलना में संकीर्णता laterally अधिक चिह्नित है।",
               "ml": "medially നെ അപേക്ഷിച്ച് laterally ആണ് ഇടുങ്ങിയ അളവ്.", "te": "medially కంటే ఇరుకైనది laterally గా గుర్తించబడింది."}
        for lang in LANGS:
            self.assertTrue(codes(src, raw[lang], lang))

    def test_single_location_plus_laterality_is_not_treated_as_a_contrast(self):
        # regression: "medial meniscus ... left knee" is one location + one side, not a medial/lateral
        # or left/right contrast, so the term-order rule must not reject its (correct) translation
        src = "Mean medial meniscus thickness of 3.1 mm is shown for the left knee, with KL grade 3 osteoarthritis (OA)."
        out = "बाएं घुटने के लिए 3.1 mm की औसत medial meniscus मोटाई KL grade 3 osteoarthritis (OA) के साथ दिखाई गई है।"
        self.assertFalse(cs._has_contrast(src))
        self.assertEqual(codes(src, out, "hi"), [])
        self.assertTrue(cs._has_contrast("The proximal fibula and the distal fibula."))
        self.assertTrue(cs._has_contrast("Left knee normal, right knee abnormal."))
        self.assertTrue(cs._has_contrast("Narrowing medially, sclerosis laterally."))

    def test_punctuation_separated_protected_terms(self):
        for src in ("Patella, Femur and Tibia are intact.", "Femur, Tibia and Fibula are intact."):
            for lang in LANGS:
                out = FX[lang][src]
                self.assertNotRegex(out, r"[A-Za-z],[A-Za-z]")
                self.assertEqual(codes(src, out, lang), [])


# ------------------------------------------------------------------------ 3. cache / pipeline version
class PipelineVersionTests(unittest.TestCase):
    def test_format(self):
        self.assertRegex(lts.PIPELINE_VERSION, r"^p\d+-[0-9a-f]{10}$")

    def _version_with(self, module, suffix):
        """Pipeline version if `module`'s source file had `suffix` appended."""
        tmp = tempfile.mkdtemp()
        try:
            copy = os.path.join(tmp, os.path.basename(module.__file__))
            shutil.copy(module.__file__, copy)
            with open(copy, "a", encoding="utf-8") as fh:
                fh.write(suffix)
            original = module.__file__
            module.__file__ = copy
            try:
                return lts._pipeline_version()
            finally:
                module.__file__ = original
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_version_unchanged_for_identical_sources(self):
        self.assertEqual(lts._pipeline_version(), lts.PIPELINE_VERSION)

    def test_each_part_of_the_pipeline_changes_the_version(self):
        base = lts.PIPELINE_VERSION
        for name, module in (("terminology dictionary", mt), ("semantic validation rules", cs),
                             ("negation preprocessing / formatting / service", lts)):
            with self.subTest(part=name):
                self.assertNotEqual(self._version_with(module, "\n# changed\n"), base)

    def test_model_revision_is_part_of_the_version(self):
        original = lts.MODEL_REVISION
        try:
            lts.MODEL_REVISION = "different-revision"
            self.assertNotEqual(lts._pipeline_version(), lts.PIPELINE_VERSION)
        finally:
            lts.MODEL_REVISION = original

    def test_router_reports_pipeline_version_on_status_and_translation(self):
        from unittest import mock
        from fastapi.testclient import TestClient
        from main import app
        from routers.analysis import get_current_user
        app.dependency_overrides[get_current_user] = lambda: "u"
        try:
            c = TestClient(app)
            self.assertEqual(c.get("/api/translate/status").json()["pipeline_version"], lts.PIPELINE_VERSION)
            r = c.post("/api/translate", json={"text": "Hello", "target_language": "en"}).json()
            self.assertEqual(r["pipeline_version"], lts.PIPELINE_VERSION)
            with mock.patch.object(lts, "translate", return_value="x"):
                r = c.post("/api/translate", json={"text": "Hello", "target_language": "ta"}).json()
            self.assertEqual(r["pipeline_version"], lts.PIPELINE_VERSION)
        finally:
            app.dependency_overrides.clear()

    def test_openrouter_never_called(self):
        from unittest import mock
        from services import openrouter_client as orc
        with mock.patch.object(orc.httpx, "post", side_effect=AssertionError("OpenRouter called")):
            lts.translate_text("About 5 degrees.", "ta", lambda s, t, retry=False: list(s))


# ------------------------------------------------------------------------------- 4. real model
def _model_ready():
    return os.path.isfile(os.path.join(lts.MODEL_DIR, "config.json")) and lts.is_available()["available"]


@unittest.skipUnless(_model_ready(), "local IndicTrans2 model not installed")
class RealModelTests(unittest.TestCase):
    """Real IndicTrans2 in hi/ta/ml/te. A sentence may be rejected (safe fallback to English) but an
    accepted translation must keep approximation, uncertainty, negation and the relationships."""

    CASES = [
        ("Approximately 2.7 mm.", {"approx": True, "keep": ["2.7 mm"]}),
        ("About 5 degrees.", {"approx": True, "keep": ["5 degrees"]}),
        ("Possible medial narrowing.", {"unc": True, "keep": ["medial"]}),
        ("No definite effusion.", {"neg": True, "qual": True, "keep": ["effusion"]}),
        ("Findings may indicate early osteoarthritis.", {"unc": True, "keep": ["osteoarthritis"]}),
        ("The joint space is about 3 mm.", {"approx": True, "keep": ["3 mm"]}),
        ("Narrowing medially, sclerosis laterally.", {"bind": [("sclerosis", "laterally", "medially")]}),
        ("Left knee shows narrowing; right knee shows no narrowing.", {"clauses": [
            {"left": True, "right": False, "neg": False}, {"left": False, "right": True, "neg": True}]}),
        ("The proximal fibula shows narrowing and the distal fibula shows sclerosis.", {
            "order": ["proximal fibula", "distal fibula", "sclerosis"]}),
        ("The proximal fibula is intact, the distal fibula is fractured.", {"order": ["proximal fibula", "distal fibula"]}),
        ("The medial compartment is narrower than the lateral compartment.", {"standard": "lateral compartment"}),
        ("The lateral compartment is narrower than the medial compartment.", {"standard": "medial compartment"}),
        ("The lateral compartment is wider than the medial compartment.", {"standard": "medial compartment"}),
        ("Patella, Femur and Tibia are intact.", {"keep": ["Patella, Femur"]}),
    ]

    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for lang in LANGS:
            for src, _ in cls.CASES:
                try:
                    cls.out[(lang, src)] = lts.translate(src, lang)
                except lts.TranslationIntegrityError:
                    cls.out[(lang, src)] = None  # UI keeps English

    def test_accepted_translations_keep_uncertainty_binding_and_values(self):
        for lang in LANGS:
            lex = LEX[lang]
            for src, exp in self.CASES:
                out = self.out[(lang, src)]
                if out is None:
                    continue
                with self.subTest(lang=lang, src=src):
                    self.assertFalse(re.search(r"\d{3}9", out), "placeholder leaked")
                    for k in exp.get("keep", []):
                        self.assertIn(k, out)
                    if exp.get("approx"):
                        self.assertTrue(any(w in out for w in lex["approx"]), "approximation lost: " + out)
                    if exp.get("unc"):
                        self.assertTrue(any(w in out for w in lex["unc"]), "became certain: " + out)
                    if exp.get("neg"):
                        self.assertTrue(any(w in out for w in lex["neg"] + lex.get("neg_weak", [])))
                    if exp.get("qual"):
                        self.assertTrue(any(w in out for w in lex["qual"]), "'definite' lost: " + out)
                    for term, loc, other in exp.get("bind", []):
                        clause = [c for c in re.split(r"[;,]", out) if term in c]
                        self.assertTrue(clause and loc in clause[0] and other not in clause[0], out)
                    if "clauses" in exp:
                        parts = [p for p in out.split(";")]
                        self.assertEqual(len(parts), 2, out)
                        for part, want in zip(parts, exp["clauses"]):
                            self.assertEqual(any(w in part for w in lex["left"]), want["left"], out)
                            self.assertEqual(any(w in part for w in lex["right"]), want["right"], out)
                            self.assertEqual(any(w in part for w in lex["neg"] + lex.get("neg_weak", [])), want["neg"], out)
                    if "order" in exp:
                        pos = [out.index(t) for t in exp["order"]]
                        self.assertEqual(pos, sorted(pos), out)
                    if "standard" in exp:
                        i = out.index(exp["standard"])
                        self.assertTrue(any(m in out[i:i + len(exp["standard"]) + 14] for m in lex["than"]), out)
                    self.assertEqual(semantic_problems(src, out, lang), [])

    def test_validator_is_not_rejecting_everything(self):
        accepted = sum(v is not None for v in self.out.values())
        self.assertGreaterEqual(accepted / len(self.out), 0.85, "{} of {}".format(accepted, len(self.out)))

    def test_every_language_translates_the_core_uncertainty_cases(self):
        for lang in LANGS:
            for src in ("Approximately 2.7 mm.", "About 5 degrees.", "Possible medial narrowing.", "No definite effusion."):
                self.assertIsNotNone(self.out[(lang, src)], "{} rejected in {}".format(src, lang))


if __name__ == "__main__":
    unittest.main()
