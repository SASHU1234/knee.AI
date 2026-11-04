"""Medical-terminology protection tests.

Part 1 (always runs): masking/restoration, matching rules, integrity checks - no model.
Part 2 (RealModelTests): real IndicTrans2 in hi/ta/ml/te; skipped automatically when the
local model is not installed. Synthetic text only. No OpenRouter, no network.

    .venv/Scripts/python -m pytest tests/test_medical_terminology.py -q
"""

import os
import re
import sys
import unittest
from unittest import mock

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from services import local_translation_service as lts
from services import medical_terminology as mt

LANGS = ("ta", "hi", "ml", "te")

MANDATORY = [
    "AP", "AP view", "Standing AP", "Fibula", "Proximal fibula", "Femur", "Tibia", "Patella",
    "Medial meniscus", "Osteoarthritis", "KL grade 3", "MRI", "X-ray", "Subchondral sclerosis",
    "Osteophytes", "Varus", "Valgus",
]


def identity_translator(segments, tag, retry=False):
    return list(segments)


class MandatoryTermTests(unittest.TestCase):
    def test_each_term_is_one_protected_unit_with_exact_text(self):
        for term in MANDATORY:
            with self.subTest(term=term):
                prot, orig = lts.protect("See {} here.".format(term))
                self.assertEqual(orig, [term])  # one unit, original capitalisation
                self.assertNotIn(term.split()[0], prot.replace("See", ""))
                self.assertEqual(lts.restore(prot, orig), "See {} here.".format(term))

    def test_each_term_survives_the_pipeline_in_all_languages(self):
        # A translator that returns the masked sentence unchanged must give the source back.
        for lang in LANGS:
            for term in MANDATORY:
                with self.subTest(lang=lang, term=term):
                    src = "The {} is visible.".format(term)
                    self.assertEqual(lts.translate_text(src, lang, identity_translator), src)


class MatchingRuleTests(unittest.TestCase):
    def test_ap_is_protected_as_a_whole_abbreviation(self):
        self.assertEqual(mt.find_terms("The AP shows it."), ["AP"])

    def test_ap_not_matched_inside_other_words(self):
        for word in ("appearance", "Apple", "capacity", "lap", "CAPS", "apparent", "Chapter"):
            with self.subTest(word=word):
                self.assertEqual(mt.find_terms("The " + word + " was noted."), [])

    def test_lowercase_ambiguous_abbreviations_are_not_protected(self):
        self.assertEqual(mt.find_terms("ap pa ct oa kl"), [])

    def test_repeated_occurrences_restored_correctly(self):
        src = "Fibula here, fibula there, and the Fibula again; near the proximal fibula."
        prot, orig = lts.protect(src)
        self.assertEqual(orig, ["Fibula", "fibula", "Fibula", "proximal fibula"])
        self.assertEqual(len(set(re.findall(r"\d{3}9", prot))), 4)  # unique placeholders
        self.assertEqual(lts.restore(prot, orig), src)

    def test_overlapping_phrases_longest_wins(self):
        self.assertEqual(mt.find_terms("Medial joint space narrowing"), ["Medial joint space narrowing"])
        self.assertEqual(mt.find_terms("lateral menisci and medial meniscus"), ["lateral menisci", "medial meniscus"])
        self.assertEqual(mt.find_terms("Standing AP view"), ["Standing AP view"])
        self.assertEqual(mt.find_terms("the proximal fibula"), ["proximal fibula"])

    def test_multiword_is_a_single_placeholder(self):
        prot, orig = lts.protect("Subchondral sclerosis near the joint space narrowing.")
        self.assertEqual(len(orig), 2)
        self.assertEqual(len(re.findall(r"\d{3}9", prot)), 2)

    def test_plural_hyphen_and_case_variants(self):
        self.assertEqual(mt.find_terms("OSTEOPHYTES and osteophyte"), ["OSTEOPHYTES", "osteophyte"])
        self.assertEqual(mt.find_terms("Joint-space narrowing, joint space narrowing"),
                         ["Joint-space narrowing", "joint space narrowing"])
        self.assertEqual(mt.find_terms("Weight-bearing and non-weight-bearing"),
                         ["Weight-bearing", "non-weight-bearing"])
        self.assertEqual(mt.find_terms("fibulae, menisci"), ["fibulae", "menisci"])

    def test_ordinary_words_not_protected(self):
        self.assertEqual(mt.find_terms("The weather was pleasant, we walked to the market and had tea."), [])

    def test_required_categories_covered(self):
        text = ("Femur Tibia Fibula Patella Meniscus Menisci Tibial plateau Femoral condyle Articular cartilage "
                "Subchondral bone Joint capsule Synovium ACL PCL MCL LCL Quadriceps tendon Patellar tendon Ligament "
                "Cartilage AP PA Anteroposterior Lateral view X-ray Radiograph Radiographic MRI CT DICOM PACS "
                "Weight-bearing Projection Image acquisition Image quality Cortical margin Cortical outline "
                "Trabecular pattern Soft tissue Radiopacity Radiolucency Osteoarthritis OA Kellgren-Lawrence "
                "Osteophyte Sclerosis Osteopenia Effusion Degenerative changes Varus Valgus Alignment Chondral "
                "Cartilage degeneration Articular surface Meniscal extrusion Meniscal tear Synovitis Fracture "
                "Bone marrow Edema HU ROI Pixel spacing Slice thickness Medial-lateral Anterior-posterior Distal Proximal")
        leftover = text
        for t in sorted(mt.find_terms(text), key=len, reverse=True):
            leftover = leftover.replace(t, " ", 1)
        self.assertEqual(leftover.split(), [], "unprotected terms: " + " ".join(leftover.split()))


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.src = "The AP radiograph shows narrowing near the proximal fibula."
        self.prot, self.orig = lts.protect(self.src)

    def test_missing_placeholder_rejected(self):
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.restore(self.prot.replace("0019", ""), self.orig)

    def test_altered_placeholder_rejected(self):
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.restore(self.prot.replace("0009", "0089"), self.orig)

    def test_duplicated_placeholder_rejected(self):
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.restore(self.prot + " 0009", self.orig)

    def test_rejected_translation_surfaces_as_error_not_placeholders(self):
        bad = lambda segs, tag, retry=False: ["no placeholders at all" for _ in segs]
        with self.assertRaises(lts.TranslationIntegrityError):
            lts.translate_text(self.src, "ta", bad)


