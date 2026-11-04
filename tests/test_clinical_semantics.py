"""Formatting and clinical-meaning regression tests for the local translation pipeline.

Part 1 (always): placeholder-spacing repair, colon repair, "No"->negation input rewrite, and the
rule-based semantic validator against (a) observed good model outputs and (b) deliberately wrong
translations in Tamil, Hindi, Malayalam and Telugu. No model, no network, no OpenRouter.
Part 2 (RealModelTests): the same checks through the real IndicTrans2 model (skipped when the
local model is not installed). Synthetic sentences only.

    .venv/Scripts/python -m pytest tests/test_clinical_semantics.py -q
"""

import json
import os
import re
import sys
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from services import local_translation_service as lts
from services.clinical_semantics import semantic_problems

LANGS = ("ta", "hi", "ml", "te")
FIXTURES = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "clinical_semantic_outputs.json"),
                          encoding="utf-8"))["outputs"]


# ----------------------------------------------------------------------------- formatting
class SpacingTests(unittest.TestCase):
    def test_restore_spacing_only_where_source_had_a_space(self):
        masked = "0009, 0019 and 0029"
        self.assertEqual(lts.restore_spacing(masked, "0009,0019 और 0029"), "0009, 0019 और 0029")
        # "1,000" has no space in the source: never insert one
        self.assertEqual(lts.restore_spacing("0009,0019 units", "0009,0019 इकाइयाँ"), "0009,0019 इकाइयाँ")

    def test_semicolon_and_colon_spacing(self):
        self.assertEqual(lts.restore_spacing("Findings: 0009; 0019", "x: 0009;0019"), "x: 0009; 0019")
        self.assertEqual(lts.restore_spacing("Findings: 0009", "x:0009"), "x: 0009")

    def test_adjacent_protected_terms_after_comma_all_languages(self):
        # A translator that, like the real model, drops the space after the comma.
        def sloppy(segs, tag, retry=False):
            return [s.replace(", ", ",") for s in segs]
        for lang in LANGS:
            with self.subTest(lang=lang):
                out = lts.translate_text("Patella, Femur and Tibia are intact.", lang, sloppy)
                self.assertEqual(out, "Patella, Femur and Tibia are intact.")
                self.assertNotIn(",F", out)

    def test_numbers_decimals_and_thousands_not_corrupted(self):
        def sloppy(segs, tag, retry=False):
            return [s.replace(", ", ",") for s in segs]
        for src in ("Gap 2.4 mm, 3.1 mm and 1,000 units.", "KL grade 3, age 61, 12 degrees.",
                    "Values: 0.5, 10.25 and 1,000,000."):
            with self.subTest(src=src):
                out = lts.translate_text(src, "hi", sloppy)
                for token in re.findall(r"\d[\d,.]*\d|\d", src):
                    self.assertIn(token, out)
                self.assertNotIn("1, 000", out)
                self.assertNotIn("2. 4", out)

    def test_bullets_and_sentence_boundaries_preserved(self):
        src = "Femur, Tibia and Patella are intact.\n\n- Fibula; ACL; PCL are seen.\n- Left knee: no effusion."
        out = lts.translate_text(src, "ta", lambda segs, tag, retry=False: [s.replace(", ", ",") for s in segs])
        lines = out.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("- ") and lines[3].startswith("- "))
        self.assertIn("Femur, Tibia", lines[0])
        self.assertIn("Fibula; ACL; PCL", lines[2])

    def test_visarga_colon_repaired_but_only_as_often_as_the_source_has_colons(self):
        self.assertEqual(lts.fix_colons("Left knee: no effusion.", "இடது முழங்கால்ஃ effusion இல்லை."),
                         "இடது முழங்கால்: effusion இல்லை.")
        self.assertEqual(lts.fix_colons("Left knee: x", "बाएँ घुटनेः effusion"), "बाएँ घुटने: effusion")
        self.assertEqual(lts.fix_colons("No colon here", "निष्कर्षः"), "निष्कर्षः")  # source has none: untouched
        self.assertEqual(lts.fix_colons("a: b", "ഇടത് കാൽമുട്ട്ഃ x"), "ഇടത് കാൽമുട്ട്: x")
        self.assertEqual(lts.fix_colons("a: b", "ఎడమ మోకాలిః x"), "ఎడమ మోకాలి: x")


