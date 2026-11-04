import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({
  getProvenance: vi.fn(), getDemoCaseProvenance: vi.fn(), listReviews: vi.fn(), submitReview: vi.fn(),
  imageUrl: (x) => `/img/${x}`, translateText: vi.fn(), getTranslateStatus: vi.fn(),
}))

import * as api from '../lib/api'
import { LanguageProvider } from '../lib/LanguageContext'
import { clearTranslationCache } from '../lib/translationCache'
import EvidencePanel, { sectionTarget } from './EvidencePanel'
import LongitudinalView from './LongitudinalView'
import ReviewPanel from './ReviewPanel'

// recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }

const wrap = (ui) => render(<MemoryRouter><LanguageProvider>{ui}</LanguageProvider></MemoryRouter>)
const flush = () => act(async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 0)) })

beforeEach(() => { localStorage.clear(); clearTranslationCache(); vi.clearAllMocks() })
afterEach(cleanup)

const PROV = {
  study_id: 's1',
  study: { study_id: 's1', modality: 'X-ray', laterality: 'Left', age: 58, sex: 'Female', analysis_timestamp: '2025-04-15T08:50:00', source_filename: 'f.png', image_size_px: [1024, 1024], image_hash_prefix: 'abc123' },
  origin: { label: 'Pre-analysed reference case', algorithm: 'nnU-Net v2', segmentation: 'polygons', note: 'read from sidecar' },
  provenance: [
    { finding_id: 'meniscus:mean', category: 'quantitative_measurement', title: 'Mean medial meniscus thickness', value: 3.57, unit: 'mm', side: 'Left', section: 'meniscus-measurements', source: { algorithm: 'mean of stored thicknesses' }, limitations: ['Derived value'] },
    { finding_id: 'implant:primary', category: 'implant_sizing', title: 'Implant size recommendation', value: 'X 4 (Y)', section: 'implant-sizing', match_pct: 92.1, source: { algorithm: 'distance to centroids' }, limitations: ['no fit validation'] },
  ],
  unavailable: [{ field: 'image_view', reason: 'The imaging view is not recorded.' }],
  images: { original: 'orig.png' },
  ai_observations: [{ finding_id: 'ai:visual_scan:abc', title: 'AI Visual Scan observation', source: { provider: 'OpenRouter', model: 'm/x' }, generated_at: '2025-04-15T09:00:00+00:00', source_image: 'orig.png', verified: true, limitations: ['AI-generated text'], section: 'ai-visual-scan' }],
  notes: ['This panel shows data lineage only.'],
}

describe('EvidencePanel', () => {
  it('is lazy: nothing is fetched until it is opened', async () => {
    api.getProvenance.mockResolvedValue(PROV)
    wrap(<EvidencePanel studyId="s1" />)
    await flush()
    expect(api.getProvenance).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Clinical Evidence/ }))
    await flush()
    expect(api.getProvenance).toHaveBeenCalledTimes(1)
  })

  it('shows measurements with units and sources, AI separately with verification, and what is unavailable', async () => {
    api.getProvenance.mockResolvedValue(PROV)
    wrap(<EvidencePanel studyId="s1" defaultOpen />)
    await flush()
    expect(screen.getByText('Mean medial meniscus thickness')).toBeTruthy()
    expect(screen.getByText(/3\.57 mm/)).toBeTruthy()
    expect(screen.getByText(/92\.1% match/)).toBeTruthy()
    expect(screen.getByText('Server-verified')).toBeTruthy()
    expect(screen.getByText(/OpenRouter/)).toBeTruthy()
    expect(screen.getByText(/image_view/)).toBeTruthy()
    expect(screen.getAllByText(/not recorded/i).length).toBeGreaterThan(0)
    const text = document.body.textContent.toLowerCase()
    for (const banned of ['confidence score', 'heatmap', 'grad-cam', 'saliency']) expect(text).not.toContain(banned)
  })

  it('passes this session\'s AI items to the server for verification', async () => {
    api.getProvenance.mockResolvedValue(PROV)
    const items = [{ provenance: { kind: 'visual_scan', content_sha256: 'a'.repeat(64) }, text: 'obs', label: 'AI Visual Scan observation' }]
    wrap(<EvidencePanel studyId="s1" aiItems={items} defaultOpen />)
    await flush()
    expect(api.getProvenance).toHaveBeenCalledWith('s1', items)
  })

  it('reports an API error instead of inventing content', async () => {
    api.getProvenance.mockRejectedValue(new Error('Analysis not found.'))
    wrap(<EvidencePanel studyId="s1" defaultOpen />)
    await flush()
    expect(screen.getByText('Analysis not found.')).toBeTruthy()
  })

  it('click-through targets: AI/image scroll in place, measurements open their module page, demo has no routes', () => {
    expect(sectionTarget('ai-visual-scan', 's1')).toEqual({ scroll: 'ai-visual-scan' })
    expect(sectionTarget('meniscus-measurements', 's1')).toEqual({ route: '/oa/s1' })
    expect(sectionTarget('implant-sizing', 's1')).toEqual({ route: '/implant/s1' })
    expect(sectionTarget('implant-sizing', undefined)).toBeNull()
    expect(sectionTarget(undefined, 's1')).toBeNull()
  })

  it('demo mode uses the demo provenance endpoint and labels pre-written text as not model output', async () => {
    api.getDemoCaseProvenance.mockResolvedValue({ ...PROV, ai_observations: [] })
    const items = [{ provenance: { kind: 'visual_scan', content_sha256: 'b'.repeat(64), live: false }, text: 't', label: 'AI Visual Scan observation' }]
    wrap(<EvidencePanel demoSource="OAI_sample_03" aiItems={items} defaultOpen />)
    await flush()
    expect(api.getDemoCaseProvenance).toHaveBeenCalledWith('OAI_sample_03')
    expect(api.getProvenance).not.toHaveBeenCalled()
    expect(screen.getByText(/not model output/)).toBeTruthy()
  })
})

