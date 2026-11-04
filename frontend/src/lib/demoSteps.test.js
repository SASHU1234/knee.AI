import { describe, expect, it } from 'vitest'
import {
  MODE_CACHED, MODE_LIVE, STAGES, completed, describeAiSource, goTo, initialDemoState, isFirst, isLast, next, prev,
  progressPct, restart, setMode,
} from './demoSteps'
import { chartRows, fmtDate, fmtPct, fmtSigned, fmtValue } from './longitudinalFormat'

describe('guided demo stage model', () => {
  it('has the ten required stages in order', () => {
    expect(STAGES.map((s) => s.id)).toEqual(['overview', 'image', 'ai', 'quant', 'implant', 'language', 'provenance', 'longitudinal', 'review', 'report'])
  })

  it('starts at stage 1 in pre-generated mode and never auto-selects live AI', () => {
    const s = initialDemoState()
    expect(s.index).toBe(0)
    expect(s.mode).toBe(MODE_CACHED)
    expect(isFirst(s)).toBe(true)
  })

  it('next/previous navigate and clamp at both ends', () => {
    let s = initialDemoState()
    expect(prev(s).index).toBe(0)
    for (let i = 0; i < 20; i++) s = next(s)
    expect(s.index).toBe(STAGES.length - 1)
    expect(isLast(s)).toBe(true)
    expect(prev(s).index).toBe(STAGES.length - 2)
  })

  it('records visited stages once and marks passed stages completed', () => {
    let s = initialDemoState()
    s = next(next(s))
    s = prev(s)
    expect(s.visited).toEqual([0, 1, 2])
    expect(completed(s).slice(0, 3)).toEqual([true, true, false])
  })

  it('goTo jumps and clamps invalid indexes', () => {
    expect(goTo(initialDemoState(), 7).index).toBe(7)
    expect(goTo(initialDemoState(), 99).index).toBe(STAGES.length - 1)
    expect(goTo(initialDemoState(), -5).index).toBe(0)
  })

  it('restart returns to stage 1 and clears progress but keeps the chosen mode', () => {
    let s = setMode(next(next(initialDemoState())), MODE_LIVE)
    s = restart(s)
    expect(s.index).toBe(0)
    expect(s.visited).toEqual([0])
    expect(s.mode).toBe(MODE_LIVE)
  })

  it('progress is proportional and ends at 100', () => {
    expect(progressPct(initialDemoState())).toBe(10)
    expect(progressPct(goTo(initialDemoState(), STAGES.length - 1))).toBe(100)
  })

  it('rejects an unknown mode', () => {
    expect(setMode(initialDemoState(), 'magic').mode).toBe(MODE_CACHED)
  })

  it('live and cached results are described distinctly and never conflated', () => {
    expect(describeAiSource({ mode: MODE_LIVE }).kind).toBe('live')
    expect(describeAiSource({ mode: MODE_CACHED }).kind).toBe('cached')
    expect(describeAiSource({ mode: MODE_CACHED }).labelKey).toBe('demoCachedLabel')
    expect(describeAiSource(null).kind).toBe('none')
  })
})

describe('longitudinal number formatting (presentation only)', () => {
  it('rounds for display but never produces -0.00', () => {
    expect(fmtSigned(-0.001, 'mm')).toBe('0.00 mm')
    expect(fmtSigned(-0.4, 'mm')).toBe('-0.40 mm')
    expect(fmtSigned(0.456, 'mm')).toBe('+0.46 mm')
    expect(fmtPct(-10)).toBe('-10.0%')
    expect(fmtPct(0.01)).toBe('0.0%')
  })

  it('missing values stay missing', () => {
    expect(fmtValue(null, 'mm')).toBeNull()
    expect(fmtSigned(undefined)).toBeNull()
    expect(fmtPct(null)).toBeNull()
  })

  it('chart rows keep real dates and leave gaps as null (no interpolation)', () => {
    const rows = chartRows([
      { examined_at: '2023-01-10T10:00:00', value: 4.0, study_id: 'a' },
      { examined_at: '2024-01-10T10:00:00', value: null, study_id: 'b' },
      { examined_at: '2025-01-10T10:00:00', value: 3.2, study_id: 'c' },
    ])
    expect(rows.map((r) => r.value)).toEqual([4.0, null, 3.2])
    expect(rows.map((r) => r.label)).toEqual(['2023-01-10', '2024-01-10', '2025-01-10'])
    expect(rows[0].t).toBeLessThan(rows[2].t)
    expect(fmtDate(null)).toBeNull()
  })
})