class NegationInputRewriteTests(unittest.TestCase):
    def test_no_becomes_not_any(self):
        self.assertEqual(lts.prepare_source("No fracture is seen."), "Not any fracture is seen.")
        self.assertEqual(lts.prepare_source("The knee shows no effusion and no swelling."),
                         "The knee shows not any effusion and not any swelling.")

    def test_numbering_and_other_words_untouched(self):
        for s in ("No. 3 of 5", "Nodule seen", "Know the limits", "Study NO 12", "no 5 mm"):
            with self.subTest(s=s):
                self.assertEqual(lts.prepare_source(s).replace("not any", "no"), s.replace("not any", "no"))

    def test_english_source_is_never_changed_by_the_rewrite(self):
        seen = []

        def spy(segs, tag, retry=False):
            seen.extend(segs)
            return segs
        src = "No fracture is seen."
        lts.translate_text(src, "ta", spy)
        self.assertEqual(src, "No fracture is seen.")
        self.assertTrue(any("Not any" in s for s in seen))


# ------------------------------------------------------------------------- semantic validator
class AcceptsGoodTranslationsTests(unittest.TestCase):
    def test_every_observed_good_output_validates(self):
        n = 0
        for lang, items in FIXTURES.items():
            for src, out in items.items():
                with self.subTest(lang=lang, src=src):
                    self.assertEqual(semantic_problems(src, out, lang), [])
                    n += 1
        self.assertGreater(n, 120)

    def test_all_required_scenarios_are_covered_by_fixtures_in_every_language(self):
        scenarios = [
            "There is no fracture.",                                              # absence of fracture
            "Possible osteophytes are seen at the tibial margin.",               # possible osteophytes
            "Narrowing is seen in the left knee.", "Narrowing is seen in the right knee.",   # left vs right
            "Narrowing is seen in the medial compartment.", "Narrowing is seen in the lateral compartment.",
            "Sclerosis at the proximal tibia.", "Sclerosis at the distal femur.",           # proximal vs distal
            "The lateral compartment is wider than the medial compartment.",                # compartments
            "Patella, Femur and Tibia are intact.",                                         # punctuation
        ]
        for lang in LANGS:
            for s in scenarios:
                self.assertIn(s, FIXTURES[lang], "{} missing for {}".format(s, lang))


