/**
 * Guided-demo stage model: pure functions, no React, so navigation rules are unit-testable.
 * Nothing here is persisted; progress lives in component state and ends when the demo is exited.
 */
export const STAGES = [
  { id: 'overview', titleKey: 'demoStageOverview' },
  { id: 'image', titleKey: 'demoStageImage' },
  { id: 'ai', titleKey: 'demoStageAi' },
  { id: 'quant', titleKey: 'demoStageQuant' },
  { id: 'implant', titleKey: 'demoStageImplant' },
  { id: 'language', titleKey: 'demoStageLanguage' },
  { id: 'provenance', titleKey: 'demoStageProvenance' },
  { id: 'longitudinal', titleKey: 'demoStageLongitudinal' },
  { id: 'review', titleKey: 'demoStageReview' },
  { id: 'report', titleKey: 'demoStageReport' },
]

export const MODE_LIVE = 'live'
export const MODE_CACHED = 'cached'

export const initialDemoState = () => ({ index: 0, visited: [0], mode: MODE_CACHED })

const clamp = (i) => Math.max(0, Math.min(STAGES.length - 1, i))

export function goTo(state, index) {
  const i = clamp(index)
  return { ...state, index: i, visited: state.visited.includes(i) ? state.visited : [...state.visited, i] }
}
export const next = (state) => goTo(state, state.index + 1)
export const prev = (state) => goTo(state, state.index - 1)
export const restart = (state) => ({ ...initialDemoState(), mode: state.mode })
export const setMode = (state, mode) =>
  mode === MODE_LIVE || mode === MODE_CACHED ? { ...state, mode } : state

export const isFirst = (state) => state.index === 0
export const isLast = (state) => state.index === STAGES.length - 1
/** A stage counts as completed once the user has moved past it. */
export const completed = (state) => STAGES.map((_, i) => state.visited.includes(i) && i < Math.max(...state.visited))
export const progressPct = (state) => Math.round(((state.index + 1) / STAGES.length) * 100)

/**
 * Where an AI result came from. Live and cached results are never mixed silently:
 * a failed live call stays an error, it does not become cached text.
 */
export function describeAiSource(result) {
  if (!result) return { kind: 'none' }
  if (result.mode === MODE_CACHED) return { kind: 'cached', labelKey: 'demoCachedLabel' }
  if (result.mode === MODE_LIVE) return { kind: 'live', labelKey: 'demoLiveLabel' }
  return { kind: 'none' }
}
