"""Central dictionary of clinical terms that must stay in English when Knee.AI text is
translated into Hindi/Tamil/Malayalam/Telugu.

local_translation_service masks every match with an opaque placeholder before the text
reaches IndicTrans2 and restores the exact original text (spelling and capitalisation
included) afterwards, so the model never sees, transliterates or "translates" these terms.

Matching rules (see build_pattern):
- whole words/phrases only (no substring hits: "AP" never matches inside "appearance");
- phrases are tried longest-first, so "proximal fibula" is one unit, not two;
- words match case-insensitively and allow plural variants, hyphen/space variation;
- abbreviations (AP, PA, CT, MRI, ...) match UPPER-CASE only, so ordinary words such as
  "ap", "pa" or "ct" in running text are not touched.

To add a term: append it to the right list below. TERMINOLOGY_VERSION changes automatically
whenever the dictionary changes; the frontend uses it to discard older cached translations.
"""

import hashlib
import re
from typing import Dict, Iterable, List

# Bump manually when the *meaning* of protection changes without a dictionary edit.
TERMINOLOGY_REVISION = 2

# ------------------------------------------------------------------ dictionary
# Case-insensitive words/phrases. Singular only; plural/hyphen variants are generated.
ANATOMY = [
    "femur", "tibia", "fibula", "patella", "meniscus", "menisci", "femoral", "tibial", "fibular",
    "patellar", "meniscal", "condyle", "epicondyle", "plateau", "synovium", "joint capsule",
    "articular cartilage", "cartilage", "subchondral bone", "subchondral surface", "subchondral cyst",
    "quadriceps tendon", "patellar tendon", "tendon", "ligament", "collateral ligament",
    "cruciate ligament", "joint line", "joint space", "tibiofemoral joint", "patellofemoral joint",
    "tibiofemoral", "patellofemoral", "compartment", "tibial condyle", "femoral condyle",
    "tibial plateau",
]
# Expanded with "medial"/"lateral" in front (medial meniscus, lateral compartment, ...).
SIDED = [
    "meniscus", "compartment", "joint space", "joint line", "femoral condyle", "tibial condyle",
    "tibial plateau", "collateral ligament", "epicondyle", "joint space narrowing", "joint space width",
]
# Expanded with "proximal"/"distal" in front (proximal fibula, distal femur, ...).
REGIONAL = ["femur", "tibia", "fibula", "patella", "femoral", "tibial", "fibular", "tibiofemoral"]

RADIOLOGY = [
    "anteroposterior", "antero-posterior", "posteroanterior", "lateral view", "lateral projection",
    "skyline view", "sunrise view", "x-ray", "xray", "radiograph", "radiographic", "weight-bearing",
    "non-weight-bearing", "projection", "image acquisition", "image quality", "cortical margin",
    "cortical outline", "trabecular pattern", "soft tissue", "radiopacity", "radiolucency",
    "pixel spacing", "slice thickness",
]

CLINICAL = [
    "osteoarthritis", "arthritis", "osteoarthrosis", "kellgren-lawrence", "joint-space narrowing",
    "joint space narrowing", "osteophyte", "marginal osteophyte", "subchondral sclerosis", "sclerosis",
    "osteopenia", "osteoporosis", "effusion", "degenerative changes", "degenerative change", "varus",
    "valgus", "genu varum", "genu valgum", "alignment", "chondral", "cartilage degeneration",
    "articular surface", "meniscal extrusion", "meniscal tear", "synovitis", "fracture", "bone marrow",
    "edema", "oedema", "arthroplasty", "osteotomy", "implant",
]

MEASUREMENT = [
    "medial-lateral", "anterior-posterior", "distal", "proximal", "anterior", "posterior", "medial",
    "lateral", "mm", "cm",
    # adverbs ("narrowing medially, sclerosis laterally"): the model otherwise translates them
    "medially", "laterally", "proximally", "distally", "anteriorly", "posteriorly",
]