WRONG = {  # (english, {lang: deliberately wrong translation}, expected problem prefix)
    "negation lost (finding turned into a positive)": ("No fracture is seen.", {
        "ta": "fracture காணப்படுகிறது.", "hi": "fracture दिखाई देता है।",
        "ml": "fracture കാണപ്പെടുന്നു.", "te": "fracture కనిపిస్తుంది."}, "negation-lost"),
    "'No' read as 'number' (the real model failure)": ("The knee shows no effusion.", {
        "ta": "முழங்கால் எண் effusion ஐக் காட்டுகிறது.", "hi": "घुटने में संख्या effusion दिखाई देती है।",
        "ml": "കാൽമുട്ട് നമ്പർ effusion കാണിക്കുന്നു.", "te": "మోకాలి సంఖ్య effusion చూపిస్తుంది."}, "negation-"),
    "negation introduced": ("A fracture is seen.", {
        "ta": "fracture காணப்படவில்லை.", "hi": "fracture नहीं देखा गया है।",
        "ml": "fracture കാണാനില്ല.", "te": "fracture కనిపించలేదు."}, "negation-introduced"),
    "uncertainty lost (possible -> confirmed)": ("Possible osteophytes are seen at the tibial margin.", {
        "ta": "tibial விளிம்பில் osteophytes காணப்படுகின்றன.", "hi": "tibial के अंतर पर osteophytes देखे गए।",
        "ml": "tibial മാർജിനിൽ osteophytes കാണപ്പെടുന്നു.", "te": "tibial మార్జిన్ వద్ద osteophytes కనిపిస్తున్నాయి."},
        "uncertainty-lost"),
    "left turned into right": ("Narrowing is seen in the left knee.", {
        "ta": "வலது முழங்காலில் சுருக்கம் காணப்படுகிறது.", "hi": "दाहिने घुटने में संकीर्णता देखी जाती है।",
        "ml": "വലത് കാൽമുട്ടിൽ ഇടുങ്ങിയ അവസ്ഥ കാണപ്പെടുന്നു.", "te": "కుడి మోకాలిలో ఇరుకైనది కనిపిస్తుంది."},
        "laterality-mismatch"),
    "laterality dropped": ("Narrowing is seen in the left knee.", {
        "ta": "முழங்காலில் சுருக்கம் காணப்படுகிறது.", "hi": "घुटने में संकीर्णता देखी जाती है।",
        "ml": "കാൽമുട്ടിൽ ഇടുങ്ങിയ അവസ്ഥ കാണപ്പെടുന്നു.", "te": "మోకాలిలో ఇరుకైనది కనిపిస్తుంది."},
        "laterality-mismatch"),
    "comparison roles swapped (which compartment is narrower)": (
        "The medial compartment is narrower than the lateral compartment.", {
            "ta": "lateral compartment என்பது medial compartment ஐ விட குறுகியதாகும்.",
            "hi": "lateral compartment medial compartment की तुलना में संकीर्ण है।",
            "ml": "medial compartment നേക്കാൾ ഇടുങ്ങിയതാണ് lateral compartment.",
            "te": "lateral compartment అనేది medial compartment కంటే ఇరుకైనది."}, "comparison-"),
    "narrower turned into wider": ("The medial compartment is narrower than the lateral compartment.", {
        "ta": "medial compartment என்பது lateral compartment ஐ விட அகலமானது.",
        "hi": "medial compartment lateral compartment की तुलना में चौड़ा है।",
        "ml": "lateral compartment നേക്കാൾ വീതിയുള്ളതാണ് medial compartment.",
        "te": "medial compartment అనేది lateral compartment కంటే వెడల్పుగా ఉంటుంది."}, "comparison-"),
    "comparison marker dropped": ("Joint space width is greater than 3 mm.", {
        "ta": "Joint space அகலம் 3 mm ஆக உள்ளது.", "hi": "Joint space की चौड़ाई 3 mm है।",
        "ml": "Joint space വീതി 3 mm ആണ്.", "te": "Joint space వెడల్పు 3 mm."}, "comparison-marker-lost"),
    "mild turned into severe": ("Mild joint space narrowing.", {
        "ta": "கடுமையான joint space narrowing.", "hi": "गंभीर joint space narrowing।",
        "ml": "ഗുരുതരമായ joint space narrowing.", "te": "తీవ్రమైన joint space narrowing."}, "severity-"),
    "severity lost": ("Severe joint space narrowing.", {
        "ta": "joint space narrowing.", "hi": "joint space narrowing।",
        "ml": "joint space narrowing.", "te": "joint space narrowing."}, "severity-lost:severe"),
}


