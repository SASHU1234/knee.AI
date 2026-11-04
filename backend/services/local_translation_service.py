"""Local English -> Hindi/Tamil/Malayalam/Telugu translation (IndicTrans2 distilled 200M).

Isolation rules:
- torch / transformers / IndicTransToolkit are imported lazily inside the engine
  loader, never at module import, so the API (and Vercel) start without them.
- One model per process, created once under a lock; inference is serialised.
- Patient-related text is never logged.

Medical integrity: numbers with units, KL grades, dates, identifiers and clinical
terminology (services/medical_terminology.py) are swapped for opaque placeholders before inference and restored
afterwards. If any placeholder is missing, duplicated or altered the result is
rejected (TranslationIntegrityError) and the caller keeps showing English.
"""

import hashlib
import logging
import os
import re
import threading
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("knee.translation")

MODEL_ID = "ai4bharat/indictrans2-en-indic-dist-200M"
# Pinned: remote code is reviewed against exactly this revision.
MODEL_REVISION = "2cfd0a20057756d756bf3e53528f492afc52f91a"

# Weights are fetched once by tools/download_translation_model.py into this dir
# (override with TRANSLATION_MODEL_DIR). Falls back to the Hugging Face cache.
MODEL_DIR = os.environ.get("TRANSLATION_MODEL_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".models", "indictrans2-en-indic-dist-200M"
)

SUPPORTED_TARGETS = {"hi": "hin_Deva", "ta": "tam_Taml", "ml": "mal_Mlym", "te": "tel_Telu"}
SUPPORTED_CODES = {"en"} | set(SUPPORTED_TARGETS)
MAX_CHARS = 6000
# One sentence per model segment (0 = never group). Measured: grouping two sentences made the
# Tamil output drop "narrowing" and say "swelling", so short isolated sentences are safer.
MAX_CHUNK_CHARS = 0
BATCH_SIZE = 8


class TranslationUnavailable(Exception):
    """Local engine/model cannot be loaded (deps or weights missing)."""


class TranslationIntegrityError(Exception):
    """A protected token was lost/duplicated/altered; translation rejected."""


class TranslationError(Exception):
    """Inference failed for another reason."""


# ---------------------------------------------------------------- protection
# Two kinds of content are masked with opaque placeholders before inference:
#   1. values/identifiers (numbers+units, dates, KL grades, file names, ids) - patterns below;
#   2. clinical terminology - the central dictionary in services/medical_terminology.py,
#      so anatomy, radiology and diagnostic terms (AP, fibula, osteophytes, ...) stay English.
# Numeric patterns come first so "2.4 mm" and "KL grade 3" are single units.
from services.clinical_semantics import semantic_problems  # noqa: E402
from services.medical_terminology import TERMINOLOGY_PATTERN, TERMINOLOGY_VERSION  # noqa: E402

_VALUE_PATTERNS = [
    r"\b(?:KL|K-L)\s*(?:grade\s*)?[0-4]\b",                        # KL grade 3
    r"\b\d{4}-\d{2}-\d{2}\b",                                       # 2024-03-05
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",                                 # 03/05/2024
    r"\b\d+(?:\.\d+)?\s?(?:mm|cm|kg|kg/m2|m|%|°|degrees?)(?![A-Za-z])",  # 4.2 mm, 12 degrees
    r"\b\d+(?:\.\d+)?(?:\s?[-–]\s?\d+(?:\.\d+)?)?\b",              # bare numbers / ranges
    r"\b(?:PNG|JPEG)\b",
    r"\b[A-Za-z0-9_\-]+\.(?:png|jpe?g|bmp|tiff?|dcm|json)\b",       # file names
    r"\b[a-f0-9]{8,}\b",                                            # study / analysis ids
]
# Case rules live inside each piece: values are case-insensitive, terminology carries its
# own scoped flags (abbreviations such as AP/PA/CT match upper-case only).
_PROTECT_RE = re.compile(
    "|".join("(?i:{})".format(p) for p in _VALUE_PATTERNS) + "|" + TERMINOLOGY_PATTERN
)
# Digit-only, fixed width: measured to survive IndicTrans2 in all four target
# languages (letter-based tokens such as "XQ0Z" get transliterated into
# Devanagari by the Hindi model). Every digit run in the source is itself masked
# first, so any other 4-digit "...9" token in output is a model invention.
_PH_FMT = "{:03d}9"
_PH_RE = re.compile(r"(?<!\d)(\d{3})9(?!\d)")
_DEGENERATE_RE = re.compile(r"(.)\1{7,}")  # e.g. ".........." runaway repetition


