import { supabase } from './supabase'

const BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')

async function fetchWithAuth(url, options = {}) {
  const { data: { session } } = await supabase.auth.getSession()
  const headers = { ...options.headers }
  if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`
  }
  return fetch(url, { ...options, headers })
}

async function handle(res) {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch (_) { /* non-JSON error body */ }
    const err = new Error(detail)
    err.status = res.status // 422 = translation rejected by the safety checks
    throw err
  }
  return res.json()
}

export function analyze(file, patient) {
  const form = new FormData()
  form.append('file', file)
  form.append('name', patient.name)
  form.append('age', String(patient.age))
  form.append('sex', patient.sex)
  form.append('imaging_type', patient.imaging_type)
  form.append('affected_side', patient.affected_side)
  // optional longitudinal metadata: only sent when the user filled it in
  if (patient.synthetic_patient_id) form.append('synthetic_patient_id', patient.synthetic_patient_id)
  if (patient.examined_date) form.append('examined_date', patient.examined_date)
  if (patient.imaging_view) form.append('imaging_view', patient.imaging_view)
  return fetchWithAuth(`${BASE}/analyze`, { method: 'POST', body: form }).then(handle)
}

export const listSamples = () => fetchWithAuth(`${BASE}/samples`).then(handle)

export function analyzeSample(source, name) {
  const form = new FormData()
  if (name) form.append('name', name)
  return fetchWithAuth(`${BASE}/analyze/sample/${source}`, { method: 'POST', body: form }).then(handle)
}

export const listAnalyses = async () => {
  const { data, error } = await supabase.from('analyses').select('*').order('created_at', { ascending: false })
  if (error) throw new Error(error.message)
  
  // Map it to the expected compact format for the History page
  const items = data.map(r => ({
    analysis_id: r.analysis_id,
    created_at: r.created_at,
    patient: r.record.patient,
    classification: r.record.meniscus.assessment.classification,
    kl_grade: r.record.meniscus.kl_grade.grade,
    mean_thickness_mm: r.record.meniscus.assessment.mean_thickness_mm,
    primary_implant: `${r.record.implant.primary.system} ${r.record.implant.primary.size} (${r.record.implant.primary.manufacturer})`,
    confidence_pct: r.record.implant.primary.confidence_pct,
    mode: r.record.mode || 'demo',
    mode_label: r.record.mode_label || 'Demo Mode',
    thumbnail: r.record.images.variants['femur-meniscus-tibia'],
    advice: r.advice
  }))
  return { count: items.length, items }
}

export const getAnalysis = async (id) => {
  const { data, error } = await supabase.from('analyses').select('*').eq('analysis_id', id).maybeSingle()
  if (error) throw new Error(error.message)
  if (!data) throw new Error('Analysis not found')
  // Inject the advice into the record before returning
  const record = data.record
  record.advice = data.advice
  return record
}

export const deleteAnalysis = async (id) => {
  const { error } = await supabase.from('analyses').delete().eq('analysis_id', id)
  if (error) throw new Error(error.message)
  return { deleted: id }
}

export const updateAdvice = async (id, adviceText) => {
  const { error } = await supabase.from('analyses').update({ advice: adviceText }).eq('analysis_id', id)
  if (error) throw new Error(error.message)
  return { success: true }
}

/**
 * AI text is always generated in English, whatever the website language is.
 * Display language is handled afterwards by local translation (see
 * translateText / useTranslatedText) so switching language never costs an
 * OpenRouter request. The `language` params below are kept for call-site
 * compatibility but deliberately ignored.
 */
const GENERATION_LANGUAGE = 'English'

/**
 * One turn of the floating assistant chat. `messages` is the full history so
 * far; `language` is the full English name of the reply language (e.g.
 * "Tamil"), omitted for English so the request stays identical to before
 * this feature existed.
 */
export const sendChatMessage = (messages, record, language) =>
  fetchWithAuth(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages, record: record || undefined,
      language: GENERATION_LANGUAGE,
    }),
  }).then(handle)

export const getFoodAdvice = (record, language) =>
  fetchWithAuth(`${BASE}/advice`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      record,
      language: GENERATION_LANGUAGE,
      include_provenance: true,
    }),
  }).then(handle)

/**
 * A vision model's own read of the uploaded image — independent of this
 * platform's own (simulated) measurements. `filename` is the original
 * ("none" variant) image filename from the analysis record.
 */
export const getVisionObservations = (filename, record, language) =>
  fetchWithAuth(`${BASE}/vision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename, record,
      language: GENERATION_LANGUAGE,
      include_provenance: true,
    }),
  }).then(handle)

/** Batch-analyse studies and return cohort statistics. */
export function analyseCohort(files, meta = {}, includeFlagged = false) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  if (meta.ages) form.append('ages', meta.ages.join(','))
  if (meta.sexes) form.append('sexes', meta.sexes.join(','))
  if (meta.sides) form.append('sides', meta.sides.join(','))
  form.append('include_flagged', String(includeFlagged))
  return fetchWithAuth(`${BASE}/research/cohort`, { method: 'POST', body: form }).then(handle)
}

