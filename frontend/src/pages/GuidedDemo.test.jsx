import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({
  listDemoCases: vi.fn(), getDemoCase: vi.fn(), getDemoCachedAi: vi.fn(), getDemoCaseProvenance: vi.fn(),
  getDemoLongitudinal: vi.fn(), listDemoSeries: vi.fn(), getVisionObservations: vi.fn(), downloadReport: vi.fn(), sampleImageUrl: (p) => p,
  translateText: vi.fn(), getTranslateStatus: vi.fn(), imageUrl: (x) => `/img/${x}`, variantKey: () => 'femur-meniscus-tibia',
}))
// Meniscus/implant tables, quality card and viewer are the REAL components fed a real backend record
// (a stub here once hid a crash). Only the panels with their own test files are stubbed.
vi.mock('../components/EvidencePanel', () => ({
  default: ({ demoSource, aiItems }) => <div data-testid="evidence" data-source={demoSource} data-ai={aiItems.length} />,
}))
vi.mock('../components/ReviewPanel', () => ({
  default: ({ demo, demoFindings }) => <div data-testid="review" data-demo={String(demo)} data-n={demoFindings.length} />,
}))
vi.mock('../components/LongitudinalView', () => ({
  default: ({ demoLabel }) => <div data-testid="longitudinal">{demoLabel}</div>,
}))

import * as api from '../lib/api'
import { DICTIONARIES } from '../lib/i18n'
import { LanguageProvider } from '../lib/LanguageContext'
import { clearTranslationCache, setVersionCheckInterval } from '../lib/translationCache'
import GuidedDemo from './GuidedDemo'
import fixture from '../test/demoCaseFixture.json'

const RECORD = fixture
const CACHED = { mode: 'cached', valid: true, visual_scan: 'Pre-written observation text.', provenance: { live: false, content_sha256: 'a'.repeat(64) } }

const mount = () => render(<MemoryRouter><LanguageProvider><GuidedDemo /></LanguageProvider></MemoryRouter>)
const flush = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)) })
const click = async (el) => { fireEvent.click(el); await flush() }
const dict = () => DICTIONARIES[localStorage.getItem('knee-ai-language')] || DICTIONARIES.en
const next = () => click(screen.getByRole('button', { name: dict().demoNext }))
const back = () => click(screen.getByRole('button', { name: dict().demoPrev }))
const goto = async (n) => { for (let i = 0; i < n; i++) await next() }
const text = () => document.body.textContent

beforeEach(() => {
  localStorage.clear(); clearTranslationCache(); setVersionCheckInterval(0); vi.clearAllMocks()
  api.listDemoCases.mockResolvedValue({ items: [{ source: 'OAI_sample_03', label: 'OAI_sample_03 - KL 2 / Moderate OA' }, { source: 'OAI_sample_01', label: 'OAI_sample_01 - KL 0 / Normal' }] })
  api.getDemoCase.mockResolvedValue(RECORD)
  api.getDemoCachedAi.mockResolvedValue(CACHED)
  api.getDemoCaseProvenance.mockResolvedValue({ provenance: [{ finding_id: 'a', title: 'A', category: 'quantitative_measurement' }, { finding_id: 'b', title: 'B', category: 'quantitative_measurement' }] })
  api.getDemoLongitudinal.mockResolvedValue({ label: 'SYNTHETIC DEMONSTRATION DATA', comparison: {}, series: {}, timeline: {}, rejected_example: {}, image_url: '/api/samples/x/image' })
  api.getTranslateStatus.mockResolvedValue({ pipeline_version: 'pv1' })
  api.listDemoSeries.mockResolvedValue({ items: [{ series_id: 'DEMO-SERIES-001', label: 'Series one' }, { series_id: 'SYNTH-KNEE-006', label: 'Synthetic patient SYNTH-KNEE-006' }] })
})
afterEach(cleanup)

