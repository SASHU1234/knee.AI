import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  translateText: vi.fn(),
  sendChatMessage: vi.fn(),
  getFoodAdvice: vi.fn(),
  getVisionObservations: vi.fn(),
  getTranslateStatus: vi.fn(),
}))

import * as api from './api'
import { LanguageProvider, useLanguage } from './LanguageContext'
import { clearTranslationCache, getPipelineVersion, setVersionCheckInterval } from './translationCache'
import { useTranslatedText } from './useTranslatedText'

const SOURCE = 'Possible narrowing of 2.4 mm. No obvious swelling.'
const FAKE = { hi: 'HI-text', ta: 'TA-text', ml: 'ML-text', te: 'TE-text' }

let setLang
function Probe({ source = SOURCE, feature = 'vision' }) {
  const { setLanguage } = useLanguage()
  setLang = setLanguage
  const { text, loading, error, translated } = useTranslatedText(source, { studyId: 's1', feature, contentType: 'visual_observations' })
  return (
    <div>
      <span data-testid="text">{text}</span>
      <span data-testid="state">{loading ? 'loading' : error ? 'error' : translated ? 'translated' : 'original'}</span>
      <button data-testid="unrelated" onClick={() => { Probe.clicked = (Probe.clicked || 0) + 1 }}>x</button>
    </div>
  )
}
const mount = (props) => render(<LanguageProvider><Probe {...props} /></LanguageProvider>)
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await new Promise((r) => setTimeout(r, 0)) })
const choose = async (code) => { await act(async () => { setLang(code) }); await flush() }
const text = () => screen.getByTestId('text').textContent
const state = () => screen.getByTestId('state').textContent

beforeEach(() => {
  localStorage.clear()
  clearTranslationCache()
  vi.clearAllMocks()
  setVersionCheckInterval(0)
  api.getTranslateStatus.mockResolvedValue({ pipeline_version: 'tv1' })
  api.translateText.mockImplementation(async (_t, lang) => ({ translated_text: FAKE[lang], pipeline_version: 'tv1' }))
})
afterEach(cleanup)