class ExistingProtectionTests(unittest.TestCase):
    def test_numbers_units_dates_ids_still_protected(self):
        src = "Gap 2.4 mm, KL grade 3 on 2024-03-05, angle 12 degrees, study a1b2c3d4e5f6, file knee_01.png."
        prot, orig = lts.protect(src)
        self.assertEqual(orig, ["2.4 mm", "KL grade 3", "2024-03-05", "12 degrees", "a1b2c3d4e5f6", "knee_01.png"])
        self.assertEqual(lts.restore(prot, orig), src)

    def test_english_source_unchanged(self):
        src = "The AP radiograph shows the Fibula."
        copy = str(src)
        lts.translate_text(src, "ta", identity_translator)
        self.assertEqual(src, copy)
        self.assertEqual(lts.translate(src, "en"), src)

    def test_no_openrouter_request(self):
        from services import openrouter_client as orc
        with mock.patch.object(orc.httpx, "post", side_effect=AssertionError("OpenRouter called")):
            lts.translate_text("The AP view of the Fibula.", "hi", identity_translator)


class VersionTests(unittest.TestCase):
    def test_version_present_and_stable(self):
        self.assertRegex(mt.TERMINOLOGY_VERSION, r"^t\d+-[0-9a-f]{8}$")
        self.assertEqual(lts.TERMINOLOGY_VERSION, mt.TERMINOLOGY_VERSION)

    def test_version_changes_when_dictionary_changes(self):
        import hashlib
        other = hashlib.sha1((mt.TERMINOLOGY_PATTERN + "|newterm").encode()).hexdigest()[:8]
        self.assertNotIn(other, mt.TERMINOLOGY_VERSION)


def _model_ready():
    return os.path.isfile(os.path.join(lts.MODEL_DIR, "config.json")) and lts.is_available()["available"]


@unittest.skipUnless(_model_ready(), "local IndicTrans2 model not installed")
class RealModelTests(unittest.TestCase):
    """Real inference: protected terms must come back verbatim in every language."""

    SENTENCES = {
        "ap_fibula": ("The AP radiograph shows narrowing near the proximal fibula.", ["AP radiograph", "proximal fibula"]),
        "standing": ("Standing AP view shows the Patella, Femur and Tibia clearly.", ["Standing AP view", "Patella", "Femur", "Tibia"]),
        "oa": ("Medial meniscus changes, Subchondral sclerosis and marginal osteophytes with Varus alignment.",
               ["Medial meniscus", "Subchondral sclerosis", "marginal osteophytes", "Varus", "alignment"]),
        "kl": ("Findings are consistent with Osteoarthritis, KL grade 3, on X-ray and MRI.",
               ["Osteoarthritis", "KL grade 3", "X-ray", "MRI"]),
        "nonmed": ("The weather was pleasant this morning, so we walked to the market.", []),
    }
    NATIVE = {"hi": (0x0900, 0x097F), "ta": (0x0B80, 0x0BFF), "ml": (0x0D00, 0x0D7F), "te": (0x0C00, 0x0C7F)}

    def test_terms_verbatim_and_rest_translated(self):
        for lang in LANGS:
            lo, hi = self.NATIVE[lang]
            for name, (src, terms) in self.SENTENCES.items():
                with self.subTest(lang=lang, sample=name):
                    out = lts.translate(src, lang)
                    for t in terms:
                        self.assertIn(t, out, "term altered/translated: " + t)
                    self.assertFalse(re.search(r"\d{3}9", out), "placeholder leaked: " + out)
                    native = sum(lo <= ord(c) <= hi for c in out)
                    self.assertGreater(native, 8, "surrounding text was not translated: " + out)

    def test_ap_and_fibula_not_transliterated(self):
        bad = {"ta": ["ஏபி", "ஃபைபுலா"], "hi": ["एपी", "फाइबुला"], "ml": ["എപി", "ഫിബുല"], "te": ["ఏపీ", "ఫైబులా", "ఫిబులా"]}
        for lang in LANGS:
            out = lts.translate("The AP radiograph shows narrowing near the proximal fibula.", lang)
            for b in bad[lang]:
                self.assertNotIn(b, out)


if __name__ == "__main__":
    unittest.main()
