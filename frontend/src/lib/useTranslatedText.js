import { useEffect, useState, useSyncExternalStore } from 'react'
import { useLanguage } from './LanguageContext'
import {
  getCached,
  getPipelineVersion,
  makeKey,
  refreshPipelineVersion,
  requestTranslation,
  subscribePipelineVersion,
} from './translationCache'

/**
 * Display value for an English AI-generated string, driven by the existing
 * website language (LanguageContext) — there is no separate language state.
 *
 * - English (or empty source): returns `source` untouched, no request.
 * - Other language: first confirms the server's translation-pipeline version (cheap status
 *   call), then returns the cached translation instantly, otherwise English while the local
 *   translation runs (`loading`), then the translation.
 * - Failure or safety rejection (HTTP 422): English stays displayed, `error` is set
 *   (`rejected` when the server refused the translation), nothing is cached.
 * The source string is never modified. The cache key includes the pipeline version, and the
 * version is verified before the cache is read, so translations from an older pipeline
 * (dictionary, negation handling, formatting, semantic rules) are never shown or reused.
 */
export function useTranslatedText(source, { studyId, feature, contentType } = {}) {
  const { language } = useLanguage()
  // re-render (and re-key) whenever the server's pipeline version changes
  useSyncExternalStore(subscribePipelineVersion, getPipelineVersion)
  const [verifiedFor, setVerifiedFor] = useState(null) // language whose pipeline version was confirmed
  const [state, setState] = useState({ key: null, text: null, error: null, rejected: false })

  useEffect(() => {
    if (language === 'en') {
      setVerifiedFor(null) // returning to a language later must re-verify
      return undefined
    }
    let live = true
    refreshPipelineVersion().then(() => live && setVerifiedFor(language))
    return () => { live = false }
  }, [language])

  const active = language !== 'en' && !!source
  const ready = verifiedFor === language
  const key = active ? makeKey(studyId, feature, source, language) : null
  const cached = key && ready ? getCached(key) : undefined

  useEffect(() => {
    if (!key || !ready || getCached(key) !== undefined) return undefined
    let current = true // flips on cleanup: language/source changed => result is stale
    const req = requestTranslation(key, source, language, contentType)
    req.promise
      .then((text) => current && setState({ key, text, error: null, rejected: false }))
      .catch((e) => current && e.message !== 'cancelled' &&
        setState({ key, text: null, error: e.message, rejected: e.status === 422 }))
    return () => {
      current = false
      req.release()
    }
  }, [key, ready]) // eslint-disable-line react-hooks/exhaustive-deps

  const base = { text: source, loading: false, error: null, translated: false, rejected: false }
  if (!active) return base
  if (cached !== undefined) return { ...base, text: cached, translated: true }
  if (ready && state.key === key && state.text) return { ...base, text: state.text, translated: true }
  if (ready && state.key === key && state.error) return { ...base, error: state.error, rejected: state.rejected }
  return { ...base, loading: true }
}