def protect(text: str) -> Tuple[str, List[str]]:
    originals: List[str] = []

    def _sub(m):
        originals.append(m.group(0))
        return _PH_FMT.format(len(originals) - 1)

    return _PROTECT_RE.sub(_sub, text), originals


def restore(text: str, originals: List[str]) -> str:
    """Put originals back. Raises TranslationIntegrityError on any mismatch."""
    seen = [int(i) for i in _PH_RE.findall(text)]
    expected = list(range(len(originals)))
    if sorted(seen) != expected:
        raise TranslationIntegrityError("Protected value missing, duplicated or altered.")
    out = _PH_RE.sub(lambda m: originals[int(m.group(1))], text)
    return out


def restore_spacing(masked_src: str, out: str) -> str:
    """Re-insert the space IndicTrans2 sometimes drops between "," ";" ":" and a placeholder.

    The model reads "0019, 0029" as a number list and emits "0019,0029". We only add a space
    where the *English source* had punctuation + space in front of that same placeholder, so
    "1,000" (no space in the source) and decimals like "2.4" are never altered.
    """
    for idx in set(re.findall(r"[,;:]\s+(\d{3})9(?!\d)", masked_src)):
        out = re.sub(r"([,;:])(%s9)(?!\d)" % idx, r"\1 \2", out)
    return out


_VISARGA_RE = re.compile(r"[\u0903\u0B83\u0D03\u0C03](?=\s|$)")


def fix_colons(src: str, out: str) -> str:
    """IndicTrans2 renders ":" as a visarga ("முழங்கால்ஃ", "घुटनेः") - turn it back into ":",
    but never more often than the English segment contained colons."""
    budget = [src.count(":")]

    def _sub(_m):
        if budget[0] > 0:
            budget[0] -= 1
            return ":"
        return _m.group(0)

    return _VISARGA_RE.sub(_sub, out) if budget[0] else out


_NO_RE = re.compile(r"\b([Nn])o\b(?!\.|\s*\d|\s*[-\u2013]\s*\d)")


def prepare_source(chunk: str) -> str:
    """Model-input wording only (the English original is never changed).

    Measured: IndicTrans2 reads "No fracture is seen" / "shows no effusion" as the abbreviation
    "No." (= number) in all four languages and drops the negation ("number fracture is seen").
    "not any" is translated as a negation every time.
    """
    return _NO_RE.sub(lambda m: "Not any" if m.group(1) == "N" else "not any", chunk)


def is_degenerate(src: str, out: str) -> bool:
    return bool(_DEGENERATE_RE.search(out)) or len(out) > 6 * len(src) + 40 or not out.strip()


# ------------------------------------------------------------------ chunking
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")
_BULLET_RE = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)(.*)$")


def split_sentences(line: str) -> List[str]:
    return [s for s in _SENT_SPLIT.split(line.strip()) if s]


def chunk_line(line: str, limit: int = MAX_CHUNK_CHARS) -> List[str]:
    """Group sentences into chunks <= limit chars (a single long sentence is
    kept whole; the model handles it, chunking never splits inside one)."""
    chunks: List[str] = []
    cur = ""
    for s in split_sentences(line):
        if cur and len(cur) + 1 + len(s) > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    return chunks


Translator = Callable[..., List[str]]  # (english segments, tgt lang tag, retry=False) -> translated


