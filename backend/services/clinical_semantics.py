"""Rule-based check that a translated sentence kept the clinical meaning of the English one.

No second model or API is involved. For each English sentence we look for meaning-critical cues
(negation, uncertainty, left/right, comparisons, severity) and require the translation to carry
the matching cue in the target language - and not to carry a contradicting one. Anything that
cannot be confirmed makes the sentence fail, the caller then keeps the English text and nothing is
cached. This is deliberately conservative: a false rejection only costs a translation, a false
acceptance could mislead a clinician.

What it cannot verify (documented limitation): which finding a location word is attached to
("narrowing medially, sclerosis laterally"), the semantics of cue-free text, and any wording that
is not in the lexicons below (such a sentence is rejected, never silently accepted).
"""

import re
from typing import Dict, List, Optional, Tuple

from services.medical_terminology import TERMINOLOGY_RE

# ------------------------------------------------------------- English cues
_NEG = re.compile(
    r"\b(?:no|not|without|absent|absence|none|neither|nor|never|cannot|free of|lack(?:s|ing)?|"
    r"negative for|devoid|rule[sd]? out)\b|n't", re.I)
_NEG_BROAD = re.compile(r"\b(?:un[a-z]{3,}|non[-\s]?[a-z]+|unable|nil|clear of|resolved)\b", re.I)
_NUMBER_WORD_SRC = re.compile(r"\b(?:number|numbers|no\.|count)\b", re.I)
_UNC = re.compile(
    r"\b(?:possible|possibly|probable|probably|suspected|suspicious|suggest(?:s|ed|ive)?|may|might|"
    r"could|likely|appears?|seems?|questionable|equivocal|uncertain|perhaps|presumed|potential|"
    r"potentially|cannot be (?:excluded|ruled out))\b", re.I)
_LEFT = re.compile(r"\bleft\b", re.I)
_RIGHT = re.compile(r"\bright\b", re.I)
_THAN = re.compile(r"\bthan\b", re.I)
_LESS_CUE = re.compile(r"\b(?:narrower|thinner|smaller|less|fewer|lower|shorter|reduced)\b", re.I)
_MORE_CUE = re.compile(r"\b(?:wider|thicker|larger|greater|more|higher|longer|increased)\b", re.I)
_SEV = {
    "mild": re.compile(r"\b(?:mild(?:ly)?|slight(?:ly)?|minimal|minor|subtle|trace)\b", re.I),
    "moderate": re.compile(r"\bmoderate(?:ly)?\b", re.I),
    "severe": re.compile(r"\b(?:severe(?:ly)?|marked(?:ly)?|advanced|extensive|pronounced|profound)\b", re.I),
}
_ANTONYM = re.compile(r"\b(proximal|distal|medial|lateral|medially|laterally|proximally|distally)\b", re.I)
# Approximation must survive ("about 2.7 mm" must not become "2.7 mm"). "about" only counts before a number.
_APPROX = re.compile(r"\b(?:approximately|approx\.?|roughly|circa|nearly|almost)\b|\b(?:about|around)\s+(?=\d)|~\s*\d", re.I)
# "No DEFINITE effusion" is weaker than "No effusion": the qualifier must survive a negation.
_QUAL = re.compile(r"\b(?:definite|definitive|obvious|evident|clear|convincing|appreciable|gross|frank)\b", re.I)
# Clause delimiters in the English sentence: punctuation and contrast words.
_SRC_CLAUSE_SPLIT = re.compile(r"\s*(?:;|,|:|\bbut\b|\bwhile\b|\bwhereas\b)\s*", re.I)

