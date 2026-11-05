# Knee.AI — AI-Assisted Knee Analysis Platform

A clinical decision-support platform combining a **real vision-language model reading the actual
uploaded image**, a live conversational AI assistant, and two structured assessment modules —
backed by Supabase auth with TOTP 2FA and a batch research mode:

**AI Visual Scan** sends the uploaded X-ray/MRI to a genuine pretrained vision-language model
(hosted on OpenRouter) that reports what it actually sees — joint space, alignment,
visible spurring/sclerosis, image quality — independent of anything else on the page. See
[AI features](#ai-features). Alongside it:

1. **Module 1 — Medial Meniscus Thickness & OA Analysis**: three-point thickness measurement, OA
   classification, KL grading, and population comparison charts.
2. **Module 2 — Femur/Tibia Measurements & Implant Sizing**: bone morphometry matched against a
   built-in catalogue of six implant systems, ranked by euclidean distance.

Every analysis also carries an **image-quality score and per-measurement uncertainty band**,
derived from the uploaded film itself (resolution, sharpness, contrast, whether the bone region
was actually located) — degraded films are flagged for clinical review rather than presented
with the same confidence as a clean one.

**What's real vs. simulated, plainly:** the AI Visual Scan and the chat/food-advice features are
live calls to real hosted models (OpenRouter) — that output is genuinely generated per
request, not canned. The *quantitative* numbers in Modules 1 and 2 — thickness in mm, OA class, KL
grade, bone dimensions — are deterministic simulation or drawn from pre-analyzed sidecars, not a
trained measurement model; no live model weights for that part ship with this repo. See
[Inference paths](#inference-paths) and [Simulation logic](#simulation-logic) for exactly how, and
[AI features](#ai-features) for what's real.

---

## Feature overview

- **AI Visual Scan** — a real pretrained vision-language model (via OpenRouter) looks at
  the actual uploaded image and reports its own visual observations, on demand, per analysis.
- **Two clinical modules** as separate pages (`/oa`, `/implant`), sharing one patient header,
  quality banner, and tab switcher for the same study.
- **Accounts via Supabase Auth** — email/password sign-in, doctor/patient roles, row-level
  security scoped per user.
- **TOTP two-factor authentication** — enable in Settings (QR + manual secret), enforced both by
  the login flow and by the backend itself (a password-only token is rejected once an account has
  a verified factor — not just a UI gate).
- **AI assistant (OpenRouter)** — a floating chat widget with context awareness of whatever
  study you're viewing, plus a one-shot "Get AI Food Diet" write-up per analysis. Models are
  configurable per feature (default `nvidia/nemotron-3.5-lightning:free`; any chat model on
  OpenRouter works through the same OpenAI-compatible endpoint).
- **Multi-language UI** — English (default), Hindi, Tamil, Malayalam, Telugu. AI text is always
  generated in English and translated locally on language change; see
  [Multi-language](#multi-language) and [Local AI translation](#local-ai-translation).
- **Research Mode** — batch-upload a cohort (or run the bundled samples) for descriptive
  statistics: thickness distributions, OA/sex/age-band comparisons, correlations, and an implant
  sizing summary. Studies that fail the quality check are excluded by default. See
  [Research Mode](#research-mode).
- **Image quality & uncertainty** — every analysis is scored on resolution, sharpness, contrast,
  and region detection; the score drives a "clinical review recommended" banner and ± tolerance
  bands shown next to each measurement.

---

## Quick start

```bash
./run.sh
```

That creates the Python virtualenv, installs both dependency sets on first run, and starts both
processes:

| Service   | URL                        |
|-----------|----------------------------|
| Frontend  | http://localhost:5173      |
| API       | http://127.0.0.1:8000      |
| API docs  | http://127.0.0.1:8000/docs |

`Ctrl+C` stops both. Override ports with `BACKEND_PORT=9000 FRONTEND_PORT=3000 ./run.sh`.

**Requirements:** Python 3.9+ and Node 18+, plus a Supabase project (see below) — the app fails
to start meaningfully without one, since auth is not optional.

### Manual start

```bash
# backend (uvicorn is launched from inside backend/ — main.py uses absolute imports
# that assume backend/ as the working directory, matching the Vercel deployment layout)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m uvicorn main:app --reload --port 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev
```

Vite proxies `/api` to `127.0.0.1:8000` in dev, so the UI needs no `VITE_API_URL` locally.

---

## Environment variables

**`backend/.env`** (gitignored — copy `backend/.env.example`):

```bash
SUPABASE_URL=
SUPABASE_ANON_KEY=

OPENROUTER_API_KEY=

OPENROUTER_CHAT_MODEL=nvidia/nemotron-3.5-lightning:free     # optional, this is the default
OPENROUTER_ADVICE_MODEL=nvidia/nemotron-3.5-lightning:free   # optional, this is the default
OPENROUTER_VISION_MODEL=nvidia/nemotron-3.5-super-vl:free    # optional, this is the default

OPENROUTER_BASE_URL=https://openrouter.ai/api/v1             # optional, this is the default
```

Without `SUPABASE_URL`/`SUPABASE_ANON_KEY`, every authenticated endpoint returns 401. Without
`OPENROUTER_API_KEY`, the chat widget, food-advice button, and AI Visual Scan all return 502 —
everything else works.

To get an OpenRouter key: create an account at [openrouter.ai](https://openrouter.ai), then
**Settings → Keys → Create Key**. Only the key is required; the three model variables above are
the defaults and can be swapped for any models OpenRouter hosts (pick a vision-capable model for
`OPENROUTER_VISION_MODEL`). The `:free` variants are rate-limited per day and per minute — a 429
from an AI feature means that limit was hit; wait and retry, or switch to a paid model. See
[AI privacy](#ai-privacy) before pointing this at anything but synthetic data.

**`frontend/.env`** (gitignored, local dev) and **`frontend/.env.production`** (tracked — see
below):

```bash
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=            # prod only; omit locally, Vite proxies /api instead
```

The Supabase anon key is safe to commit: it's a build-time value baked into the client bundle
either way (anyone can read it in the shipped JS), it grants no privileges on its own, and access
is gated by row-level security. That's why `frontend/.env.production` is tracked in git while
`backend/.env` and `frontend/.env` are not — the backend's key, and any future service-role key,
must never end up in a public bundle or history.

Your Supabase project needs email/password auth enabled and, if you want 2FA, TOTP MFA enabled
(Authentication → Providers). The `analyses` table needs RLS policies keyed on
`auth.uid() = user_id`; the backend authenticates each request as the calling user (not with a
shared service-role client) so those policies apply normally — see
[Authentication & security](#authentication--security).

---

## Deployment (Vercel)

One Vercel project with two **services** (root `vercel.json`):

- **`backend`** (`backend/`, FastAPI, entrypoint `main:app`) is public only under `/api/*` through a top-level
  rewrite. Its routes already start with `/api`, and Vercel passes the original path through, so no path
  rewriting is needed. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `OPENROUTER_API_KEY`, `OPENROUTER_CHAT_MODEL`,
  `OPENROUTER_ADVICE_MODEL`, `OPENROUTER_VISION_MODEL` and `PROVENANCE_SECRET` as project environment variables.
- **`frontend`** (`frontend/`, Vite) serves every other path. `frontend/.env.production` sets
  `VITE_API_URL=/api` (same origin, so no CORS) plus the public Supabase config; `frontend/vercel.json` keeps the
  single-page-app fallback.
- No service bindings: neither service calls the other server-side (the browser reaches the backend through the
  `/api` rewrite; the backend only calls OpenRouter and Supabase).
- Not available on Vercel: the local translation model (the API answers 503 and the UI keeps English) and durable
  reviews until the `study_reviews` migration is applied (the local-file fallback does not persist there).
- The old standalone `backend/vercel.json` is kept as `backend/vercel.legacy.json.disabled` for reference.

Because the backend service's root is `backend/` in production but the repo root locally, `backend/main.py`
uses absolute imports (`import store`, `from routers import ...`) throughout — that's also why
local dev launches uvicorn from *inside* `backend/` rather than from the repo root.

---

## Usage flow

1. **Sign in** — email/password. If the account has 2FA enabled, a TOTP code is required after
   the password step before the app becomes accessible at all (enforced by the backend too, not
   just the login screen).
2. **New Analysis** — click a pre-analyzed sample card, or drop any knee X-ray or MRI
   (JPEG/PNG/BMP/TIFF/DICOM-lite), fill in patient details, and **Run Analysis**.
3. **Meniscus & OA** (`/oa/:id`) and **Implant Sizing** (`/implant/:id`) — the two modules, each
   with its own page and a tab switcher between them for the same study. Both show the quality
   banner and ± uncertainty bands when relevant.
4. **AI Visual Scan** — a real vision-language model's own read of the uploaded image, on demand.
   **Get AI Food Diet** / the chat bubble — AI-generated dietary guidance for the current study,
   or a free-form conversation that's aware of whatever study you're viewing.
5. **Generate Report** — downloads a two-page clinical PDF.
6. **History** — every stored analysis, searchable and filterable by severity, with a doctor-only
   inline advice editor.
7. **Research** — batch-analyse an uploaded cohort or the bundled samples for descriptive
   statistics across the group.
8. **Settings** — account info, 2FA management, classification thresholds, overlay colour key,
   and the full implant catalogue.

A language switcher sits next to the API status badge (top right) — English, हिन्दी, தமிழ்,
മലയാളം, తెలుగు.

---

## Folder structure

```
knee-ai/
├── run.sh                          # single-command launcher
├── README.md
├── backend/
│   ├── main.py                     # FastAPI app, CORS, router wiring
│   ├── store.py                    # JSON-on-disk local storage helpers
│   ├── requirements.txt
│   ├── .env.example
│   ├── api/index.py                # Vercel serverless entrypoint
│   ├── vercel.json
│   ├── routers/
│   │   ├── analysis.py             # POST /api/analyze, history, catalogue, auth deps
│   │   ├── report.py                # image serving + PDF report
│   │   ├── advice.py                # AI food/diet advice (OpenRouter)
│   │   ├── chat.py                  # AI assistant chat (OpenRouter)
│   │   ├── vision.py                # AI Visual Scan — real vision model on the image (OpenRouter)
│   │   └── research.py              # batch cohort analysis + statistics
│   ├── services/
│   │   ├── image_processor.py      # OpenCV overlays, calliper lines, variants
│   │   ├── oa_classifier.py        # thickness simulation, OA class, KL grade
│   │   ├── implant_matcher.py      # bone morphometry + euclidean size matching
│   │   ├── analysis_builder.py     # assembles the record; run_measurements() is
│   │   │                           #   shared by the single-study and cohort paths
│   │   ├── quality.py              # image-quality scoring + uncertainty bands
│   │   ├── cohort.py                # descriptive statistics for Research Mode
│   │   ├── sample_registry.py      # sample lookup by MD5/filename, picker cards
│   │   ├── supabase_client.py      # per-request authenticated Supabase client, MFA/AAL check
│   │   ├── openrouter_client.py    # OpenRouter chat completions + language instruction
│   │   ├── report_builder.py       # ReportLab clinical PDF
│   │   └── seed.py                 # deterministic hash-seeded RNG
│   ├── data/
│   │   ├── implant_database.json   # 6 systems × 5 sizes + population reference
│   │   └── samples/                # 5 pre-analyzed films + JSON sidecars + index.json
│   └── storage/                    # generated PNGs, PDFs, analyses.json (gitignored)
├── tools/
│   └── make_samples.py             # regenerates the sample films + sidecars
├── tests/
│   └── test_e2e.py                 # end-to-end API suite — predates auth, see Tests
└── frontend/
    ├── .env.production             # tracked; public build-time config, see above
    └── src/
        ├── App.jsx                 # session/AAL gating, routes
        ├── lib/
        │   ├── api.js
        │   ├── supabase.js         # client init + build-config guard
        │   ├── i18n.js             # per-language dictionaries
        │   └── LanguageContext.jsx
        ├── components/             # Sidebar, Topbar, Viewer, Charts, ChatWidget,
        │                           #   AnalysisShell (shared module-page chrome), ui primitives
        └── pages/                  # Dashboard, NewAnalysis, OaAnalysis, ImplantSizing,
                                     #   History, Research, Settings, Auth, MfaChallenge
```

---

## API

All `/api/analyze*`, `/api/analyses*`, `/api/implants`, `/api/advice`, `/api/chat`, `/api/vision`,
and `/api/research/*` routes require `Authorization: Bearer <supabase access token>`, and reject a
password-only (aal1) token if the account has 2FA enabled. `/api/report*`, `/api/images/*`, and
`/api/samples*` are public.

| Method   | Path                        | Auth | Purpose                                          |
|----------|-----------------------------|:----:|---------------------------------------------------|
| `GET`    | `/api/health`               |      | Liveness probe                                    |
| `POST`   | `/api/analyze`              |  ✓   | Multipart upload + patient form → full analysis    |
| `POST`   | `/api/analyze/sample/{id}`  |  ✓   | Run a shipped sample through the model path        |
| `GET`    | `/api/analyses`             |  ✓   | Compact history rows                               |
| `GET`    | `/api/analyses/{id}`        |  ✓   | Full stored analysis                               |
| `DELETE` | `/api/analyses/{id}`        |  ✓   | Remove an analysis                                 |
| `GET`    | `/api/implants`             |  ✓   | Implant catalogue + population reference           |
| `GET`    | `/api/samples`              |      | Sample picker cards (age/sex/side, KL, OA)         |
| `GET`    | `/api/samples/{id}/image`   |      | Sample film PNG                                    |
| `GET`    | `/api/images/{filename}`    |      | Rendered original / overlay variant PNG            |
| `GET`    | `/api/report/{id}`          |      | Clinical PDF report (stored analysis)              |
| `POST`   | `/api/report`               |      | Clinical PDF report (from a record in the body)    |
| `POST`   | `/api/advice`               |  ✓   | AI food/diet advice for one analysis               |
| `POST`   | `/api/chat`                 |  ✓   | Multi-turn AI assistant, optionally record-aware   |
| `POST`   | `/api/vision`               |  ✓   | Real vision-model observations on the actual image |
| `POST`   | `/api/research/cohort`      |  ✓   | Batch-analyse uploaded studies → cohort statistics |
| `POST`   | `/api/research/cohort/samples` | ✓ | Cohort statistics over the bundled samples         |

`POST /api/analyze` fields: `file`, `name`, `age`, `sex` (`Male`/`Female`),
`imaging_type` (`X-ray`/`MRI`), `affected_side` (`Left`/`Right`).

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -F "file=@knee.png" -F "name=Jane Doe" -F "age=67" \
  -F "sex=Female" -F "imaging_type=X-ray" -F "affected_side=Left"
```

`POST /api/advice`, `POST /api/chat`, and `POST /api/vision` all accept an optional `language`
field — one of `Hindi`, `Tamil`, `Malayalam`, `Telugu` (whitelisted server-side; anything else is
ignored rather than interpolated into the prompt, since it isn't free text an end user should
control).

---

## Authentication & security

- **Auth** is Supabase Auth (email/password). The frontend talks to Supabase directly for
  sign-in/sign-up/session management; the backend independently verifies every request's bearer
  token via `supabase.auth.get_user()` rather than trusting the frontend.
- **Row-level security**: the backend never uses a shared, anon-key-only client for user data.
  `services/supabase_client.py` builds a fresh client per request, authenticated with the caller's
  own JWT, so `analyses` table reads/writes run *as that user* and RLS policies keyed on
  `auth.uid() = user_id` apply normally.
- **Two-factor authentication (TOTP)**: enable from Settings — Supabase issues a QR/secret, the
  frontend renders the QR itself via the `qrcode` package (not Supabase's own returned SVG, which
  proved unreliable to inline directly), and confirms with a 6-digit code.
  - **Frontend gate**: `App.jsx` checks `supabase.auth.mfa.getAuthenticatorAssuranceLevel()` on
    every session change and shows a TOTP challenge screen before rendering anything else if a
    verified factor exists and the session is still aal1.
  - **Backend enforcement**: `verify_token()` reads the account's factor list and the token's
    `aal` claim directly. If the account has a verified factor and the token is aal1, the request
    is rejected — this closes the gap where a stolen password alone could call the API directly,
    bypassing the frontend's login prompt entirely.

---

## AI features

Every AI feature in this app is a live call to a real hosted model via **OpenRouter**, an
OpenAI-compatible inference gateway, through `services/openrouter_client.py` — nothing here is
canned or templated. Model selection is centralized in that one service and driven entirely by
backend environment variables: `OPENROUTER_CHAT_MODEL` (chat), `OPENROUTER_ADVICE_MODEL` (food
advice) and `OPENROUTER_VISION_MODEL` (visual scan). To change a model, set the variable to any
model OpenRouter hosts and restart — no code change needed.

### Reasoning models and token budgets

The default NVIDIA Nemotron models are **reasoning** models: they emit a hidden chain of thought
that counts against `max_tokens` *before* any answer text is produced. Measured live against
OpenRouter, a food-advice request spends ~2,300–3,700 reasoning tokens before writing a ~2,400
character answer. A budget sized for a non-reasoning model therefore returns HTTP 200 with an
empty `content` field — the request "succeeds" and the user sees nothing.

The generation budgets live in `services/openrouter_client.py` (`CHAT_MAX_TOKENS`,
`ADVICE_MAX_TOKENS`, `VISION_MAX_TOKENS`), sized from those measurements with headroom. If you
swap in a different model, adjust them there — one place, no router changes. The client rejects a
response whose `finish_reason` is `length` even when partial text came back: half a sentence of
dietary guidance served as if complete is worse than an explicit error.

Observed live latencies on the free tier: chat ~7 s, vision ~14 s, food advice ~31–56 s. Passing
`reasoning: {"effort": ...}` to these endpoints does not reliably reduce that (an `effort: low`
request produced *more* reasoning tokens than the default), so it is not used.

**Deployment consequence:** the food-advice path can approach 60 s, which is the default serverless
function cap on Vercel's Hobby plan — a slower run there surfaces as a gateway timeout, not an
application error. Either run the advice path on a plan/config with a higher `maxDuration`, or set
`OPENROUTER_ADVICE_MODEL` to a faster non-reasoning model.

### AI Visual Scan — real vision-model image analysis

`POST /api/vision` (`backend/routers/vision.py`) sends the **actual uploaded image** to a
pretrained vision-language model — `OPENROUTER_VISION_MODEL`, default
`nvidia/nemotron-3.5-super-vl:free`
— and asks what it can literally see: joint
space width and symmetry, bone alignment, visible spurring or sclerosis patterns, soft-tissue
shadows, image positioning and quality. This is independent of Modules 1/2 — it's a second,
unrelated read of the film by a genuine trained model, not a restatement of this platform's own
simulated numbers.

It's deliberately scoped to *observation*, not diagnosis: the system prompt explicitly forbids
stating a diagnosis, a severity grade, or a treatment recommendation, and instructs the model to
say plainly when part of the image is unclear rather than guess. Every response ends with a
one-line reminder that these are visual observations, not a diagnosis.

The image itself is inlined as base64 into the request rather than passed as a URL — a local dev
backend on `127.0.0.1` isn't reachable from OpenRouter's servers to fetch a URL from, but the
backend can always reach the image bytes itself (local disk in dev, Supabase storage in prod), so
the feature works identically in both environments. OpenRouter accepts PNG/JPEG/WEBP/GIF; any
stored image in another format (BMP, TIFF) is converted to PNG with the existing OpenCV pipeline
before sending. See `_resolve_image_data_uri()` in `vision.py`.

### Chat and food advice

- **Chat** (`/api/chat`) is a real multi-turn conversation, capped at 20 messages and 2000
  characters each, using a text model (`OPENROUTER_CHAT_MODEL`, default
  `nvidia/nemotron-3.5-lightning:free` — any chat model on OpenRouter is a drop-in replacement
  against the same endpoint). If you're viewing an
  analysis when you open it, that study's classification, KL grade, thickness, and recommended
  implant are folded into the system prompt automatically.
- **Food advice** (`/api/advice`) is a one-shot write-up tailored to one analysis's OA severity,
  age, and sex, kept distinct from the doctor-authored "Doctor's Advice" field in History. It uses
  `OPENROUTER_ADVICE_MODEL` (same default as chat).
- All three endpoints strip markdown the model leaks despite being told not to
  (`strip_markdown()`), since instruction-following on that specific rule isn't reliable across
  models or modalities.

## AI privacy

**The default free models are for synthetic/demo data only.** The bundled samples are synthetic
films — keep it that way for anything you send through the AI features.

- AI requests (chat text, study context, and for the Visual Scan the image itself) leave this
  application and are processed by an external inference provider, OpenRouter, and the upstream
  model host. The selected free NVIDIA endpoints explicitly prohibit submitting confidential
  information or personal data — do not upload real patient studies while these models are
  configured.
- Prompts include age, sex, affected side and computed measurements — never patient names or
  other direct identifiers — but that is **not** de-identification, and it does not make real
  patient uploads safe to send.
- The backend never logs image contents, base64 payloads, or the API key.
- Using the AI features with real patient data requires switching to models and a provider
  agreement appropriate for that data — that decision and its compliance obligations belong to
  the deploying clinician/organization, not this repository.

## Multi-language

The UI chrome — navigation, auth, settings, the New Analysis form, the two module pages'
headers/tables/buttons, chart legends, the chat widget — is translated across English, Hindi,
Tamil, Malayalam, Telugu via a flat dictionary (`frontend/src/lib/i18n.js`) and
`useLanguage()`/`t()`. Selection persists in `localStorage`; English is the default.

**Not translated, deliberately**: text assembled server-side by interpolating computed values
into English sentences — measurement rationale, KL descriptions, quality-factor detail, implant
manufacturer/system names, research correlation captions. Translating that means localizing the
backend's string assembly, not just adding UI labels. AI-generated text (AI Visual Scan, food advice,
Clinician Note, chat replies) is covered by [local translation](#local-ai-translation) instead.

Classification values (`Normal`/`Mild OA`/`Moderate OA`/`Severe OA`), sex, and side stay the
literal English strings the backend returns everywhere they're used as data (badge color mapping,
filters, chart series keys) — only the *displayed* label is translated.

---

## Local AI translation

AI text is always generated in **English** (the frontend sends `language: "English"` to OpenRouter
regardless of the website language). Changing the website language then translates the
*already-generated* text on your own machine — no OpenRouter request, no tokens, no cloud
translator. The English original is never overwritten; switching back to English restores it
instantly.

- **Model:** [`ai4bharat/indictrans2-en-indic-dist-200M`](https://huggingface.co/ai4bharat/indictrans2-en-indic-dist-200M)
  (MIT, one model for hi/ta/ml/te, ~1.1 GB download, ~1.3 GB RAM when loaded, CPU inference).
  Pinned to revision `2cfd0a20057756d756bf3e53528f492afc52f91a`; its remote code was reviewed
  before enabling `trust_remote_code` (`docs/translation-model-review.md`).
- **Covers:** AI Visual Scan, Food Advice, Clinician Note, AI chat assistant messages.
- **Clinical terms stay in English** (e.g. *Medial joint space narrowing*, *osteophytes*, *AP view*,
  *fibula*, *Kellgren-Lawrence/KL grade*, *MRI*, *X-ray*, *femur*, *tibia*, *varus/valgus*), as do
  numbers, units, dates and file/study IDs. They come from the central dictionary
  `backend/services/medical_terminology.py` (whole-word, longest-phrase-first matching; abbreviations
  such as `AP`/`PA`/`CT` match upper-case only). To protect another term, add it there. If a protected
  value is lost or altered the translation is rejected and the English text stays visible.
- **Meaning checks (rule-based, no extra model):** every translated sentence must keep negation
  (no/not/without/absent) and its qualifiers ("no *definite* effusion"), hedges (possible/probable/suspected/
  appears/may indicate), approximation (about/approximately before a measurement), left/right, the direction
  and roles of comparisons (narrower/wider/greater/less than), severity words (mild/moderate/severe), the
  order of proximal/distal/medial/lateral terms, and which finding sits with which location in multi-clause
  sentences ("narrowing medially, sclerosis laterally"). A sentence that cannot be confirmed makes the whole
  translation fail, the English text stays visible and nothing is cached. (`backend/services/clinical_semantics.py`)
  The model reads "No ..." as the abbreviation for "number", so "no" is sent to it as "not any".
- **Caching:** in the browser tab's memory only, keyed by study + feature + source-text hash +
  language + pipeline version. The server's `pipeline_version` fingerprints the whole pipeline (terminology
  dictionary, "no" input rewrite, spacing/colon repair, meaning-check rules, model revision); the browser
  re-checks it with a cheap status call whenever the language changes, so translations from an older pipeline
  are never shown or reused, only regenerated locally. Failed translations are never cached; nothing is written to storage or server logs.
- **Machine translation notice:** translated cards say so. It is a display convenience, not a
  clinically validated translation; the English text is the source of truth.

First-time setup (local backend only):

```bash
pip install -r backend/requirements.txt -r backend/requirements-translation.txt
# For CPU-only PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cpu
# 1) accept the model terms at the model page above  2) log in once:  hf auth login
python tools/download_translation_model.py      # weights -> backend/.models/ (git-ignored)
```

Then start the backend as usual. The model loads lazily on the first translation (~7 s) and stays
loaded. `GET /api/translate/status` reports availability; set `TRANSLATION_ENABLED=0` to disable.

**Known limitations.** Machine translation can soften or reorder hedges (e.g. "about 2.4 mm"),
and a 200M model can still miss nuance, so clinicians should read the English original for decisions.
The meaning checks are word-list based: they cannot verify which finding a location word belongs to,
"about"/"approximately", or wording outside their lists (such sentences are rejected, not accepted), so
some translations fall back to English (9 of 144 synthetic test translations, all of them genuinely wrong or unverifiable).
Typical CPU speed is 1-3 s per short paragraph. **Vercel:** the serverless backend (50 MB limit)
cannot host PyTorch or the weights, so there `/api/translate` answers `503`, the UI keeps showing
the English text with a short notice, and nothing else is affected. Translation is available
when running the backend locally (or on any host that can install the extra requirements).

---

## Clinical workflow: evidence, comparison, review, demo

Four features sit around the existing analysis, none of them changes a stored result:

- **Clinical Evidence & Provenance** (expandable panel on every study; `GET/POST /api/provenance/{study_id}`).
  Data lineage only, built from the stored record: patient/study metadata, each measurement with value, unit,
  side, algorithm and timestamp, implant sizing, image quality, and the analysis origin (pre-analysed
  reference sidecar vs hash-seeded simulation - stated honestly). Anything not recorded (imaging view,
  algorithm version number) is listed as unavailable. AI observations are shown separately with the
  provider/model/time the *server* recorded at generation; the server signs that block (HMAC), so the panel
  can show "server-verified". AI text is not stored by the platform, so only this session's observations
  appear. There are no confidence scores, saliency maps or explanations of model reasoning. AI provenance is
  returned by `/api/vision` and `/api/advice` only when the request sets `include_provenance: true`; the
  default responses are unchanged. Set `PROVENANCE_SECRET` in production (otherwise signatures last until the
  backend restarts).
- **Longitudinal Comparison** (`/compare/:id`; `GET /api/longitudinal/{id}/candidates`, `POST
  /api/longitudinal/compare`, `GET /api/longitudinal/{id}/series`). The platform stores **no patient ID**: a
  study has the name/sex/side/modality typed at upload inside one account, so "same patient" means same
  normalised name and sex in that account, and every response says so. Comparison is refused for different
  patient, side, modality or measurement method, non-chronological order, duplicate images, decreasing age;
  the imaging view is not recorded, so that is always a warning. Allowed comparisons show stored values,
  absolute and percentage difference (original values, rounded only for display; zero/missing handled),
  side-by-side images with preserved aspect ratio, a timeline and, with three or more values, a trend chart
  at the real dates without interpolation. Wording is "observed measurement difference"; nothing says
  progression or improvement. History lookups are filtered by patient name and capped at 50.
- **Clinician Review** (`POST /api/reviews`, `GET /api/reviews/{study_id}[/{review_id}]`). Decisions
  (confirmed / needs further review / disagreed + comment <= 1000 chars) are appended as immutable audit events
  with previous/new state; the reviewer is the authenticated account (derived from the session token, never
  from the request), labelled "Reviewer" because this system does not verify clinical roles. Reviewable items
  are the stored measurements, classification, implant sizing, the report, and this session's AI observations
  (the exact text is snapshotted with its hash). Duplicate submissions (same `request_id`, or an identical
  consecutive decision) create nothing; a stale `expected_previous_state` is a 409. Storage:
  - **Supabase `study_reviews`** (append-only, RLS) once you apply `docs/migrations/001_study_reviews.sql`
    (additive; rollback at the end of the file; **not applied automatically**).
  - Until then the API falls back to a **local append-only file** and says so (`persistence: "local_file"`):
    useful in development, not a durable clinical record, and not available on Vercel's read-only filesystem.
  `REVIEW_STORE=auto|supabase|file` overrides the choice.
- **Guided Demo** (`/demo`, linked from the Dashboard and sidebar). Ten stages on a bundled synthetic case:
  study overview, image inspection, AI Visual Scan, quantitative analysis, implant module, multilingual,
  provenance, longitudinal comparison, review, report. The case is analysed in memory by the normal builder
  (`GET /api/demo/cases/{source}`), never saved to your history. AI Visual Scan has two explicit modes:
  **Live AI** (the real `/api/vision` call, only when you press the button; a failure stays an error) and
  **Pre-generated** (pre-written synthetic text from `backend/data/demo/cached_ai.json`, labelled as such, valid
  only for the exact sample image hash, analysis model and fixture version; it is never substituted for a
  failed live call). The longitudinal stage uses a labelled **synthetic** three-study series
  (`backend/data/demo/longitudinal_demo.json`, values authored for the demo) plus an intentionally rejected
  right-knee example. The review stage is simulated on screen only and labelled so. The report stage uses
  the existing PDF endpoint. Changing the language translates the AI text locally and makes no AI request.

**SYNTH-KNEE-006 (synthetic longitudinal case).** A second demo series with two examinations of one fictional
patient, built from two radiographs supplied for the demo (`backend/data/demo/synth_knee_006/`: a single right knee,
"STANDING", and a bilateral "AP STANDING" film from which the pipeline selects the right knee). The workflow is the
app's own: upload the baseline, upload the follow-up, open Longitudinal Comparison.
`tools/make_synth_knee_006.py` replays it through the real `POST /api/analyze` (auth stubbed, nothing saved) and
stores each result as its own record (`baseline.json`, `followup.json`). `/api/analyze` and the upload form accept
three **optional** fields - patient ID, examination date, imaging view - plus `.webp`; omit them and nothing
changes. For records that carry a patient ID, **identity is decided by that ID only** (never name or sex: a namesake
with another ID is a different patient, an ID-less record never matches an ID-bearing one) and history discovery
queries by ID; chronology uses the examination date and a recorded view must match. Records without IDs keep the
original name+sex rule. Limits, stated in the UI: these images are not reference samples, so the meniscus/bone/implant
numbers come from the platform's deterministic simulation (hash-seeded from the image bytes), not from measuring the
anatomy (knee region and image quality are computed from the pixels); age, sex and dates are synthetic inputs; the
images are not verified films of one person; the side (Right) was read from the images. Differences are descriptive and
never a progression claim. Pick the series with the selector on the demo's longitudinal stage
(`GET /api/demo/longitudinal?series_id=SYNTH-KNEE-006`).

All new endpoints require the normal login (and MFA). Tests: `tests/test_clinical_workflow.py` (backend,
fake Supabase, no OpenRouter) and the Vitest suites under `frontend/src` (`npm test`).

---

## Image quality & uncertainty

`services/quality.py` scores every upload on four measured signals — effective resolution
(geometric mean of the measured region, not the shorter edge, since a knee region is naturally
~2:1 tall), Laplacian sharpness, intensity spread, and whether `detect_roi` actually isolated the
bone region. The overall score is capped at the *worst* factor plus a small margin rather than a
plain weighted mean, so one disqualifying factor (e.g. a 160px crop) can't be averaged away by
three good ones.

That score derives a ± mm/° tolerance band per measurement type (meniscus thickness, bone
dimensions, tibial slope), shown inline next to the numbers it qualifies, and widens further on
the simulated path (proportional zones) versus the sample path (traced per-pixel polygons). A
score below the "acceptable" threshold — or a failed region detection — triggers a "clinical
review recommended" banner on the results pages.

Verified against the five bundled samples (92–96% quality, no review flag) and against blurred /
downscaled / low-contrast / degenerate inputs (all correctly flagged).

---

## Research Mode

Batch-upload a cohort, or run the bundled samples, for **descriptive statistics only** — no
p-values, no diagnostic claims. `services/cohort.py` reuses the same measurement core as the
single-study path (`analysis_builder.run_measurements`) so a study's numbers can never drift
between its patient view and its cohort row.

- **Quality-gated by default**: studies whose image quality triggers `review_recommended` are
  excluded from statistics and listed separately; an `include_flagged` toggle folds them back in
  for a sensitivity check. One unreadable file in a batch doesn't sink the rest.
- **Comparisons** (OA status, sex, age band) report a difference in means and Cohen's d, gated at
  5 studies per group; **correlations** are gated at 10 complete pairs. Below those sizes, the API
  returns an explicit withheld state with the counts rather than a number computed from a handful
  of studies.
- **On the platform's simulated data specifically**, several associations are structural rather
  than empirical — OA class is assigned by thresholding thickness (so that comparison is circular
  by construction), and simulated thickness carries a coded sex/age drift (so those trends recover
  the generator's own constants). The UI states this at the point of display; against real
  annotated studies the same statistics would be meaningful.

---

## Inference paths

**Dispatch.** `POST /api/analyze` hashes the upload with MD5 and checks it against the sample
sidecars, falling back to a filename match. A hit loads that sidecar; a miss runs a deterministic
simulation. The record shape is identical either way, and all runs present as a unified
`model_inference` workflow.

**Sample sidecars** (`backend/data/samples/*.json`) carry `segmentation_polygon` point lists in
image pixel coordinates for femur, meniscus and tibia, the three meniscus thicknesses, femoral
and tibial AP/ML dimensions, tibial slope, OA class, KL grade, the demographics used at analysis
time, and the implant recommendation. On this path the overlays are drawn as real per-pixel
contours with callipers measured off the actual meniscus polygon — not boxes.

The five samples span KL 0 (Normal, 45 F Left), KL 1 (Mild, 52 M Right), KL 2 (Moderate,
58 F Left), KL 3 (Severe, 66 M Right) and KL 4 (post-TKA candidate, 72 F Left). Their films are
synthesised — real OAI images cannot be redistributed here — by `tools/make_samples.py`, which
writes the image and its sidecar together so the polygons match the pixels exactly. Rerun it with
`.venv/bin/python tools/make_samples.py` (the MD5s in the sidecars change, which is fine —
detection reads them back from the same files).

---

## Simulation logic

For uploads that don't match the pre-analyzed dataset, results are generated by a deterministic
simulation.

**Determinism.** `sha256(image bytes)` seeds a namespaced RNG per subsystem (`meniscus`, `bones`,
`zones`), so identical uploads reproduce identical output while the three subsystems stay
independent.

**Meniscus thickness.** Clamped normal draws per location (Anterior Horn, Mid-Body, Posterior
Horn) inside 2.5–6.5 mm, centred on location means, shifted down for female patients and drifting
~0.02 mm/year past age 35.

**OA classification** on mean thickness uses 4 age-band tiers and sex adjustments:

| Mean thickness | Class       |
|-----------------|-------------|
| `< 3 mm`        | Severe OA   |
| `3 – 4 mm`       | Moderate OA |
| `4 – 5 mm`       | Mild OA     |
| `> 5 mm`         | Normal      |

- **Sex Adjustment:** Female patients receive a **−0.3 mm** shift across all thresholds.
- **Age Adjustments:**
  - `Age < 40`: 0 mm shift
  - `Age 40-50`: -0.15 mm shift
  - `Age 50-60`: -0.35 mm shift
  - `Age > 60`: -0.55 mm shift AND severity is escalated by one grade (e.g. Mild -> Moderate).

The KL grade (0–4) maps from the final class, nudged within its band by absolute thickness so
intermediate grades are reachable.

**Implant matching.** Bone dimensions (femoral ML/AP, tibial ML/AP, tibial slope) are drawn from
sex-specific population means. Each catalogued size is a 4-D centroid; candidates are ranked by
euclidean distance and confidence is `100 · e^(−d/19)`. One recommendation per system, so the two
alternatives are genuinely distinct hardware.

**Overlays.** The bone region is located first with an Otsu threshold: components are merged back
into whole limbs (the joint space splits each one), and on a film showing both knees the limb
matching the affected side is chosen — an AP view is displayed facing the patient, so the
patient's left knee is the one on the viewer's right. Femur / meniscus / tibia zones are then
placed proportionally *inside that region* and hash-jittered, with the meniscus box covering the
medial compartment only. If the threshold finds nothing convincing, the full frame is used. Zones
are drawn with OpenCV — orange femur, green meniscus, pink tibia — with calliper lines and mm
callouts. All eight toggle combinations are pre-rendered at analysis time, so the UI toggles
instantly without another request.

---

## Tests

`tests/test_openrouter_migration.py` covers the AI inference paths — the OpenRouter client
(URL, auth header, model selection, response parsing, timeouts, 401/402/429/5xx), the chat and
advice endpoints (models, limits, study context, multi-language prompts, response contracts), and
the vision endpoint (multimodal payload, actual image bytes, PNG/JPEG passthrough, BMP/TIFF
conversion, local and production image resolution). All external HTTP is mocked; images are
tiny OpenCV-synthesised arrays, never patient data. Stdlib `unittest`, no extra dependencies:

```bash
.venv/bin/python tests/test_openrouter_migration.py
```

`tests/test_e2e.py` drives the live API with generated knee images — no test framework, just the
project venv (OpenCV/NumPy synthesise the test scans, everything else is stdlib). **It predates
authentication** and does not attach a bearer token, so as written it now gets 401s from every
endpoint it exercises; treat it as a reference for the analysis contract and rule-based
classifications rather than a suite you can currently run unmodified. Updating it to sign in via
Supabase first is a natural next step.

```bash
.venv/bin/python tests/test_e2e.py
```

The suite creates 15 analyses and deletes eight; wipe the rest before a demo with:

```bash
rm -rf backend/storage/images backend/storage/reports backend/storage/analyses.json
```

---

## Design system

**Warm Toon 3D Aesthetic:**
- **Background:** Beach cream (`#FFF5E4`)
- **Cards:** White surface with thick dark brown borders (`2px solid #2D2016`) and offset
  box-shadows (`4px 4px 0 #2D2016`)
- **Accent colors:** Vibrant orange (`#E8772E`), green (`#2D9F6F`), pink (`#E85D75`)
- **Typography:**
  - Headers: **Newsreader** (Serif)
  - UI/Labels: **Space Grotesk**
  - Body: **Inter**

The interface is fully responsive down to mobile with a collapsible sidebar and clean separation
of assessment modules.

---

## Disclaimer

This tool is intended for research and decision support only. Final diagnosis remains with the
clinician. The AI Visual Scan and chat/food-advice features call real hosted models through an
external provider (see [AI privacy](#ai-privacy) — the default free configuration is for
synthetic/demo data only), but none of
them are validated diagnostic tools, and the AI Visual Scan is explicitly instructed never to
state a diagnosis. The quantitative measurements in Modules 1 and 2 — thickness, OA class, KL
grade, bone dimensions — are simulated, not the output of a validated measurement model; see
[Simulation logic](#simulation-logic).