# Upper-case abbreviations: matched exactly as written (never lower-case).
ABBREVIATIONS = [
    "AP", "PA", "MRI", "CT", "DICOM", "PACS", "OA", "KL", "HU", "ROI", "BMI", "ACL", "PCL", "MCL",
    "LCL", "TKA", "UKA",
]

# Hand-written patterns (scoped flags: (?i:...) is case-insensitive, rest exact).
# "Standing AP", "AP standing", "AP view", "AP radiograph", "PA image", ...
EXTRA_PATTERNS = [
    r"(?:(?i:standing|weight-bearing|non-weight-bearing)[\s\-]+)?(?:AP|PA)"
    r"(?:[\s\-]+(?i:standing|weight-bearing|view|projection|radiograph|image|film|x-ray)s?)?",
]

_IRREGULAR_PLURALS = {
    "meniscus": "menisci", "fibula": "fibulae", "patella": "patellae", "tibia": "tibiae",
    "osteophyte": "osteophytes", "edema": "edemas",
}


# --------------------------------------------------------------------- builder
def _flex(phrase: str) -> str:
    """Spaces and hyphens in a phrase match any run of spaces/hyphens."""
    words = [w for w in re.split(r"[\s\-]+", phrase.strip()) if w]
    return r"[\s\-]+".join(re.escape(w) for w in words)


def _expand(prefixes: Iterable[str], bases: Iterable[str]) -> List[str]:
    return ["{} {}".format(p, b) for p in prefixes for b in bases]


def all_terms() -> Dict[str, List[str]]:
    """Words/phrases by category (documentation, tests and the version hash use this)."""
    return {
        "anatomy": ANATOMY + _expand(["medial", "lateral"], SIDED) + _expand(["proximal", "distal"], REGIONAL),
        "radiology": RADIOLOGY,
        "clinical": CLINICAL,
        "measurement": MEASUREMENT,
        "abbreviations": ABBREVIATIONS,
    }


def _word_alternatives() -> List[str]:
    phrases = set()
    for cat in ("anatomy", "radiology", "clinical", "measurement"):
        phrases.update(t.lower() for t in all_terms()[cat])
    # Longest phrase first so the regex engine prefers "medial joint space narrowing"
    # over "medial" at the same start position.
    ordered = sorted(phrases, key=lambda t: (-len(t), t))
    out = []
    for t in ordered:
        piece = _flex(t)
        words = re.split(r"[\s\-]+", t)
        irregular = _IRREGULAR_PLURALS.get(words[-1])
        if irregular and irregular != words[-1] + "s":
            head = r"[\s\-]+".join(re.escape(w) for w in words[:-1])
            piece = "(?:{}|{})".format(piece, (head + r"[\s\-]+" if head else "") + re.escape(irregular))
        out.append("(?i:{})(?i:e?s)?".format(piece) if not t.endswith(("s", "mm", "cm")) else "(?i:{})".format(piece))
    return out


def build_pattern() -> str:
    alternatives = list(EXTRA_PATTERNS)
    alternatives += _word_alternatives()
    alternatives += [re.escape(a) for a in sorted(ABBREVIATIONS, key=lambda a: (-len(a), a))]
    return r"(?<![A-Za-z0-9])(?:{})(?![A-Za-z0-9])".format("|".join(alternatives))


TERMINOLOGY_PATTERN = build_pattern()
TERMINOLOGY_RE = re.compile(TERMINOLOGY_PATTERN)

# Changes whenever the dictionary or revision changes -> clients drop older cached translations.
TERMINOLOGY_VERSION = "t{}-{}".format(
    TERMINOLOGY_REVISION, hashlib.sha1(TERMINOLOGY_PATTERN.encode("utf-8")).hexdigest()[:8]
)


def find_terms(text: str) -> List[str]:
    """Exact source text of every protected clinical term in `text` (for tests/diagnostics)."""
    return [m.group(0) for m in TERMINOLOGY_RE.finditer(text)]
