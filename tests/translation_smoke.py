"""REAL local-model smoke test on synthetic text (no patient data, no network after weights are cached).

Checks per language: output script, protected values kept, line structure kept, clinical
terms kept in English (not force-translated), and that non-medical prose IS translated.

Prereq: pip install -r backend/requirements-translation.txt, python tools/download_translation_model.py
    PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/translation_smoke.py
"""

import os
import re
import sys
import time

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from services import local_translation_service as lts

# kind -> (text, clinical terms that must appear verbatim, min fraction of native-script letters)
SAMPLES = {
    "visual_observations": (
        "Medial joint space narrowing is seen in the left knee, with a minimum width of about 2.4 mm. "
        "Subchondral sclerosis and marginal osteophytes are also seen. "
        "Possible mild varus alignment. No obvious swelling is visible.\n"
        "- Image positioning of the AP view is acceptable.\n"
        "- Part of the lateral compartment is unclear.\n"
        "These are visual observations, not a diagnosis.",
        ["Medial joint space narrowing", "Subchondral sclerosis", "marginal osteophytes", "varus", "AP view",
         "lateral compartment", "2.4 mm"],
        0.45,
    ),
    "medical_chat": (
        "Mean medial meniscus thickness of 3.1 mm is shown for the left knee, with KL grade 3 osteoarthritis (OA). "
        "The X-ray and MRI both show the femur and tibia clearly. Ask your clinician what this means for you.",
        ["medial meniscus", "3.1 mm", "KL grade 3", "osteoarthritis", "OA", "X-ray", "MRI", "femur", "tibia"],
        0.45,
    ),
    "food_advice": (
        "For a 61 year old with KL grade 3 osteoarthritis, favour anti-inflammatory foods.\n\n"
        "- Oily fish such as salmon twice a week.\n"
        "- Leafy greens, berries and nuts.\n"
        "- Limit sugary drinks and fried food.\n\n"
        "Sample meal: oats with berries for breakfast, and lentil soup with vegetables for dinner. "
        "This is general guidance, not a substitute for your clinician or a registered dietitian.",
        ["KL grade 3", "osteoarthritis", "61"],
        0.85,
    ),
    "non_medical": (
        "The weather was pleasant this morning, so we walked to the market and bought fresh vegetables. "
        "My sister called in the afternoon to say that she would visit us next weekend.\n"
        "- Please bring two books.\n"
        "- We will have tea at 5 pm.",
        ["5", "two"],  # "two" is expected to be translated; only digits must survive
        0.85,
    ),
}
SCRIPT_RANGES = {"hi": (0x0900, 0x097F), "ta": (0x0B80, 0x0BFF), "ml": (0x0D00, 0x0D7F), "te": (0x0C00, 0x0C7F)}


def script_ratio(text, lang):
    lo, hi = SCRIPT_RANGES[lang]
    letters = [c for c in text if c.isalpha()]
    return sum(lo <= ord(c) <= hi for c in letters) / max(1, len(letters))


def rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return float("nan")


def main():
    ok = True
    fallbacks = 0
    total = 0
    t0 = time.time()
    engine = lts.get_engine()
    print("model load: %.1fs, device=%s, rss=%.0f MB" % (time.time() - t0, engine.device, rss_mb()))
    for kind, (src, terms, min_ratio) in SAMPLES.items():
        for lang in ("hi", "ta", "ml", "te"):
            t = time.time()
            total += 1
            try:
                out = lts.translate(src, lang)
            except lts.TranslationIntegrityError:
                # The meaning/placeholder checks could not confirm this translation: the UI would keep the
                # English text and cache nothing. That is the designed safe outcome, not a failure.
                fallbacks += 1
                print("SAFE-FALLBACK %-20s %s: rejected by the safety checks (English kept)" % (kind, lang))
                continue
            except Exception as e:
                print("FAIL %-20s %s: %s: %s" % (kind, lang, type(e).__name__, e))
                ok = False
                continue
            dt = time.time() - t
            ratio = script_ratio(out, lang)
            low = out.lower()
            missing = [x for x in terms if x != "two" and x.lower() not in low]
            same_lines = len(out.split("\n")) == len(src.split("\n"))
            good = ratio >= min_ratio and not missing and same_lines
            ok &= good
            print("%s %-20s %s %.1fs script=%.2f terms_missing=%s lines_kept=%s" % (
                "PASS" if good else "FAIL", kind, lang, dt, ratio, missing, same_lines))
            print("   ", out.replace("\n", "\n    ")[:700])
    accepted = total - fallbacks
    print("accepted %d of %d, safe fallbacks to English: %d" % (accepted, total, fallbacks))
    ok &= accepted / total >= 0.75  # the checks must not reject most translations
    print("rss=%.0f MB" % rss_mb())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