class RejectsWrongTranslationsTests(unittest.TestCase):
    def test_each_wrong_translation_is_flagged_in_every_language(self):
        for name, (src, outs, code) in WRONG.items():
            for lang in LANGS:
                with self.subTest(case=name, lang=lang):
                    problems = semantic_problems(src, outs[lang], lang)
                    self.assertTrue(problems, "undetected: " + name)
                    self.assertTrue(any(p.startswith(code) for p in problems), "{} -> {}".format(name, problems))

    def test_proximal_distal_and_medial_lateral_swaps_are_flagged(self):
        src = "The proximal fibula is intact but the distal fibula shows a fracture."
        for lang in LANGS:
            good = FIXTURES[lang][src]
            swapped = good.replace("proximal fibula", "\0").replace("distal fibula", "proximal fibula").replace("\0", "distal fibula")
            self.assertEqual(semantic_problems(src, good, lang), [])
            self.assertIn("anatomical-direction-order", semantic_problems(src, swapped, lang))
        src2 = "Narrowing is seen in the medial compartment."
        for lang in LANGS:
            wrong = FIXTURES[lang][src2].replace("medial compartment", "lateral compartment")
            self.assertTrue(semantic_problems(src2, wrong, lang))

    def test_left_right_order_swap_in_contrast_sentence_is_flagged(self):
        src = "The left knee is normal but the right knee shows osteophytes."
        for lang in LANGS:
            good = FIXTURES[lang][src]
            self.assertEqual(semantic_problems(src, good, lang), [])
        # swap the two laterality words in Hindi
        swapped = FIXTURES["hi"][src].replace("बायां", "\0").replace("दाहिना", "बायां").replace("\0", "दाहिना")
        self.assertTrue(semantic_problems(src, swapped, "hi"))

    def test_unverifiable_wording_is_rejected_not_accepted(self):
        # Observed real outputs whose severity wording is wrong/unknown must NOT validate.
        self.assertTrue(semantic_problems("Marked osteophyte formation is present.",
                                          "குறிக்கப்பட்ட osteophyte உருவாக்கம் உள்ளது.", "ta"))
        self.assertTrue(semantic_problems("Minimal sclerosis is seen.", "కనీసం sclerosis కనిపిస్తుంది.", "te"))
        self.assertTrue(semantic_problems("Mild joint space narrowing.", "മിതമായ joint space narrowing.", "ml"))


class PipelineSafetyTests(unittest.TestCase):
    def test_semantically_wrong_translation_is_rejected_after_one_retry(self):
        calls = []

        def reverses(segs, tag, retry=False):
            calls.append(retry)
            return ["0009 காணப்படுகிறது." for _ in segs]  # "fracture is seen" (0009 = masked "fracture")
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.translate_text("No fracture is seen.", "ta", reverses, semantic_check=True)
        self.assertEqual(calls, [False, True])  # first attempt + one stricter retry, then give up

    def test_retry_can_recover_a_bad_first_attempt(self):
        def flaky(segs, tag, retry=False):
            return ["0009 இல்லை." if retry else "0009 காணப்படுகிறது." for _ in segs]
        self.assertEqual(lts.translate_text("No fracture is seen.", "ta", flaky, semantic_check=True), "fracture இல்லை.")

    def test_check_is_off_by_default_for_mechanics_tests_but_on_in_public_translate(self):
        out = lts.translate_text("No fracture is seen.", "ta", lambda s, t, retry=False: list(s))
        self.assertIn("Not any fracture", out)  # identity translator, no semantic check, no exception
        import inspect
        self.assertIn("semantic_check=True", inspect.getsource(lts.translate))

    def test_router_maps_rejection_to_422_so_the_ui_keeps_english(self):
        from unittest import mock
        from fastapi.testclient import TestClient
        from main import app
        from routers.analysis import get_current_user
        app.dependency_overrides[get_current_user] = lambda: "u"
        try:
            with mock.patch.object(lts, "translate", side_effect=lts.TranslationIntegrityError("x")):
                r = TestClient(app).post("/api/translate", json={"text": "No fracture is seen.", "target_language": "ta"})
            self.assertEqual(r.status_code, 422)
            self.assertNotIn("translated_text", r.json())
        finally:
            app.dependency_overrides.clear()


# ------------------------------------------------------------------------------- real model
def _model_ready():
    return os.path.isfile(os.path.join(lts.MODEL_DIR, "config.json")) and lts.is_available()["available"]