# ------------------------------------------------- target-language lexicons
# Substring matches on the (restored) output. Lists include forms observed from the real model
# plus common alternatives. "strong" = unambiguous words (also used to detect contradictions).
LEX: Dict[str, Dict[str, object]] = {
    "ta": {
        "neg": ["இல்ல", "ில்லை", "அல்ல", "இன்றி", "இன்மை", "அற்ற", "முடியாது", "காட்டாது", "இல்லாது"],
        "number": ["எண் ", "எண்.", "எண்ணை"],
        "unc": ["சாத்தியம்", "சாத்தியமான", "ஒருவேளை", "சந்தேக", "இருக்கலாம்", "லாம்", "கூடும்", "தோன்று",
                "தெரிகிறது", "தெரியும்", "போல", "வாய்ப்பு", "அநேகமாக", "அனேகமாக", "முடியாது", "ஐயம்"],
        "left": ["இடது", "இடப்"], "right": ["வலது", "வலப்"],
        "than": ["விட"],
        "less": ["குறுக", "குறைவ", "குறைந்த", "சிறிய", "மெல்லிய", "சுருங்க", "குறுகிய", "இடுக்க"],
        "more": ["அகல", "அதிக", "பெரிய", "தடிமன", "கூடுதல்", "விரிவ", "நீளம", "உயர்"],
        "approx": ["சுமார்", "ஏறத்தாழ", "தோராய", "கிட்டத்தட்ட", "அண்ணளவ", "சுமாராக"],
        "qual": ["திட்டவட்ட", "உறுதியான", "வெளிப்படையான", "தெளிவான", "குறிப்பிடத்தக்க", "தெளிவாக", "நிச்சய"],
        "conj": ["ஆனால்", "அதேசமயம்", "அதே நேரத்தில்", "எனினும்"],
        "strip_width": ["அகலம்"], "strip_thick": ["தடிமன்"],
        "mild": (["லேசான", "இலேசான", "மென்மையான", "சிறிதளவு"], ["சிறிய", "சிறு", "குறைவான", "மெல்லிய"]),
        "moderate": (["மிதமான", "நடுத்தர", "மிதம்"], []),
        "severe": (["கடுமையான", "கடுமை", "தீவிர", "மோசமான", "கடும்"], ["கணிசமான", "குறிப்பிடத்தக்க"]),
    },
    "hi": {
        "neg": ["नहीं", "नही", "बिना", "अनुपस्थित", "रहित", "अभाव", "न कि"],
        "number": ["संख्या", "नंबर", "क्रमांक"],
        "unc": ["संभाव", "शायद", "संदिग्ध", "सकत", "प्रतीत", "लगता", "लगती", "लगते", "अनुमान", "संदेह",
                "संभव", "हो सकता"],
        "left": ["बाएँ", "बाएं", "बायाँ", "बायां", "बाईं", "बायें", "बाया", "बाई "],
        "right": ["दाएँ", "दाएं", "दायाँ", "दायां", "दाहिन", "दाईं", "दायें"],
        "than": ["की तुलना", "तुलना में", "अपेक्षा", "से "],
        "less": ["संकीर्ण", "कम", "तंग", "संकरा", "सँकरा", "पतला", "छोटा"],
        "more": ["चौड़", "अधिक", "बड़ा", "मोटा", "ज़्यादा", "ज्यादा", "विस्तृत", "बढ़"],
        "approx": ["लगभग", "करीब", "तकरीबन", "अनुमानित", "क़रीब", "सुमारे"],
        "qual": ["निश्चित", "स्पष्ट", "ठोस", "महत्वपूर्ण", "पुष्ट", "निर्णायक"],
        "conj": ["लेकिन", "परंतु", "जबकि", "किन्तु"],
        "strip_width": ["चौड़ाई"], "strip_thick": ["मोटाई"],
        "mild": (["हल्का", "हल्की", "हल्के", "मामूली", "सौम्य"], ["न्यूनतम", "थोड़ा", "थोड़ी"]),
        "moderate": (["मध्यम"], []),
        "severe": (["गंभीर", "तीव्र", "उग्र", "अत्यधिक"], ["गहरा", "महत्वपूर्ण"]),
    },
    "ml": {
        "neg": ["ഇല്ല", "ില്ല", "അല്ല", "അഭാവ", "ഇല്ലാതെ", "കഴിയില്ല"],
        "neg_weak": ["ാതെ", "ാത്ത", "ല്ല"],  # "-ാതെ" = without, but also "കേടുകൂടാതെ" (intact): never used to flag
        "number": ["നമ്പർ", "സംഖ്യ", "എണ്ണം"],
        "unc": ["സാധ്യത", "സാധ്യമായ", "ഒരുപക്ഷേ", "സംശയ", "തോന്നു", "ആകാം", "ആവാം", "ഇരിക്കാം", "കാണാം",
                "കഴിയില്ല", "സൂചിപ്പിക്കാം", "പ്രതിനിധീകരിക്കാം", "ചേക്കാം"],
        "left": ["ഇടത്", "ഇടതു"], "right": ["വലത്", "വലതു"],
        "than": ["നേക്കാൾ", "ക്കാൾ", "കാൾ"],
        "less": ["ഇടുങ്ങി", "കുറവ", "കുറഞ്ഞ", "ചെറിയ", "നേർത്ത", "ചുരുങ്ങ"],
        "more": ["വീതി", "കൂടുതൽ", "കൂടുതല", "കൂടിയ", "വലിയ", "കട്ടി", "വിശാല", "വർദ്ധ"],
        "approx": ["ഏകദേശം", "ഏതാണ്ട്", "ഉദ്ദേശം", "ഏതാണ്ടു"],
        "qual": ["വ്യക്തമായ", "ഉറപ്പായ", "നിർണായക", "കൃത്യമായ", "നിശ്ചിത", "പ്രകടമായ"],
        "conj": ["എന്നാൽ", "പക്ഷേ", "അതേസമയം", "ങ്കിലും", "എങ്കിലും"],
        "strip_width": ["വീതി"], "strip_thick": ["കനം"],
        "mild": (["സൌമ്യ", "സൗമ്യ", "നേരിയ", "ലഘു", "മൈൽഡ്"], ["ചെറിയ", "നേർത്ത", "കുറഞ്ഞ", "അല്പ"]),
        "moderate": (["മിതമായ", "ഇടത്തരം"], []),
        "severe": (["ഗുരുതര", "കഠിന", "തീവ്ര", "രൂക്ഷ", "ഗൗരവ"], ["ശക്ത"]),
    },
    "te": {
        "neg": ["లేదు", "లేవు", "లేని", "కాదు", "కావు", "లేకుండా", "లేకపోవడం", "కనిపించదు", "కనిపించలేదు",
                "చూపించదు", "లేరు", "లేము", "మినహాయించలేము", "లేదని"],
        "number": ["సంఖ్య", "నంబర్", "నెంబర్"],
        "unc": ["సాధ్య", "బహుశా", "అనుమాన", "సూచించవచ్చు", "వచ్చు", "ఉండవచ్చు", "అనిపిస్తు", "తెలుస్తో",
                "ఉన్నట్లు", "మినహాయించలేము"],
        "left": ["ఎడమ"], "right": ["కుడి"],
        "than": ["కంటే", "కన్నా", "కంటె"],
        "less": ["ఇరుక", "తక్కువ", "సన్న", "చిన్న", "సంకుచిత", "తగ్గ"],
        "more": ["వెడల్పు", "ఎక్కువ", "పెద్ద", "మందం", "విశాల", "పెరిగ"],
        "approx": ["సుమారు", "దాదాపు", "అంచనా", "సుమారుగా"],
        "qual": ["స్పష్టమైన", "ఖచ్చితమైన", "నిర్దిష్ట", "నిశ్చిత", "స్పష్ట", "ఖచ్చిత"],
        "conj": ["కానీ", "అయితే", "అయినప్పటికీ", "మరోవైపు"],
        "strip_width": ["వెడల్పు"], "strip_thick": ["మందం"],
        "mild": (["తేలికపాటి", "స్వల్ప"], ["తక్కువ", "చిన్న", "సన్నని"]),
        "moderate": (["మితమైన", "మధ్యస్థ", "మోస్తరు"], []),
        "severe": (["తీవ్ర", "గణనీయ", "గంభీర"], []),
    },
}