describe('ReviewPanel (real study)', () => {
  const LIST = {
    study_id: 's1', persistence: 'local_file', persistence_note: 'Stored in a local file on the backend server (development storage; not a durable clinical record).',
    findings: [{ finding_id: 'meniscus:mean', title: 'Mean medial meniscus thickness', kind: 'quantitative_measurement', value: 3.57, unit: 'mm', state: 'pending_review' }],
    events: [],
  }

  it('shows pending findings, the persistence backend and that the reviewer role is not verified', async () => {
    api.listReviews.mockResolvedValue(LIST)
    wrap(<ReviewPanel studyId="s1" />)
    await flush()
    expect(screen.getByTestId('state-meniscus:mean').textContent).toBe('Pending review')
    expect(screen.getByText(/local_file/)).toBeTruthy()
    expect(screen.getByText(/role is not verified/)).toBeTruthy()
    expect(screen.getByText(/No review decisions have been recorded yet/)).toBeTruthy()
  })

  it('submits a decision without any reviewer identity, with a request id and the status the user saw', async () => {
    api.listReviews.mockResolvedValue(LIST)
    api.submitReview.mockResolvedValue({ review: { review_id: 'r1' }, persistence: 'local_file' })
    wrap(<ReviewPanel studyId="s1" />)
    await flush()
    fireEvent.change(screen.getByLabelText(/Reviewer comment.*Mean medial/), { target: { value: 'looks right' } })
    fireEvent.click(screen.getByTestId('confirmed-meniscus:mean'))
    await flush()
    const payload = api.submitReview.mock.calls[0][0]
    expect(payload).toMatchObject({ study_id: 's1', finding_id: 'meniscus:mean', decision: 'confirmed', comment: 'looks right', expected_previous_state: 'pending_review' })
    expect(payload.request_id).toBeTruthy()
    for (const k of ['reviewer_id', 'user_id', 'reviewer']) expect(payload).not.toHaveProperty(k)
    expect(api.listReviews).toHaveBeenCalledTimes(2) // reloaded after saving
  })

  it('a conflict is surfaced and the current status is reloaded', async () => {
    api.listReviews.mockResolvedValue(LIST)
    api.submitReview.mockRejectedValue(new Error("This finding is now 'confirmed' (you saw 'pending_review')."))
    wrap(<ReviewPanel studyId="s1" />)
    await flush()
    fireEvent.click(screen.getByTestId('disagreed-meniscus:mean'))
    await flush()
    expect(screen.getByText(/This finding is now 'confirmed'/)).toBeTruthy()
    expect(api.listReviews).toHaveBeenCalledTimes(2)
  })

  it('AI observations from this session become reviewable and carry their provenance + text', async () => {
    api.listReviews.mockResolvedValue(LIST)
    api.submitReview.mockResolvedValue({ review: { review_id: 'r2' } })
    const prov = { kind: 'visual_scan', content_sha256: 'c'.repeat(64), signature: 'sig' }
    wrap(<ReviewPanel studyId="s1" aiItems={[{ provenance: prov, text: 'Joint space narrowed.', label: 'AI Visual Scan observation' }]} />)
    await flush()
    const id = `ai:visual_scan:${'c'.repeat(16)}`
    fireEvent.click(screen.getByTestId(`disagreed-${id}`))
    await flush()
    expect(api.submitReview.mock.calls[0][0]).toMatchObject({ finding_id: id, decision: 'disagreed', ai: { provenance: prov, text: 'Joint space narrowed.' } })
  })

  it('shows the audit history including previous and new status', async () => {
    api.listReviews.mockResolvedValue({ ...LIST, events: [
      { review_id: 'a', finding_id: 'meniscus:mean', finding_title: 'Mean', previous_state: 'pending_review', new_state: 'confirmed', created_at: '2025-04-15T10:00:00.123456+00:00', comment: 'ok' },
      { review_id: 'b', finding_id: 'meniscus:mean', finding_title: 'Mean', previous_state: 'confirmed', new_state: 'disagreed', created_at: '2025-04-15T11:00:00.123456+00:00', comment: '' },
    ] })
    wrap(<ReviewPanel studyId="s1" />)
    await flush()
    const items = within(screen.getByTestId('review-history')).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('Pending review')
    expect(items[1].textContent).toContain('Disagreed with observation')
  })
})

