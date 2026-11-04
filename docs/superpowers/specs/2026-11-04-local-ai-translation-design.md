# Local AI-response translation: design and plan

Status: approved by the project owner on 2026-11-04 (design + extra conditions 1-8).

## Goal
Translate already-generated English AI text (AI Visual Scan, Food Advice, Clinician Note,
AI chat assistant messages) into Hindi/Tamil/Malayalam/Telugu with a local model when the
user changes the existing website language. English originals stay immutable. Zero extra
OpenRouter requests or tokens on language change.

## Decisions
- **AI generation language is always English.** `frontend/src/lib/api.js` sends
  `language: "English"` explicitly on `/chat`, `/advice`, `/vision`. Backend ignores it
  (`language_instruction` only acts on Hindi/Tamil/Malayalam/Telugu), so endpoint contracts
  and prompts are unchanged. UI language is independent of generation language.
- **Model:** `ai4bharat/indictrans2-en-indic-dist-200M` (MIT, one model for all four
  targets, ~200M params). Pinned to revision
  `2cfd0a20057756d756bf3e53528f492afc52f91a`. The repo is *gated (auto)*: the user must accept
  the terms on Hugging Face and authenticate once (`hf auth login`). Remote code
  (`trust_remote_code`) is enabled only after the pinned files are reviewed (see
  "Remote code review" below). IndicTrans3-beta is LLM-scale and not suitable for CPU.
- **Backend** (`backend/services/local_translation_service.py`, `backend/routers/translate.py`):
  - Lazy, lock-guarded singleton; CPU by default, CUDA if available; no import of torch/
    transformers at module import time, so app startup never depends on them.
  - `POST /api/translate` (auth via existing `get_current_user`), `GET /api/translate/status`.
  - 503 with a stable message when the engine is unavailable; 422/400 on bad language/size;
    502-style generic error on inference failure; no stack traces; no text logged.
  - English returns the input untouched with no model call.
  - Inference serialised by a lock (one model, no concurrent instances).
- **Medical integrity:** numbers+units, KL grades, dates, ages, L/R markers, identifiers and
  clinical abbreviations are replaced with opaque placeholders before translation and restored
  after. If any placeholder is missing, duplicated or altered the translation is rejected (error
  to client, nothing cached, English stays shown). Line/bullet structure preserved by
  translating line by line; sentences chunked to stay within model limits.
- **Dependencies:** `backend/requirements-translation.txt` only (torch, transformers,
  sentencepiece, etc.). `backend/requirements.txt` and Vercel config untouched.
- **Frontend:**
  - `lib/translationCache.js`: in-memory Map keyed `studyId|feature|sourceHash|lang`; failures
    never cached; in-flight de-duplication.
  - `lib/useTranslatedText.js`: reads `language` from the existing `LanguageContext`; returns
    `{ text, loading, error, translated }`; English returns the original synchronously; a
    request-token guard drops stale results on rapid switching.
  - Used by the Vision, Food Advice and Clinician Note cards in `AnalysisShell.jsx` and by
    assistant messages in `ChatWidget.jsx` (messages get stable ids). A small spinner and a
    "machine-translated" notice show beside translated content. Unavailable engine: show English
    plus a short note.
  - Vitest is a devDependency only; config in `frontend/vitest.config.js`, separate from
    `vite.config.js`, tests under `frontend/src/**/*.test.js`.
- **No** persistent storage of translations (memory only). No DB changes.

## Remote code review
Performed before enabling `trust_remote_code`; findings recorded in
`docs/translation-model-review.md`.

## Verification
1. pytest (mocked engine) for service + router; existing `tests/` suites still pass.
2. Vitest for hook/cache/stale-guard/English-restore/language switching.
3. Real-model smoke script (`tests/translation_smoke.py`) on synthetic text for hi/ta/ml/te,
   with timing and memory; quality sanity-checked (placeholders intact, script correct,
   round-trip sanity where possible).
4. Network check proving language switching sends no `/chat|/advice|/vision` request.

## Plan
1. Review pinned remote code (needs HF access).
2. Translation service + masking + chunking; benchmark real model.
3. Router + startup-safe registration + 503.
4. Frontend api.js, cache, hook, components.
5. Tests (pytest, vitest), regression run.
6. README + review doc + final report.
