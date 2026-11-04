/**
 * About-page technical content. Deliberately ENGLISH ONLY: model identifiers, library names, versions and
 * implementation notes are proper nouns / precise technical statements, and the page says so (abTechEnglishNote).
 * Headings, summaries, the clinical-limitations list and navigation are translated in i18nAbout.js.
 *
 * Every statement here was checked against the repository (source files named in comments). Versions are the
 * ones installed/pinned in this project; models marked "configured default" can be changed by environment variable.
 */

/** Hosted-inference defaults: backend/services/openrouter_client.py, overridable via OPENROUTER_*_MODEL. */
export const MODELS = {
  vision: 'nvidia/nemotron-3.5-super-vl:free',
  chat: 'nvidia/nemotron-3.5-lightning:free',
  advice: 'nvidia/nemotron-3.5-lightning:free',
  translation: 'ai4bharat/indictrans2-en-indic-dist-200M',
  translationRevision: '2cfd0a2', // pinned in backend/services/local_translation_service.py (full 40-char SHA there)
}

/** Capability details (expandable). Keys match the capability ids used in About.jsx. */
export const CAPABILITY_DETAILS = {
  vision: [
    'The uploaded image itself is sent to a hosted vision-language model through OpenRouter, inlined as a base64 data URI in an image_url message part; BMP/TIFF are first converted to PNG with OpenCV.',
    `Configured default model: ${MODELS.vision} (OPENROUTER_VISION_MODEL). Temperature 0.4, 2000-token budget.`,
    'The system prompt restricts the model to visible features (joint space, alignment, spurring or sclerosis patterns, soft-tissue shadows, positioning/quality) and forbids stating a diagnosis, severity grade or treatment.',
    'Output is plain text ending with a note that these are visual observations, not a diagnosis. It is not stored by the platform; it lives in the session (optionally with a signed provenance block).',
    'Limits: the default free model is rate-limited, may omit or misdescribe features, and the provider terms prohibit personal data, so use synthetic or de-identified images only.',
  ],
  chat: [
    `Text-only conversation through OpenRouter (configured default ${MODELS.chat}); the model never receives an image. Temperature 0.6.`,
    'Multi-turn with validation: at most 20 messages per conversation and 2000 characters per message; the last message must come from the user.',
    'If a study is open, a short summary of its key numbers (age, sex, side, OA class, KL grade, mean thickness, recommended implant) is added to the system prompt as context.',
    'Replies are generated in English and translated locally for display, so changing the website language costs no extra OpenRouter request.',
  ],
  advice: [
    `One-shot text generation (configured default ${MODELS.advice}) from the patient's age, sex, side, OA class, KL grade and meniscus thickness.`,
    'Plain-text, food-focused guidance with 2-3 sample meal ideas, ending with a sentence that it is general guidance and not a substitute for a clinician or registered dietitian.',
    'It is general educational information, not prescribed medical nutrition therapy. English generation, local translation for display.',
  ],
  quant: [
    'Computed from pixels with OpenCV/NumPy: decoding (Pillow fallback), resizing so the longest edge is at most 1100 px, Otsu-threshold bone-region detection with morphology and connected components (choosing the limb that matches the affected side on bilateral films), image-quality heuristics (resolution, Laplacian sharpness, contrast, region found) and the overlay drawing.',
    'For the 5 bundled reference cases, segmentation polygons and all thickness/bone/implant numbers are read from JSON sidecars labelled "nnU-Net v2 (3d_fullres) + MedSAM refinement". Those models are NOT executed inside this repository; the sidecars stand in for their output.',
    'For any other upload, medial meniscus thickness at three locations and the bone dimensions are a deterministic simulation seeded from the SHA-256 of the image bytes. They are not measurements of the anatomy.',
    'OA class is a rule-based threshold on mean medial meniscus thickness, adjusted by sex and age band; the Kellgren-Lawrence grade is an estimate mapped from class, thickness and age. Both are decision-support numbers, not diagnoses.',
    'Tolerance bands are derived from image quality and are wider for proportional zones than for per-pixel polygons. They are heuristics, not statistical confidence intervals.',
    'The imaging type (X-ray / MRI) is stored as a label; no MRI-specific processing exists.',
  ],
  implant: [
    'Bone dimensions (femoral ML/AP, tibial ML/AP, tibial slope) come from the sidecar or the simulation above.',
    'Matching is a Euclidean distance in 4-D (femoral ML/AP, tibial ML/AP) to the centroid of every catalogued size; the lowest distance wins and the top three are listed.',
    'The "match" percentage is a mapping from that distance, not a probability. The catalogue holds nominal published component footprints and is marked in the data file as for simulation use only.',
    'No biomechanical, fit or surgical-compatibility validation is performed, and the module does not select an implant for surgery.',
  ],
  provenance: [
    'Built only from the stored study record: patient/study metadata, each measurement with value, unit, side, algorithm description and timestamp, implant sizing and image quality. Fields that were not recorded (imaging view, algorithm version number) are listed as unavailable.',
    'The analysis origin is stated honestly: "pre-analysed reference case (sidecar)" or "deterministic simulation".',
    'AI observations are listed separately. The server issues an HMAC-signed provenance block (provider, model, time, source image, SHA-256 of the text) when asked, and later verifies it; the text itself is not stored.',
    'It shows where results came from. It is not a model explanation: there are no confidence scores, saliency maps or chain-of-thought.',
  ],
  longitudinal: [
    'Compares two stored examinations. The platform has no patient registry: for ordinary studies "same patient" means same normalised name and sex within one account. Records carrying an explicit patient ID are matched by that ID only.',
    'Comparison is refused for a different patient, side, modality or measurement method, non-chronological order, duplicate images, a decreasing age, or a differing recorded imaging view. A missing view is shown as a warning.',
    'For allowed pairs it shows each stored value, the absolute difference and the percentage difference, calculated from the original unrounded values, plus the images side by side, a timeline and (three or more values) a trend chart without interpolation.',
    'SYNTH-KNEE-006 is illustrative synthetic demonstration data: two independently sourced radiographs assigned to a fictional patient ID. They are not two examinations of the same person, their numbers come from the deterministic simulation, and the page makes no claim about OA progression.',
  ],
  review: [
    'States: pending review, confirmed by reviewer, needs further review, disagreed with observation, each with an optional comment (up to 1000 characters).',
    'Every decision is a new append-only event with previous and new state; nothing overwrites the reviewed result. Duplicate submissions and stale updates are rejected.',
    'The reviewer is the signed-in account, taken from the session on the server. The system does not verify clinical credentials, so it says "Reviewer", not "verified clinician".',
    'Durable storage needs the study_reviews migration in your Supabase project. Without it, reviews fall back to a local file on the backend (labelled as development storage). Reviews in the Guided Demo are simulated on screen and never stored.',
  ],
  demo: [
    'Ten stages: study overview, image inspection, AI Visual Scan, quantitative analysis, implant module, multilingual, provenance, longitudinal comparison, human review, report.',
    'Cases are the five bundled synthetic samples, analysed in memory and never saved to your history. AI Visual Scan has two explicit modes: live (the real vision call, only on button press) or pre-generated text.',
    'Pre-generated results are pre-written demonstration text, not model output; they are tied to the sample image hash, the analysis model label and a fixture version, and a failed live call is never replaced by them.',
    'The report stage uses the existing PDF endpoint.',
  ],
}