/** Cohort over the bundled reference samples — no upload needed. */
export function analyseSampleCohort(includeFlagged = false) {
  const form = new FormData()
  form.append('include_flagged', String(includeFlagged))
  return fetchWithAuth(`${BASE}/research/cohort/samples`, { method: 'POST', body: form }).then(handle)
}

export const getImplants = () => fetchWithAuth(`${BASE}/implants`).then(handle)
export const health = () => fetchWithAuth(`${BASE}/health`).then(handle)

// If the value is already a data URL (base64), return it directly.
// Otherwise construct the API endpoint URL for file-based serving.
export const imageUrl = (filenameOrDataUrl) => {
  if (!filenameOrDataUrl) return ''
  if (filenameOrDataUrl.startsWith('data:')) return filenameOrDataUrl
  return `${BASE}/images/${filenameOrDataUrl}`
}
export async function downloadReport(result) {
  const res = await fetch(`${BASE}/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record: result }),
  })
  if (!res.ok) {
    let detail = 'Failed to generate report'
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch (_) { /* ignore */ }
    throw new Error(detail)
  }
  
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  
  const contentDisp = res.headers.get('Content-Disposition') || ''
  const match = contentDisp.match(/filename="?([^"]+)"?/)
  a.download = match ? match[1] : `Knee_Report_${result.analysis_id || 'Unknown'}.pdf`
  
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
// Rewrite backend-returned relative sample image paths to the correct absolute URL.
// The backend returns "/api/samples/{source}/image" but in production the frontend
// is on a different domain than the backend, so we must prefix with BASE's origin.
export const sampleImageUrl = (relOrAbs) => {
  if (!relOrAbs) return ''
  if (relOrAbs.startsWith('http')) return relOrAbs
  // relOrAbs is like "/api/samples/OAI_sample_01/image"
  // BASE is like "https://kneeai.vercel.app/api" or "/api" for local dev
  const origin = BASE.startsWith('http') ? new URL(BASE).origin : ''
  return `${origin}${relOrAbs}`
}

/** Key into images.variants for a given overlay toggle state. */
export function variantKey(toggles) {
  const active = ['femur', 'meniscus', 'tibia'].filter((s) => toggles[s]).sort()
  return active.length ? active.join('-') : 'none'
}

/** Local (on-server) machine translation of existing English AI text. */
export const translateText = (text, targetLanguage, contentType, signal) =>
  fetchWithAuth(`${BASE}/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, target_language: targetLanguage, content_type: contentType }),
    signal,
  }).then(handle)

/** Cheap (no model) status call: availability and the server's translation-pipeline version. */
export const getTranslateStatus = () => fetchWithAuth(`${BASE}/translate/status`).then(handle)

// ---- Evidence & provenance, longitudinal comparison, clinician review, guided demo -------------
const jsonPost = (url, body) =>
  fetchWithAuth(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(handle)

/** aiItems: [{ provenance, text }] - signed blocks the server issued for this session's AI text. */
export const getProvenance = (studyId, aiItems = []) =>
  aiItems.length
    ? jsonPost(`${BASE}/provenance/${studyId}`, { ai_items: aiItems.map(({ provenance, text }) => ({ provenance, text })) })
    : fetchWithAuth(`${BASE}/provenance/${studyId}`).then(handle)

export const getComparisonCandidates = (studyId) => fetchWithAuth(`${BASE}/longitudinal/${studyId}/candidates`).then(handle)
export const compareStudies = (previousId, currentId) =>
  jsonPost(`${BASE}/longitudinal/compare`, { previous_id: previousId, current_id: currentId })
export const getMeasurementSeries = (studyId, measurement) =>
  fetchWithAuth(`${BASE}/longitudinal/${studyId}/series?measurement=${encodeURIComponent(measurement)}`).then(handle)

export const listReviews = (studyId) => fetchWithAuth(`${BASE}/reviews/${studyId}`).then(handle)
/** The reviewer is never sent: the server derives it from the session token. */
export const submitReview = (payload) => jsonPost(`${BASE}/reviews`, payload)

export const listDemoCases = () => fetchWithAuth(`${BASE}/demo/cases`).then(handle)
export const getDemoCase = (source) => fetchWithAuth(`${BASE}/demo/cases/${source}`).then(handle)
export const getDemoCaseProvenance = (source) => fetchWithAuth(`${BASE}/demo/cases/${source}/provenance`).then(handle)
export const getDemoCachedAi = (source) => fetchWithAuth(`${BASE}/demo/cases/${source}/cached-ai`).then(handle)
export const getDemoLongitudinal = (seriesId) =>
  fetchWithAuth(`${BASE}/demo/longitudinal${seriesId ? `?series_id=${encodeURIComponent(seriesId)}` : ''}`).then(handle)
export const listDemoSeries = () => fetchWithAuth(`${BASE}/demo/longitudinal/series`).then(handle)