def _has(text: str, words: List[str]) -> bool:
    return any(w in text for w in words)


def _positions(text: str, words: List[str]) -> List[int]:
    return [m.start() for w in words for m in re.finditer(re.escape(w), text)]


def _first_term_after_than(src: str) -> Optional[str]:
    m = _THAN.search(src)
    if not m:
        return None
    tail = src[m.end():]
    cands = []
    t = TERMINOLOGY_RE.search(tail)
    if t:
        cands.append((t.start(), t.group(0)))
    n = re.search(r"\d+(?:\.\d+)?\s?(?:mm|cm|°|degrees?|%)?", tail)
    if n:
        cands.append((n.start(), n.group(0).strip()))
    return min(cands)[1] if cands else None


def _src_signatures(src: str) -> List[Tuple[bool, bool, Tuple[str, ...], bool]]:
    """(left, right, direction words, negated) for each English clause that has any of them."""
    sigs = []
    for clause in _SRC_CLAUSE_SPLIT.split(src):
        if not clause or not clause.strip():
            continue
        left, right = bool(_LEFT.search(clause)), bool(_RIGHT.search(clause))
        ants = tuple(sorted(m.group(1).lower() for m in _ANTONYM.finditer(clause)))
        neg = bool(_NEG.search(clause))
        terms = frozenset(m.group(0).lower() for m in TERMINOLOGY_RE.finditer(clause))
        if left or right or ants or neg:
            sigs.append((left, right, ants, neg, terms))
    return sigs