describe('useTranslatedText', () => {
  it('English shows the original and never calls the translate endpoint', async () => {
    mount()
    await flush()
    expect(text()).toBe(SOURCE)
    expect(api.translateText).not.toHaveBeenCalled()
  })

  it.each(['hi', 'ta', 'ml', 'te'])('switching to %s translates existing content', async (code) => {
    mount()
    await choose(code)
    expect(text()).toBe(FAKE[code])
    expect(state()).toBe('translated')
    expect(api.translateText).toHaveBeenCalledWith(SOURCE, code, 'visual_observations')
  })

  it('switching back to English restores the exact original with no request', async () => {
    mount()
    await choose('ta')
    const calls = api.translateText.mock.calls.length
    await choose('en')
    expect(text()).toBe(SOURCE)
    expect(api.translateText.mock.calls.length).toBe(calls)
  })

  it('reuses cached translations when switching between languages', async () => {
    mount()
    await choose('ta')
    await choose('hi')
    await choose('ta')
    await choose('hi')
    expect(api.translateText).toHaveBeenCalledTimes(2)
    expect(text()).toBe(FAKE.hi)
  })

  it('shows English with a loading flag while translating and does not block the UI', async () => {
    let release
    api.translateText.mockImplementation(() => new Promise((r) => { release = () => r({ translated_text: FAKE.ta }) }))
    mount()
    await choose('ta')
    expect(state()).toBe('loading')
    expect(text()).toBe(SOURCE)
    screen.getByTestId('unrelated').click() // still interactive
    expect(Probe.clicked).toBe(1)
    await act(async () => { release() }); await flush()
    expect(text()).toBe(FAKE.ta)
  })

  it('rapid switching never shows a stale translation', async () => {
    const pending = {}
    api.translateText.mockImplementation((_t, lang) => new Promise((r) => { pending[lang] = () => r({ translated_text: FAKE[lang] }) }))
    mount()
    await choose('ta')           // ta request in flight
    await choose('hi')           // user moves on before ta returns
    await act(async () => { pending.ta?.() }); await flush()
    expect(text()).not.toBe(FAKE.ta)
    await act(async () => { pending.hi?.() }); await flush()
    expect(text()).toBe(FAKE.hi)
  })

  it('does not cache failures and falls back to English', async () => {
    api.translateText.mockRejectedValueOnce(new Error('Translation unavailable'))
    mount()
    await choose('ta')
    expect(state()).toBe('error')
    expect(text()).toBe(SOURCE)
    await choose('en')
    await choose('ta') // retried, not served from cache
    expect(api.translateText).toHaveBeenCalledTimes(2)
    expect(text()).toBe(FAKE.ta)
  })

  it('a changed English source is re-translated, not served stale', async () => {
    const { rerender } = mount()
    await choose('ta')
    api.translateText.mockImplementation(async () => ({ translated_text: 'NEW-TA' }))
    rerender(<LanguageProvider><Probe source="Different advice." /></LanguageProvider>)
    await flush()
    expect(text()).toBe('NEW-TA')
  })

  it('language switching sends zero OpenRouter-backed requests', async () => {
    mount()
    for (const c of ['ta', 'hi', 'ml', 'te', 'en']) await choose(c)
    expect(api.sendChatMessage).not.toHaveBeenCalled()
    expect(api.getFoodAdvice).not.toHaveBeenCalled()
    expect(api.getVisionObservations).not.toHaveBeenCalled()
  })

  it('never mutates the source string', async () => {
    const src = SOURCE
    mount({ source: src })
    await choose('ta')
    expect(src).toBe(SOURCE)
  })

  it('discards translations made under an older terminology dictionary', async () => {
    mount()
    await choose('ta')                       // cached under glossary tv1
    expect(getPipelineVersion()).toBe('tv1')
    expect(api.translateText).toHaveBeenCalledTimes(1)
    api.translateText.mockImplementation(async (_t, lang) => ({ translated_text: 'NEW-' + FAKE[lang], pipeline_version: 'tv2' }))
    await choose('hi')                       // server now reports tv2
    expect(getPipelineVersion()).toBe('tv2')
    expect(text()).toBe('NEW-' + FAKE.hi)
    await choose('ta')                       // old tv1 Tamil must NOT be reused
    expect(api.translateText).toHaveBeenCalledTimes(3)
    expect(text()).toBe('NEW-' + FAKE.ta)
  })

  it('keeps reusing translations while the terminology version is unchanged', async () => {
    mount()
    await choose('ta'); await choose('hi'); await choose('ta')
    expect(api.translateText).toHaveBeenCalledTimes(2)
  })

  it('English original stays untouched across a terminology refresh', async () => {
    mount()
    await choose('ta')
    api.translateText.mockImplementation(async () => ({ translated_text: 'X', pipeline_version: 'tv9' }))
    await choose('hi')
    await choose('en')
    expect(text()).toBe(SOURCE)
  })

  it('server upgrade seen via /translate/status: older cached translations are not reused', async () => {
    mount()
    await choose('ta')                          // cached under pipeline tv1
    expect(api.translateText).toHaveBeenCalledTimes(1)
    // backend restarted with a new pipeline (new dictionary / validation rules)
    api.getTranslateStatus.mockResolvedValue({ pipeline_version: 'tv2' })
    api.translateText.mockImplementation(async (_t, lang) => ({ translated_text: 'V2-' + FAKE[lang], pipeline_version: 'tv2' }))
    await choose('en')
    await choose('ta')                          // language change re-checks the version; tv1 entry is dead
    expect(getPipelineVersion()).toBe('tv2')
    expect(text()).toBe('V2-' + FAKE.ta)
    expect(api.translateText).toHaveBeenCalledTimes(2)
  })

  it('the old terminology_version field is still honoured', async () => {
    api.getTranslateStatus.mockResolvedValue({ terminology_version: 'legacy1' })
    api.translateText.mockImplementation(async (_t, lang) => ({ translated_text: FAKE[lang], terminology_version: 'legacy1' }))
    mount()
    await choose('ta')
    expect(getPipelineVersion()).toBe('legacy1')
  })
})