def translate_text(text: str, target: str, translator: Translator, semantic_check: bool = False) -> str:
    """Translate multiline text preserving blank lines and bullet prefixes.

    Placeholder protection is applied per segment so integrity is verified
    segment by segment. With semantic_check, each translated sentence must also pass the
    rule-based clinical-meaning check (negation, uncertainty, laterality, comparisons,
    severity); a sentence that cannot be confirmed fails the whole translation.
    """
    tag = SUPPORTED_TARGETS[target]
    lines = text.split("\n")
    plan: List[Tuple[str, Optional[str], List[Tuple[int, List[str]]]]] = []
    jobs: List[str] = []  # protected english segments
    job_meta: List[List[str]] = []
    sources: List[str] = []  # original english sentence per job (for semantic validation)

    for line in lines:
        if not line.strip():
            plan.append(("", None, []))
            continue
        m = _BULLET_RE.match(line)
        prefix, body = (m.group(1), m.group(2)) if m else ("", line)
        slots = []
        for chunk in chunk_line(body):
            protected, originals = protect(prepare_source(chunk))
            sources.append(chunk)
            slots.append((len(jobs), originals))
            jobs.append(protected)
            job_meta.append(originals)
        plan.append((prefix, body, slots))

    outputs: List[str] = []
    for i in range(0, len(jobs), BATCH_SIZE):
        outputs.extend(translator(jobs[i:i + BATCH_SIZE], tag))
    if len(outputs) != len(jobs):
        raise TranslationError("Translator returned an unexpected number of segments.")

    def finalize(idx: int, originals: List[str]) -> str:
        """Validate one segment; on failure retry it alone with stricter decoding."""
        for attempt in range(2):
            out = outputs[idx].strip() if attempt == 0 else translator([jobs[idx]], tag, retry=True)[0].strip()
            if is_degenerate(jobs[idx], out):
                continue
            try:
                restored = fix_colons(sources[idx], restore(restore_spacing(jobs[idx], out), originals))
            except TranslationIntegrityError:
                continue
            if semantic_check and semantic_problems(sources[idx], restored, target):
                continue
            return restored
        raise TranslationIntegrityError("Segment could not be translated faithfully.")

    result_lines = []
    for prefix, body, slots in plan:
        if body is None:
            result_lines.append("")
            continue
        parts = [finalize(idx, originals) for idx, originals in slots]
        result_lines.append(prefix + " ".join(parts))
    return "\n".join(result_lines)


# ------------------------------------------------------------------ cache version
# Clients key cached translations on this. It fingerprints the WHOLE pipeline - terminology
# dictionary, "no" input rewrite, placeholder/format repair, semantic-validation lexicons and
# rules (all live in these three source files) plus the pinned model revision - so any change
# that could alter or re-judge a translation makes every older cached translation unusable.
PIPELINE_REVISION = 3


def _pipeline_version() -> str:
    from services import clinical_semantics, medical_terminology
    h = hashlib.sha1(MODEL_REVISION.encode("utf-8"))
    for path in (medical_terminology.__file__, clinical_semantics.__file__, __file__):
        try:
            with open(path, "rb") as fh:
                h.update(fh.read().replace(b"\r\n", b"\n"))  # same hash on Windows and Linux checkouts
        except OSError:
            h.update(TERMINOLOGY_VERSION.encode("utf-8"))
    return "p{}-{}".format(PIPELINE_REVISION, h.hexdigest()[:10])


PIPELINE_VERSION = _pipeline_version()