def _out_signatures(out: str, lex) -> List[Tuple[bool, bool, Tuple[str, ...], bool, bool]]:
    conj = "|".join(re.escape(w) for w in lex["conj"])
    splitter = re.compile(r"\s*(?:;|,|:|" + conj + r")\s*")
    sigs = []
    for clause in splitter.split(out):
        if not clause or not clause.strip():
            continue
        left, right = _has(clause, lex["left"]), _has(clause, lex["right"])
        ants = tuple(sorted(m.group(1).lower() for m in _ANTONYM.finditer(clause)))
        neg_strong = _has(clause, lex["neg"])
        neg_any = neg_strong or _has(clause, lex.get("neg_weak", []))
        terms = frozenset(m.group(0).lower() for m in TERMINOLOGY_RE.finditer(clause))
        if left or right or ants or neg_any:
            sigs.append((left, right, ants, neg_any, neg_strong, terms))
    return sigs


def _sig_matches(s, o) -> bool:
    """Same laterality, direction words, negation and protected finding terms in this clause."""
    return (s[0] == o[0] and s[1] == o[1] and s[2] == o[2] and (o[3] if s[3] else not o[4])
            and s[4] == o[5])


_CONTRAST_PAIRS = (("proximal", "distal"), ("medial", "lateral"), ("medially", "laterally"),
                   ("proximally", "distally"), ("left", "right"))


def _has_contrast(src: str) -> bool:
    """True when both members of an opposite pair occur (proximal+distal, left+right, ...)."""
    words = {m.group(1).lower() for m in _ANTONYM.finditer(src)}
    if _LEFT.search(src):
        words.add("left")
    if _RIGHT.search(src):
        words.add("right")
    return any(a in words and b in words for a, b in _CONTRAST_PAIRS)


def _term_sequence(text: str) -> List[str]:
    return [m.group(0).lower() for m in TERMINOLOGY_RE.finditer(text)]