describe('ReviewPanel (demo)', () => {
  const demoFindings = [{ finding_id: 'meniscus:mean', title: 'Mean thickness', kind: 'quantitative_measurement', value: 3.5, unit: 'mm' }]

  it('never calls the review API, is labelled simulated, and records history locally', async () => {
    wrap(<ReviewPanel demo demoFindings={demoFindings} />)
    await flush()
    expect(screen.getByText(/simulated, kept only on this screen, not stored and not a clinical approval/)).toBeTruthy()
    fireEvent.click(screen.getByTestId('needs_further_review-meniscus:mean'))
    await flush()
    expect(api.submitReview).not.toHaveBeenCalled()
    expect(api.listReviews).not.toHaveBeenCalled()
    expect(screen.getByTestId('state-meniscus:mean').textContent).toBe('Needs further review')
    expect(screen.getByTestId('review-history').textContent).toContain('Simulated reviewer activity for demonstration')
  })
})

describe('LongitudinalView', () => {
  const study = (d) => ({ examined_at: d, side: 'Left', modality: 'X-ray', image: 'a.png', image_view: null })
  const comparison = {
    previous: study('2023-04-12T09:30:00'), current: study('2025-04-15T08:50:00'),
    comparability: { comparable: true, blocking_reasons: [], warnings: ['The imaging view is not recorded for either study.'] },
    measurements: [
      { id: 'meniscus:mean', label: 'Meniscus thickness - mean', unit: 'mm', previous: 3.8666666, current: 3.5666666, difference: -0.3, percentage_difference: -7.758620689, available: true },
      { id: 'bone:tibial_slope_deg', label: 'Tibial slope', unit: 'deg', previous: null, current: 8.1, difference: null, percentage_difference: null, available: false },
    ],
  }

  it('shows values, differences and percentages (rounded only for display), missing values and warnings', () => {
    wrap(<LongitudinalView comparison={comparison} />)
    const table = screen.getByTestId('comparison-table')
    expect(within(table).getByText('3.87 mm')).toBeTruthy()
    expect(within(table).getByText('-0.30 mm')).toBeTruthy()
    expect(within(table).getByText('-7.8%')).toBeTruthy()
    expect(within(table).getByText('missing')).toBeTruthy()
    expect(screen.getByText(/imaging view is not recorded/)).toBeTruthy()
    expect(screen.getByText('Observed measurement difference between the selected examinations.')).toBeTruthy()
  })

  it('never states progression, improvement or deterioration', () => {
    wrap(<LongitudinalView comparison={comparison} />)
    const text = document.body.textContent.toLowerCase()
    for (const w of ['progress', 'improv', 'worsen', 'deteriorat']) expect(text).not.toContain(w)
  })

  it('a rejected comparison shows the reasons and no measurement table', () => {
    const bad = { ...comparison, comparability: { comparable: false, blocking_reasons: ['Anatomical side differs (Left vs Right).'], warnings: [] }, measurements: [] }
    wrap(<LongitudinalView comparison={bad} />)
    expect(screen.getByRole('alert').textContent).toContain('Anatomical side differs')
    expect(screen.queryByTestId('comparison-table')).toBeNull()
  })

  it('images keep their aspect ratio (auto height, contain) and open full size', () => {
    wrap(<LongitudinalView comparison={comparison} />)
    const img = screen.getAllByAltText(/examination/)[0]
    expect(img.className).toContain('h-auto')
    expect(img.className).toContain('object-contain')
    expect(img.closest('a').getAttribute('target')).toBe('_blank')
  })

  it('trend chart only with three or more values; otherwise states direct comparison only', () => {
    const two = { measurement: { label: 'Mean', unit: 'mm' }, points: [{ examined_at: '2023-01-01T00:00:00', value: 4 }, { examined_at: '2024-01-01T00:00:00', value: 3.6 }], trend_available: false, note: 'n' }
    const { unmount } = wrap(<LongitudinalView series={two} />)
    expect(screen.queryByTestId('trend-chart')).toBeNull()
    expect(screen.getByText(/fewer than three comparable examinations/)).toBeTruthy()
    unmount()
    const three = { ...two, points: [...two.points, { examined_at: '2025-01-01T00:00:00', value: 3.2 }], trend_available: true }
    wrap(<LongitudinalView series={three} />)
    expect(screen.getByTestId('trend-chart')).toBeTruthy()
  })

  it('timeline marks the current study and flags non-comparable ones', () => {
    const timeline = { identity_basis: 'identity note', studies: [
      { study_id: 'a', examined_at: '2023-01-01T00:00:00', side: 'Left', modality: 'X-ray', is_current: false, comparable_with_current: false, reasons: ['side'] },
      { study_id: 'b', examined_at: '2024-01-01T00:00:00', side: 'Left', modality: 'X-ray', is_current: true },
    ] }
    wrap(<LongitudinalView timeline={timeline} />)
    const items = within(screen.getByTestId('timeline')).getAllByRole('listitem')
    expect(items[0].textContent).toContain('These studies cannot be compared')
    expect(items[1].textContent).toContain('Current study')
  })
})