# -------------------------------------------------------------------- engine
class _Engine:
    """Holds the loaded model; created once per process."""

    def __init__(self):
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            from IndicTransToolkit.processor import IndicProcessor
        except Exception as e:  # ImportError or binary mismatch
            raise TranslationUnavailable(
                "Translation dependencies are not installed (see backend/requirements-translation.txt)."
            ) from e

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # Local pinned snapshot if present, else the pinned hub revision.
        if os.path.isfile(os.path.join(MODEL_DIR, "config.json")):
            source, kwargs = MODEL_DIR, {"trust_remote_code": True, "local_files_only": True}
        else:
            source, kwargs = MODEL_ID, {"trust_remote_code": True, "revision": MODEL_REVISION}
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(source, **kwargs)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                source, torch_dtype=torch.float32, **kwargs
            )
        except Exception as e:
            raise TranslationUnavailable(
                "Translation model is not available locally. Run tools/download_translation_model.py "
                "(accept the model terms on Hugging Face and run 'hf auth login' first), then restart the backend."
            ) from e
        self.model.to(self.device)
        self.model.eval()
        self.processor = IndicProcessor(inference=True)
        logger.info("Local translation model loaded on %s", self.device)

    def __call__(self, segments: List[str], tgt_tag: str, retry: bool = False) -> List[str]:
        torch = self.torch
        batch = self.processor.preprocess_batch(segments, src_lang="eng_Latn", tgt_lang=tgt_tag)
        inputs = self.tokenizer(
            batch, truncation=True, padding="longest", return_tensors="pt", return_attention_mask=True
        ).to(self.device)
        with torch.inference_mode():
            # Output length bounded by input length: stops runaway repetition early.
            budget = min(250, int(inputs["input_ids"].shape[1] * 3) + 20)
            extra = {"repetition_penalty": 1.3, "no_repeat_ngram_size": 4, "num_beams": 5} if retry else {"num_beams": 4}
            generated = self.model.generate(
                **inputs, use_cache=True, min_length=0, max_new_tokens=budget, num_return_sequences=1, **extra
            )
        decoded = self.tokenizer.batch_decode(
            generated.detach().cpu().tolist(), skip_special_tokens=True, clean_up_tokenization_spaces=True
        )
        return self.processor.postprocess_batch(decoded, lang=tgt_tag)


_engine: Optional[_Engine] = None
_init_lock = threading.Lock()
_infer_lock = threading.Lock()
_load_error: Optional[str] = None


def get_engine() -> _Engine:
    global _engine, _load_error
    if _engine is not None:
        return _engine
    with _init_lock:
        if _engine is None:
            try:
                _engine = _Engine()
                _load_error = None
            except TranslationUnavailable as e:
                _load_error = str(e)
                raise
    return _engine


def is_available() -> Dict[str, object]:
    """Cheap status; never loads the model. Disabled with TRANSLATION_ENABLED=0."""
    if os.environ.get("TRANSLATION_ENABLED", "1") == "0":
        return {"available": False, "loaded": False, "reason": "Local translation is disabled."}
    try:
        import importlib.util
        have = all(importlib.util.find_spec(m) for m in ("torch", "transformers", "IndicTransToolkit"))
    except Exception:
        have = False
    if not have:
        return {"available": False, "loaded": False,
                "reason": "Local translation dependencies are not installed on this server."}
    return {"available": True, "loaded": _engine is not None, "reason": _load_error}


def translate(text: str, target: str) -> str:
    """Public entry. Validates, short-circuits English, runs the local model."""
    if target not in SUPPORTED_CODES:
        raise ValueError("Unsupported target language.")
    if not text or not text.strip():
        raise ValueError("Nothing to translate.")
    if len(text) > MAX_CHARS:
        raise ValueError("Text exceeds the {} character limit.".format(MAX_CHARS))
    if target == "en":
        return text
    if os.environ.get("TRANSLATION_ENABLED", "1") == "0":
        raise TranslationUnavailable("Local translation is disabled.")

    engine = get_engine()

    def run(segments: List[str], tag: str, retry: bool = False) -> List[str]:
        with _infer_lock:
            return engine(segments, tag, retry)

    try:
        return translate_text(text, target, run, semantic_check=True)
    except (TranslationIntegrityError, TranslationUnavailable, ValueError):
        raise
    except Exception as e:
        logger.error("Translation inference failed: %s", type(e).__name__)
        raise TranslationError("Translation failed.") from e