/** Architecture details (expandable). */
export const ARCH_DETAILS = {
  frontend: [
    'React 18 function components and hooks, built with Vite; React Router for routing (including session/MFA-gated routes); Tailwind CSS with a custom theme; Recharts for charts; no UI component library (cards, buttons and icons are hand-built).',
    'State: component state plus two React contexts (authentication, language). No global state library.',
    'API: fetch with the Supabase access token as a Bearer header; in development Vite proxies /api to FastAPI. History and Dashboard also read the analyses table directly from Supabase under row-level security.',
    'Internationalisation: a small in-house dictionary (one flat key-to-string map per language) with English fallback, plus the local translation engine for AI-generated text.',
  ],
  backend: [
    'Python (developed on 3.12) with FastAPI and Pydantic. Routers in backend/routers handle HTTP and validation; business logic lives in backend/services; Supabase access is isolated in services/supabase_client.py; a small JSON-on-disk store backs report generation.',
    'Routers: analysis, report, advice, chat, vision, translate, research, provenance, longitudinal, reviews, demo.',
    'Errors are returned as HTTP errors with fixed messages; upstream OpenRouter bodies and stack traces are never echoed to the client.',
    'Authentication: the bearer JWT is verified through Supabase (auth.get_user). If the account has a verified TOTP factor, the token must carry assurance level aal2. Each database call uses a per-request client carrying the caller JWT, so row-level security applies.',
  ],
  ai: [
    'Frontend → FastAPI → OpenRouter → configured model → FastAPI → frontend. OpenRouter is the hosted inference gateway; the backend holds the API key, which is never sent to the browser.',
    'Three separate pathways: vision-language inference (image + prompt), conversational text inference, and one-shot food-advice text generation. Each has its own configurable model id and token budget.',
    'Image-based and text-based inference are kept apart: only AI Visual Scan receives pixels. Quantitative results are never produced by these models.',
  ],
  translation: [
    `Local IndicTrans2 distilled 200M (${MODELS.translation}, MIT licence, revision ${MODELS.translationRevision} pinned, ~1.1 GB). It loads lazily once per process on CPU, or CUDA when available. It is an optional install that cannot run on the Vercel backend, where the API answers 503 and the UI keeps the English text.`,
    'Why local: translation of already-generated English text costs no OpenRouter tokens, makes no extra request when the language changes, and sends no text to a third-party translator.',
    'Protected terminology: numbers, units, dates, KL grades, identifiers and a central dictionary of anatomical, radiological and clinical terms (AP, fibula, osteophytes, meniscus, varus, ...) are masked with placeholders before translation and restored exactly afterwards; they stay in English by design.',
    'Validation: placeholders must all come back intact; "no" is rewritten to "not any" for the model because it otherwise reads "No" as "number"; a rule-based check (no extra model) requires negation, hedges, approximation, left/right, comparisons, severity and finding-to-location binding to survive. One stricter retry, then rejection.',
    'On any failure the original English is shown (the server answers 422), nothing is cached, and the English response is never overwritten.',
    'Cache: in browser memory only, keyed by study, feature, source-text hash, language and a pipeline version that fingerprints the dictionary, rules, code and model revision, so older translations are never reused.',
    'Machine translation is a display convenience and is not clinically validated.',
  ],
  image: [
    '1. Ingestion: JPEG, PNG, WebP, BMP, TIFF and DICOM-lite file extensions up to 25 MB; empty or undecodable files are rejected.',
    '2. Normalisation: decode with OpenCV (Pillow fallback), resize so the longest edge is at most 1100 px.',
    '3. Region detection: Otsu threshold, morphology, connected components, column clustering; on bilateral films the limb matching the affected side is chosen.',
    '4. Quality assessment: resolution, Laplacian sharpness, contrast and region-found heuristics combined into a score.',
    '5. Zones and measurements: per-pixel polygons from a reference sidecar, or proportional zones fitted to the detected region; numbers from the sidecar or the seeded simulation (see Quantitative analysis).',
    '6. Result preparation: overlay variants drawn with OpenCV, uncertainty bands, rule-based OA class, KL estimate, implant matching, record assembly and PDF report (ReportLab).',
  ],
  data: [
    'Supabase provides authentication (email/password, TOTP MFA), the Postgres analyses table and a Storage bucket for overlay images. Row-level security on analyses is configured in your Supabase project (documented in the README, not defined by SQL in this repository). The study_reviews table ships as an additive migration with insert/select-only policies.',
    'Study access: backend lookups run as the caller, so another account\'s study is reported as not found; reviews and comparisons use the same lookup.',
    'Secrets (OpenRouter key, provenance signing key) stay in backend environment variables.',
    'Not implemented or not claimed: end-to-end encryption, regulatory certification, formal HIPAA/GDPR compliance. Overlay images are served through Supabase Storage URLs, and hosted AI providers receive the data sent to them, so use synthetic or de-identified data.',
  ],
}

