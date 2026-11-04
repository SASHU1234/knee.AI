import { getTranslateStatus, translateText } from './api'

/**
 * Session-only (in-memory) translation cache. Nothing is written to
 * localStorage/sessionStorage: translated clinical text stays in this tab's
 * memory and disappears on reload.
 *
 * Key: studyId | feature | sourceHash | targetLanguage | pipelineVersion.
 * - The hash of the English source is in the key, so changed source text can never
 *   hit a stale entry (old hashes for the same study+feature are evicted).
 * - pipelineVersion is the server's fingerprint of the WHOLE translation pipeline
 *   (medical-terminology dictionary, "no" input rewrite, formatting repair, clinical
 *   semantic-validation rules, model revision). It is learned from every translate
 *   response and re-checked via the cheap /translate/status call whenever the language
 *   changes. A different version makes older entries unreachable (the key changes) and
 *   deletes them; they are regenerated locally on demand. Only this translation cache is
 *   touched; English originals and other caches are not.
 * - Failed or rejected (HTTP 422) translations are never stored.
 */
const cache = new Map()
const inflight = new Map() // key -> { promise, refs }
const listeners = new Set()
let queue = Promise.resolve() // translations run one at a time (server has one model)
let pipelineVersion = null // unknown until the server tells us
let lastVersionCheck = 0
let inflightCheck = null // shared promise so many components trigger one status call
let versionCheckIntervalMs = 5000

export const getPipelineVersion = () => pipelineVersion
export const subscribePipelineVersion = (fn) => {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
/** Tests only: how often the status endpoint may be polled. */
export const setVersionCheckInterval = (ms) => { versionCheckIntervalMs = ms }

export function hashText(text) {
  let h = 5381
  for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0
  return (h >>> 0).toString(36) + ':' + text.length
}

export const makeKey = (studyId, feature, text, lang) =>
  `${studyId || '-'}|${feature}|${hashText(text)}|${lang}|${pipelineVersion ?? '?'}`

export const getCached = (key) => cache.get(key)

export function clearTranslationCache() {
  cache.clear()
  inflight.clear()
  pipelineVersion = null
  lastVersionCheck = 0
  inflightCheck = null
  listeners.forEach((fn) => fn())
}

/** Adopt the server's pipeline version; drop translations made under any other version. */
function adoptPipelineVersion(version) {
  if (!version || version === pipelineVersion) return
  pipelineVersion = version
  for (const k of cache.keys()) {
    if (k.split('|')[4] !== version) cache.delete(k)
  }
  listeners.forEach((fn) => fn())
}

/**
 * Ask the server for its current pipeline version (cheap, never loads the model; throttled).
 * Components call this when the language changes and wait for it BEFORE reading the cache or
 * requesting a translation, so a translation from an older pipeline is never shown or reused.
 */
export function refreshPipelineVersion() {
  if (inflightCheck) return inflightCheck
  const now = Date.now()
  if (now - lastVersionCheck < versionCheckIntervalMs) return Promise.resolve()
  lastVersionCheck = now
  inflightCheck = (async () => {
    try {
      const s = await getTranslateStatus()
      adoptPipelineVersion(s?.pipeline_version || s?.terminology_version)
    } catch {
      // status unavailable: keep what we have; translate responses still carry the version
    } finally {
      inflightCheck = null
    }
  })()
  return inflightCheck
}

function evictStale(key) {
  const [study, feature, hash] = key.split('|')
  const prefix = `${study}|${feature}|`
  for (const k of cache.keys()) {
    if (k.startsWith(prefix) && k.split('|')[2] !== hash) cache.delete(k)
  }
}

/**
 * Returns { promise, release }. Identical in-flight requests are shared. If
 * every caller releases before the queued job starts (e.g. rapid language
 * switching), the request is never sent.
 */
export function requestTranslation(key, text, lang, contentType) {
  const hit = cache.get(key)
  if (hit !== undefined) return { promise: Promise.resolve(hit), release() {} }

  let entry = inflight.get(key)
  if (!entry) {
    entry = { refs: 0 }
    entry.promise = new Promise((resolve, reject) => {
      queue = queue.then(async () => {
        if (entry.refs <= 0) {
          inflight.delete(key)
          reject(new Error('cancelled'))
          return
        }
        try {
          const res = await translateText(text, lang, contentType)
          const translated = res?.translated_text
          if (typeof translated === 'string' && translated.trim()) {
            adoptPipelineVersion(res.pipeline_version || res.terminology_version)
            const parts = key.split('|')
            parts[4] = pipelineVersion ?? '?'
            const finalKey = parts.join('|')
            evictStale(finalKey)
            cache.set(finalKey, translated) // only successes are cached
            resolve(translated)
          } else {
            reject(new Error('Empty translation'))
          }
        } catch (e) {
          reject(e) // includes HTTP 422 (rejected by safety checks): nothing is cached
        } finally {
          inflight.delete(key)
        }
      })
    })
    entry.promise.catch(() => {})
    inflight.set(key, entry)
  }
  entry.refs += 1
  let released = false
  return {
    promise: entry.promise,
    release() {
      if (!released) { released = true; entry.refs -= 1 }
    },
  }
}
