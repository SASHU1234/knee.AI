/**
 * Real backend output (dumped from the live demo endpoints) rendered by the REAL components.
 * Guards against hand-written test data drifting from what the API actually returns.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({
  getDemoCaseProvenance: vi.fn(), getProvenance: vi.fn(), imageUrl: (x) => `/img/${x}`, sampleImageUrl: (p) => p,
}))
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }

import * as api from '../lib/api'
import { LanguageProvider } from '../lib/LanguageContext'
import EvidencePanel from '../components/EvidencePanel'
import LongitudinalView from '../components/LongitudinalView'
import longi from './demoLongitudinalFixture.json'
import prov from './demoProvenanceFixture.json'
import synth from './synthKnee006Fixture.json'

const flush = () => act(async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 0)) })
afterEach(cleanup)

describe('real backend shapes', () => {
  it('longitudinal view renders the real demo comparison, timeline, trend and rejected example', async () => {
    render(<MemoryRouter><LanguageProvider>
      <LongitudinalView comparison={longi.comparison} series={longi.series} timeline={longi.timeline}
                        imageOverride={longi.image_url} demoLabel={longi.label} rejectedExample={longi.rejected_example} />
    </LanguageProvider></MemoryRouter>)
    await flush()
    expect(screen.getByTestId('comparison-table').textContent).toContain('Meniscus thickness - mean')
    expect(screen.getByTestId('trend-chart')).toBeTruthy()
    expect(screen.getByTestId('timeline').querySelectorAll('li')).toHaveLength(3)
    expect(document.body.textContent).toContain('Anatomical side differs')
    expect(document.body.textContent).toContain('SYNTHETIC')
  })

  it('evidence panel renders the real provenance payload', async () => {
    api.getDemoCaseProvenance.mockResolvedValue(prov)
    render(<MemoryRouter><LanguageProvider><EvidencePanel demoSource="OAI_sample_03" defaultOpen /></LanguageProvider></MemoryRouter>)
    await flush()
    expect(document.body.textContent).toContain('Anterior Horn')
    expect(document.body.textContent).toContain('Pre-analysed reference case')
    expect(document.body.textContent).toContain('image_view')
  })

  it('SYNTH-KNEE-006: two different images side by side, real differences, synthetic label, no trend, rejected namesake', async () => {
    render(<MemoryRouter><LanguageProvider>
      <LongitudinalView comparison={synth.comparison} series={synth.series} timeline={synth.timeline} notes={synth.notes}
                        demoLabel={synth.label} rejectedExample={synth.rejected_example} />
    </LanguageProvider></MemoryRouter>)
    await flush()
    const imgs = screen.getAllByAltText(/examination/)
    expect(imgs).toHaveLength(2)
    expect(imgs[0].getAttribute('src')).not.toBe(imgs[1].getAttribute('src'))
    expect(imgs[0].getAttribute('src')).toContain('baseline_right_knee_standing.webp')
    expect(imgs[1].getAttribute('src')).toContain('followup_bilateral_ap_standing.png')
    const text = document.body.textContent
    expect(text).toContain('SYNTHETIC DEMONSTRATION DATA')
    expect(text).toContain('SYNTH-KNEE-006')
    expect(text).toContain('AP standing')
    expect(text).toContain('-0.47 mm') // mean thickness difference, computed by the backend from stored values
    expect(text).toContain('Right')
    expect(text).toContain('deterministic simulation')
    expect(screen.queryByTestId('trend-chart')).toBeNull()
    expect(text).toContain('Direct comparison only')
    expect(text).toContain('explicit patient ID')
    expect(screen.getByTestId('case-notes').textContent).toContain('progression')
    for (const w of ['progressed', 'deteriorat', 'worsened', 'improved']) expect(text.toLowerCase()).not.toContain(w)
  })
})
