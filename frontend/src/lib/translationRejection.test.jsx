/**
 * End-to-end frontend behaviour for a server-side translation failure, using the REAL api.js
 * (only fetch and the Supabase session are stubbed): an HTTP 422 from /api/translate must leave the
 * English original on screen, show the "could not be verified" notice, and cache nothing.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./supabase', () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: { access_token: 'test-token' } } }) } },
}))

import TranslatedBlock from '../components/TranslatedBlock'
import { DICTIONARIES } from './i18n'
import { LanguageProvider, useLanguage } from './LanguageContext'
import { clearTranslationCache, setVersionCheckInterval } from './translationCache'

const SOURCE = 'No fracture is seen. The left knee shows possible narrowing.'
const REJECT_DETAIL = 'Translation was rejected because it could not preserve the original values.'

let setLang
function Harness() {
  setLang = useLanguage().setLanguage
  return <TranslatedBlock source={SOURCE} studyId="s1" feature="vision" contentType="visual_observations" />
}
const mount = () => render(<LanguageProvider><Harness /></LanguageProvider>)
const flush = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)) })
const choose = async (code) => { await act(async () => { setLang(code) }); await flush() }
const bodyText = () => document.body.textContent

let translateBehaviour
const postCalls = () => fetch.mock.calls.filter(([u]) => String(u).endsWith('/translate'))
const jsonRes = (status, body) => ({ ok: status < 400, status, json: async () => body })

beforeEach(() => {
  localStorage.clear()
  clearTranslationCache()
  setVersionCheckInterval(0)
  translateBehaviour = () => jsonRes(422, { detail: REJECT_DETAIL })
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url).endsWith('/translate/status')) return jsonRes(200, { available: true, pipeline_version: 'pv1' })
    if (String(url).endsWith('/translate')) return translateBehaviour()
    throw new Error('unexpected request: ' + url)
  })
})
afterEach(cleanup)

describe('HTTP 422 from /api/translate', () => {
  it('keeps the English original on screen and explains why', async () => {
    mount()
    await choose('ta')
    expect(postCalls().length).toBe(1)
    expect(bodyText()).toContain(SOURCE)                                    // original English still shown
    expect(bodyText()).toContain(DICTIONARIES.ta.translationRejected)       // "could not be verified" (Tamil UI)
    expect(bodyText()).not.toContain(DICTIONARIES.ta.machineTranslatedNote) // no "machine-translated" claim
  })

  it('does not cache the failed translation: selecting the language again retries the server', async () => {
    mount()
    await choose('ta')
    await choose('en')
    expect(bodyText()).toContain(SOURCE)
    await choose('ta')
    expect(postCalls().length).toBe(2)         // asked again, nothing was cached
    expect(bodyText()).toContain(SOURCE)
  })

  it('a later successful translation is shown and cached normally', async () => {
    mount()
    await choose('hi')                          // 422 first
    translateBehaviour = () => jsonRes(200, { translated_text: 'HINDI-OK', pipeline_version: 'pv1' })
    await choose('en')
    await choose('hi')
    expect(bodyText()).toContain('HINDI-OK')
    const n = postCalls().length
    await choose('en')
    await choose('hi')                          // served from cache now
    expect(postCalls().length).toBe(n)
  })

  it('a 503 (engine unavailable) shows the English text with the generic unavailable notice', async () => {
    translateBehaviour = () => jsonRes(503, { detail: 'Translation model is not available locally.' })
    mount()
    await choose('ml')
    expect(bodyText()).toContain(SOURCE)
    expect(bodyText()).toContain(DICTIONARIES.ml.translationUnavailable)
    expect(bodyText()).not.toContain(DICTIONARIES.ml.translationRejected)
  })

  it('every supported language falls back to English on 422', async () => {
    mount()
    for (const code of ['hi', 'ta', 'ml', 'te']) {
      await choose(code)
      expect(bodyText()).toContain(SOURCE)
      expect(bodyText()).toContain(DICTIONARIES[code].translationRejected)
    }
  })

  it('never calls an AI-generation endpoint', async () => {
    mount()
    for (const code of ['ta', 'en', 'hi']) await choose(code)
    const urls = fetch.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => /\/(chat|advice|vision)$/.test(u))).toBe(false)
  })
})