/** Feature status: what works as-is, what needs configuration, what is demonstration-only. */
export const STATUS = [
  { id: 'vision', status: 'ok', note: 'Live on the local host via OpenRouter' },
  { id: 'chat', status: 'ok', note: 'Live on the local host via OpenRouter' },
  { id: 'advice', status: 'ok', note: 'Live on the local host via OpenRouter' },
  { id: 'quant', status: 'ok', note: 'Reference-sidecar values for bundled cases, deterministic simulation otherwise' },
  { id: 'implant', status: 'ok', note: 'Dimensional matching against a nominal catalogue' },
  { id: 'translation', status: 'ok', note: 'Runs locally on this host (IndicTrans2, CPU)' },
  { id: 'provenance', status: 'ok', note: 'Operational; AI signatures last for the current server session' },
  { id: 'longitudinal', status: 'ok', note: 'Needs at least two compatible stored studies; SYNTH-KNEE-006 is demo data' },
  { id: 'review', status: 'ok', note: 'Operational on the local host; records are stored locally and labelled as such' },
  { id: 'demo', status: 'demo', note: 'Synthetic data; pre-generated AI text is pre-written, not live' },
]

/** Technology stack, grouped by purpose. `core:false` marks optional dependencies. */
export const STACK = [
  { group: 'frontend', items: [
    { name: 'React', version: '18.3.1', use: 'All pages and components (function components + hooks).' },
    { name: 'Vite', version: '5.4.21', use: 'Dev server, production build and /api proxy.' },
    { name: 'React Router', version: '6.30.6', use: 'Client routing, including session/MFA-gated routes.' },
    { name: 'Tailwind CSS', version: '3.4.19', use: 'Styling with a custom theme.' },
    { name: 'Recharts', version: '2.15.4', use: 'Thickness comparison, cohort and longitudinal trend charts.' },
    { name: 'Supabase JS', version: '2.112.3', use: 'Sign-in, TOTP MFA and RLS-scoped reads.' },
    { name: 'qrcode', version: '1.5.4', use: 'Renders the 2FA setup QR code in the browser.' },
  ] },
  { group: 'backend', items: [
    { name: 'Python', version: '3.12.10 (dev)', use: 'Runtime for the API and services.' },
    { name: 'FastAPI', version: '0.115.6', use: 'HTTP API; routers per feature.' },
    { name: 'Pydantic', version: '2.10.4', use: 'Request validation and response models.' },
    { name: 'Uvicorn', version: '0.34.0', use: 'ASGI server for local development.' },
    { name: 'httpx', version: '0.28.1', use: 'Outbound calls (OpenRouter, stored-image fetch).' },
    { name: 'ReportLab', version: '4.2.5', use: 'PDF clinical report.' },
    { name: 'python-multipart / python-dotenv', version: '0.0.20 / 1.0.1', use: 'Upload parsing; local environment loading.' },
  ] },
  { group: 'ai', items: [
    { name: 'OpenRouter', version: null, use: 'Hosted inference gateway for the three AI pathways.' },
    { name: MODELS.vision, version: 'configured default', use: 'AI Visual Scan (vision-language, receives the image).' },
    { name: MODELS.chat, version: 'configured default', use: 'AI Chat and Food Advice (text only).' },
  ] },
  { group: 'vision', items: [
    { name: 'OpenCV (headless)', version: '4.10.0.84', use: 'Decode, Otsu region detection, quality heuristics, overlay drawing.' },
    { name: 'NumPy', version: '2.0.2', use: 'Array maths for the image pipeline.' },
    { name: 'Pillow', version: '11.0.0', use: 'Fallback decoder for formats OpenCV declines.' },
  ] },
  { group: 'segmentation', items: [
    { name: 'nnU-Net v2 / MedSAM', version: null, use: 'Named in the bundled sample sidecars as the origin of their segmentations. Not executed in this repository; no segmentation model runs here.' },
  ] },
  { group: 'translation', items: [
    { name: 'IndicTrans2 (distilled 200M)', version: `revision ${MODELS.translationRevision}`, use: 'Local English to Hindi/Tamil/Malayalam/Telugu translation.', core: false },
    { name: 'PyTorch', version: '2.15.0 (CPU build installed locally; requirement >=2.2)', use: 'Runs the translation model.', core: false },
    { name: 'Transformers / IndicTransToolkit / SentencePiece', version: '4.51.3 / 1.1.1 / 0.2.2', use: 'Model loading, Indic pre/post-processing, tokenisation.', core: false },
  ] },
  { group: 'data', items: [
    { name: 'Supabase (Auth, Postgres, Storage)', version: 'supabase-py 2.11.0', use: 'Accounts and MFA, the analyses table, overlay-image bucket, optional study_reviews table.' },
  ] },
  { group: 'testing', items: [
    { name: 'pytest', version: null, use: 'Backend unit and API tests (mocked AI and Supabase).', core: false },
    { name: 'Vitest + Testing Library + jsdom', version: 'Vitest 2.1.9', use: 'Frontend unit and component tests (dev only).', core: false },
    { name: 'Vercel', version: null, use: 'Static frontend and Python serverless backend (two projects); the local translation engine does not fit there.' },
  ] },
]