describe('Guided Demo', () => {
  it('opens on stage 1 of 10 with the synthetic-data banner and fires no AI request', async () => {
    mount()
    await flush()
    expect(text()).toContain('Stage 1 of 10')
    expect(screen.getByRole('status').textContent).toContain('Synthetic demonstration data')
    expect(text()).toContain('OAI_sample_03 (synthetic demo case)')
    expect(api.getVisionObservations).not.toHaveBeenCalled()
    expect(api.getDemoCachedAi).not.toHaveBeenCalled()
    expect(api.getDemoLongitudinal).not.toHaveBeenCalled()
  })

  it('walks all ten stages with Next/Back and each stage shows its own content', async () => {
    mount()
    await flush()
    expect(screen.getByRole('button', { name: 'Back' }).disabled).toBe(true)
    await next(); expect(screen.getByText(DICTIONARIES.en.visualization)).toBeTruthy()
    await next(); expect(screen.getByRole('button', { name: 'Show pre-generated result' })).toBeTruthy()
    await next()
    expect(text()).toContain('Anterior Horn')
    expect(text()).toContain(String(RECORD.meniscus.assessment.mean_thickness_mm))
    expect(text()).toContain(RECORD.meniscus.assessment.classification)
    await next()
    expect(text()).toContain(RECORD.implant.primary.system)
    await next(); expect(text()).toContain('No AI text yet')
    await next(); expect(screen.getByTestId('evidence').dataset.source).toBe('OAI_sample_03')
    await next(); expect(screen.getByTestId('longitudinal').textContent).toContain('SYNTHETIC')
    await next(); expect(screen.getByTestId('review').dataset.demo).toBe('true')
    await next(); expect(text()).toContain('Generate PDF report')
    expect(text()).toContain('Stage 10 of 10')
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull()
    await back(); expect(text()).toContain('Stage 9 of 10')
  })

  it('stage chips jump directly and Restart returns to stage 1', async () => {
    mount()
    await flush()
    await click(screen.getByRole('button', { name: /7\. Provenance/ }))
    expect(text()).toContain('Stage 7 of 10')
    await click(screen.getByRole('button', { name: 'Restart' }))
    expect(text()).toContain('Stage 1 of 10')
  })

  it('has a clear exit to the dashboard', async () => {
    mount()
    await flush()
    expect(screen.getByRole('link', { name: 'Exit demo' }).getAttribute('href')).toBe('/')
  })

  it('pre-generated mode: shows the cached text with its own label and never calls the live model', async () => {
    mount()
    await flush()
    await goto(2)
    await click(screen.getByRole('button', { name: 'Show pre-generated result' }))
    expect(screen.getByTestId('ai-source-label').textContent).toBe('Pre-generated synthetic demonstration result.')
    expect(text()).toContain('Pre-written observation text.')
    expect(api.getVisionObservations).not.toHaveBeenCalled()
  })

  it('live mode: calls the real vision endpoint on demand and labels the result as live', async () => {
    api.getVisionObservations.mockResolvedValue({ observations: 'Live model text.', provenance: { kind: 'visual_scan', content_sha256: 'b'.repeat(64) } })
    mount()
    await flush()
    await goto(2)
    await click(screen.getByRole('button', { name: 'Live AI' }))
    expect(api.getVisionObservations).not.toHaveBeenCalled() // choosing the mode costs nothing
    await click(screen.getByRole('button', { name: 'Run live AI Visual Scan' }))
    expect(api.getVisionObservations).toHaveBeenCalledTimes(1)
    expect(api.getVisionObservations.mock.calls[0][0]).toBe(RECORD.images.variants.none)
    expect(screen.getByTestId('ai-source-label').textContent).toBe('Generated live by the AI model just now.')
    expect(text()).toContain('Live model text.')
  })

  it('a failed live call stays an error: no silent fallback to cached text', async () => {
    api.getVisionObservations.mockRejectedValue(new Error('The AI provider\'s rate limit was reached.'))
    mount()
    await flush()
    await goto(2)
    await click(screen.getByRole('button', { name: 'Live AI' }))
    await click(screen.getByRole('button', { name: 'Run live AI Visual Scan' }))
    expect(text()).toContain("rate limit was reached")
    expect(text()).not.toContain('Pre-written observation text.')
    expect(api.getDemoCachedAi).not.toHaveBeenCalled()
    expect(screen.queryByTestId('ai-source-label')).toBeNull()
    await next() // the demo carries on through unaffected stages
    expect(text()).toContain('Anterior Horn')
  })

  it('an invalidated pre-generated result is refused with the reason', async () => {
    api.getDemoCachedAi.mockResolvedValue({ mode: 'cached', valid: false, reason: 'The source image changed after this result was prepared.' })
    mount()
    await flush()
    await goto(2)
    await click(screen.getByRole('button', { name: 'Show pre-generated result' }))
    expect(text()).toContain('source image changed')
    expect(text()).not.toContain('Pre-written observation text.')
  })

  it('language stage: switching language never triggers an AI request; translation failure keeps English', async () => {
    localStorage.setItem('knee-ai-language', 'ta')
    api.translateText.mockRejectedValue(Object.assign(new Error('Translation model is not available locally.'), { status: 503 }))
    mount()
    await flush()
    await goto(2)
    await click(screen.getByRole('button', { name: DICTIONARIES.en.demoLoadCached }))
    await goto(3) // -> language stage
    expect(text()).toContain('Pre-written observation text.') // English stays visible
    expect(text()).toContain(DICTIONARIES.ta.translationUnavailable)
    expect(api.getVisionObservations).not.toHaveBeenCalled()
  })

  it('provenance stage receives the AI item from this demo run; review stage is demo-only', async () => {
    mount()
    await flush()
    await goto(2)
    await click(screen.getByRole('button', { name: 'Show pre-generated result' }))
    await goto(4)
    expect(screen.getByTestId('evidence').dataset.ai).toBe('1')
    await goto(2)
    expect(screen.getByTestId('review').dataset.demo).toBe('true')
    expect(Number(screen.getByTestId('review').dataset.n)).toBe(2)
  })

  it('longitudinal stage failure is shown and the demo can continue', async () => {
    api.getDemoLongitudinal.mockRejectedValue(new Error('Demo series unavailable'))
    mount()
    await flush()
    await goto(7)
    expect(text()).toContain('Demo series unavailable')
    await next()
    expect(screen.getByTestId('review')).toBeTruthy()
  })

  it('report stage uses the existing PDF service with the demo record, and reports failures', async () => {
    api.downloadReport.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('PDF generation failed'))
    mount()
    await flush()
    await goto(9)
    await click(screen.getByRole('button', { name: 'Generate PDF report' }))
    expect(api.downloadReport).toHaveBeenCalledWith(RECORD)
    expect(text()).toContain('Report generated with the existing PDF service.')
    await click(screen.getByRole('button', { name: 'Generate PDF report' }))
    expect(text()).toContain('PDF generation failed')
  })

  it('every stage renders real data without crashing, even for a case with missing optional data', async () => {
    api.getDemoCase.mockResolvedValue({ ...RECORD, meniscus: { ...RECORD.meniscus, population_comparison: undefined }, implant: {}, quality: RECORD.quality })
    mount()
    await flush()
    await goto(3)
    expect(text()).toContain('Population comparison is not available')
    await next()
    expect(text()).toContain('No implant sizing is available')
  })

  it('a crash inside one stage shows an error for that stage only and the demo continues', async () => {
    api.getDemoCase.mockResolvedValue({ ...RECORD, meniscus: { ...RECORD.meniscus, population_comparison: [{ location: 'x', label: 'x' }] } }) // malformed rows
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mount()
    await flush()
    await goto(3)
    expect(text()).toContain(DICTIONARIES.en.demoStageUnavailable)
    expect(screen.getByRole('button', { name: 'Next' })).toBeTruthy() // page is not blank
    await next()
    expect(text()).toContain(RECORD.implant.primary.system)
    spy.mockRestore()
  })

  it('longitudinal stage lets the evaluator switch to the SYNTH-KNEE-006 series', async () => {
    mount()
    await flush()
    await goto(7)
    expect(api.getDemoLongitudinal).toHaveBeenLastCalledWith('DEMO-SERIES-001')
    fireEvent.change(screen.getByLabelText(DICTIONARIES.en.demoSeries), { target: { value: 'SYNTH-KNEE-006' } })
    await flush()
    expect(api.getDemoLongitudinal).toHaveBeenLastCalledWith('SYNTH-KNEE-006')
  })

  it('a case that cannot be prepared shows an error instead of a blank demo', async () => {
    api.getDemoCase.mockRejectedValue(new Error('The demo case could not be prepared (image processing failed).'))
    mount()
    await flush()
    expect(text()).toContain('could not be prepared')
  })
})