def semantic_problems(src: str, out: str, lang: str) -> List[str]:
    """Return a list of short problem codes; an empty list means the translation was confirmed."""
    lex = LEX.get(lang)
    if lex is None:
        return ["unsupported-language"]
    problems: List[str] = []
    low_out = out
    comparison = bool(_THAN.search(src))

    # --- negation / presence of findings -----------------------------------------------------
    src_neg = bool(_NEG.search(src))
    out_neg = _has(low_out, lex["neg"])
    if src_neg and not (out_neg or _has(low_out, lex.get("neg_weak", []))):
        problems.append("negation-lost")
    if not src_neg and not _NEG_BROAD.search(src) and out_neg:
        problems.append("negation-introduced")
    if src_neg and _has(low_out, lex["number"]) and not _NUMBER_WORD_SRC.search(src):
        problems.append("negation-read-as-number")

    # --- uncertainty (a hedge must survive; certain text may be phrased either way) ---------------
    if _UNC.search(src) and not _has(low_out, lex["unc"]):
        problems.append("uncertainty-lost")

    # --- laterality -----------------------------------------------------------------------------
    sl, sr = bool(_LEFT.search(src)), bool(_RIGHT.search(src))
    ol, orr = _has(low_out, lex["left"]), _has(low_out, lex["right"])
    if sl != ol or sr != orr:
        problems.append("laterality-mismatch")
    elif sl and sr:
        src_seq = [("L" if m.group(0).lower() == "left" else "R") for m in re.finditer(r"\b(?:left|right)\b", src, re.I)]
        found = sorted([(p, "L") for p in _positions(low_out, lex["left"])] +
                       [(p, "R") for p in _positions(low_out, lex["right"])])
        collapse = lambda seq: [c for i, c in enumerate(seq) if i == 0 or c != seq[i - 1]]  # one word can match 2 lexicon stems
        if collapse([c for _, c in found]) != collapse(src_seq) and not comparison:
            problems.append("laterality-order")

    # --- anatomical direction words stay put relative to each other (proximal/distal/medial/lateral) -
    if not comparison:
        s_seq = [m.group(1).lower() for m in _ANTONYM.finditer(src)]
        o_seq = [m.group(1).lower() for m in _ANTONYM.finditer(out)]
        if s_seq != o_seq:
            problems.append("anatomical-direction-order")
    else:
        if sorted(m.group(1).lower() for m in _ANTONYM.finditer(src)) != \
           sorted(m.group(1).lower() for m in _ANTONYM.finditer(out)):
            problems.append("anatomical-direction-changed")

    # --- comparisons: "than" marker, polarity (narrower/wider...), which side is the standard -----------
    if comparison:
        markers = lex["than"]
        if not _has(low_out, markers):
            problems.append("comparison-marker-lost")
        else:
            body = low_out
            if re.search(r"\bwidth\b", src, re.I):
                for w in lex["strip_width"]:
                    body = body.replace(w, " ")
            if re.search(r"\bthickness\b", src, re.I):
                for w in lex["strip_thick"]:
                    body = body.replace(w, " ")
            less_src, more_src = bool(_LESS_CUE.search(src)), bool(_MORE_CUE.search(src))
            if less_src != more_src:
                has_less, has_more = _has(body, lex["less"]), _has(body, lex["more"])
                want, other = (has_less, has_more) if less_src else (has_more, has_less)
                if not want or other:
                    problems.append("comparison-direction-unconfirmed")
            std = _first_term_after_than(src)
            if std:
                ok = False
                for m in markers:
                    for mm in re.finditer(re.escape(m), low_out):
                        if std.lower() in low_out[max(0, mm.start() - len(std) - 14):mm.start()].lower():
                            ok = True
                if not ok:
                    problems.append("comparison-roles-unconfirmed")

    # --- approximation: "about 2.7 mm" must not become an exact "2.7 mm" ------------------------------
    if _APPROX.search(src) and not _has(low_out, lex["approx"]):
        problems.append("approximation-lost")

    # --- "no DEFINITE effusion" is weaker than "no effusion": the qualifier must survive -------------
    if _NEG.search(src) and _QUAL.search(src) and not _has(low_out, lex["qual"]):
        problems.append("qualifier-lost")

    # --- finding <-> location/negation binding across clauses ("narrowing medially, sclerosis laterally")
    if not comparison:
        s_sigs = _src_signatures(src)
        if len(s_sigs) >= 2:
            o_sigs = _out_signatures(out, lex)
            if len(o_sigs) == len(s_sigs):
                if not all(_sig_matches(s, o) for s, o in zip(s_sigs, o_sigs)):
                    problems.append("clause-binding-unconfirmed")
            elif any(s[3] for s in s_sigs):
                # clause boundaries lost AND a negation is attached to one clause: cannot tell which
                problems.append("clause-binding-unconfirmed")
            # (without negation the global left/right and proximal/distal/medial/lateral order checks above apply)
        elif _has_contrast(src):
            # one clause pairing several locations with several findings ("proximal fibula shows sclerosis
            # and distal fibula shows narrowing"): the protected terms must keep their order
            if _term_sequence(src) != _term_sequence(out):
                problems.append("finding-location-order-unconfirmed")

    # --- severity -----------------------------------------------------------------------------------
    for cls, rx in _SEV.items():
        strong, weak = lex[cls]
        present = bool(rx.search(src))
        if present and not _has(low_out, list(strong) + list(weak)):
            problems.append("severity-lost:" + cls)
        if not present and _has(low_out, list(strong)):
            problems.append("severity-introduced:" + cls)
    return problems