@unittest.skipUnless(_model_ready(), "local IndicTrans2 model not installed")
class RealModelTests(unittest.TestCase):
    """Real inference. A sentence may be rejected (safe fallback to English) but must never come back
    with reversed or lost meaning, and the formatting must be intact."""

    CASES = [
        ("There is no fracture.", {"must_neg": True}),
        ("No fracture is seen.", {"must_neg": True}),
        ("The knee shows no effusion and no swelling.", {"must_neg": True}),
        ("Possible osteophytes are seen at the tibial margin.", {"must_unc": True}),
        ("The cartilage appears to be thinned.", {"must_unc": True}),
        ("Narrowing is seen in the left knee.", {"left": True}),
        ("Narrowing is seen in the right knee.", {"right": True}),
        ("The left knee is normal but the right knee shows osteophytes.", {"left": True, "right": True}),
        ("Narrowing is seen in the medial compartment.", {"term": "medial compartment", "not_term": "lateral"}),
        ("Narrowing is seen in the lateral compartment.", {"term": "lateral compartment", "not_term": "medial"}),
        ("Sclerosis at the proximal tibia.", {"term": "proximal tibia", "not_term": "distal"}),
        ("Sclerosis at the distal femur.", {"term": "distal femur", "not_term": "proximal"}),
        ("The proximal fibula is intact but the distal fibula shows a fracture.", {"order": ["proximal fibula", "distal fibula"]}),
        ("The medial compartment is narrower than the lateral compartment.", {"compare": True}),
        ("The lateral compartment is wider than the medial compartment.", {"compare": True}),
        ("Joint space width is greater than 3 mm.", {"compare": True}),
        ("Joint space width is less than 2 mm.", {"compare": True}),
        ("Patella, Femur and Tibia are intact.", {"spacing": "Patella, Femur"}),
        ("Findings: Femur; Tibia; Patella.", {"spacing": "Femur; Tibia; Patella"}),
        ("Left knee: no effusion. Right knee: mild effusion.", {"colon": True}),
    ]

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        for lang in LANGS:
            for src, _ in cls.CASES:
                try:
                    cls.results[(lang, src)] = lts.translate(src, lang)
                except lts.TranslationIntegrityError:
                    cls.results[(lang, src)] = None  # safe fallback: UI would keep English

    def test_accepted_translations_keep_meaning_and_format(self):
        for lang in LANGS:
            lex = __import__("services.clinical_semantics", fromlist=["LEX"]).LEX[lang]
            for src, exp in self.CASES:
                out = self.results[(lang, src)]
                if out is None:
                    continue
                with self.subTest(lang=lang, src=src):
                    self.assertFalse(re.search(r"\d{3}9", out), "placeholder leaked")
                    if exp.get("must_neg"):
                        self.assertTrue(any(w in out for w in lex["neg"] + lex.get("neg_weak", [])))
                        self.assertFalse(any(w in out for w in lex["number"]), "'No' read as 'number'")
                    if exp.get("must_unc"):
                        self.assertTrue(any(w in out for w in lex["unc"]))
                    if exp.get("left"):
                        self.assertTrue(any(w in out for w in lex["left"]))
                    if exp.get("right"):
                        self.assertTrue(any(w in out for w in lex["right"]))
                    if exp.get("left") and not exp.get("right"):
                        self.assertFalse(any(w in out for w in lex["right"]))
                    if exp.get("right") and not exp.get("left"):
                        self.assertFalse(any(w in out for w in lex["left"]))
                    if "term" in exp:
                        self.assertIn(exp["term"], out)
                        self.assertNotIn(exp["not_term"], out.lower())
                    if "order" in exp:
                        a, b = exp["order"]
                        self.assertLess(out.index(a), out.index(b))
                    if "spacing" in exp:
                        self.assertIn(exp["spacing"], out)
                    if exp.get("colon"):
                        self.assertNotRegex(out, "[ःஃഃః]\\s")
                        self.assertIn(":", out)
                    if exp.get("compare"):
                        self.assertEqual(semantic_problems(src, out, lang), [])

    def test_validator_is_not_rejecting_everything(self):
        accepted = sum(v is not None for v in self.results.values())
        total = len(self.results)
        self.assertGreaterEqual(accepted / total, 0.85, "{} of {} accepted".format(accepted, total))

    def test_known_unreliable_wordings_fall_back_to_english(self):
        for lang in ("ta", "hi", "ml", "te"):
            with self.assertRaises(lts.TranslationIntegrityError):
                lts.translate("Marked osteophyte formation is present.", lang)


if __name__ == "__main__":
    unittest.main()
