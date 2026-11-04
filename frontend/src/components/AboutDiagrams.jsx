import { useLanguage } from '../lib/LanguageContext'

const BORDER = { border: '2px solid #2D2016' }

/** A labelled box. tone: hosted (hosted AI), local (runs on the backend machine), data, neutral. */
function Box({ title, sub, tone = 'neutral', className = '' }) {
  const bg = { hosted: 'bg-warn-light', local: 'bg-ok-light', data: 'bg-accent-light', neutral: 'bg-surface' }[tone]
  return (
    <div className={`rounded-[10px] ${bg} px-3 py-2.5 text-center ${className}`} style={BORDER}>
      <p className="text-[12px] font-display font-bold text-navy leading-tight">{title}</p>
      {sub && <p className="text-[10.5px] font-display text-muted mt-0.5 leading-snug">{sub}</p>}
    </div>
  )
}

const Arrow = ({ vertical = false }) => (
  <span aria-hidden="true" className={`text-navy/60 font-display text-[16px] leading-none shrink-0 ${vertical ? 'rotate-90' : ''}`}>→</span>
)

/** Frontend → FastAPI → (OpenRouter → model | local services | Supabase). Built from the verified architecture. */
export function ArchDiagram() {
  const { t } = useLanguage()
  return (
    <div className="space-y-3" role="img" aria-label={`${t('abDiagBrowser')} → ${t('abDiagApi')} → ${t('abDiagOpenRouter')}, ${t('abDiagLocal')}, ${t('abDiagSupabase')}`} data-testid="arch-diagram">
      <div className="flex flex-wrap items-center justify-center gap-2.5">
        <Box title={t('abDiagBrowser')} sub="Vite · Router · i18n" />
        <Arrow />
        <Box title={t('abDiagApi')} sub="routers → services" tone="neutral" className="min-w-[150px]" />
      </div>
      <div className="grid sm:grid-cols-3 gap-3">
        <div className="space-y-2 text-center">
          <Box title={t('abDiagOpenRouter')} sub="vision · chat · advice" tone="hosted" />
          <span aria-hidden="true" className="block text-navy/60 text-[14px]">↓</span>
          <Box title={t('abDiagModel')} sub="OPENROUTER_*_MODEL" tone="hosted" />
        </div>
        <div className="space-y-2 text-center">
          <Box title={t('abDiagLocal')} sub={t('abDiagLocalSub')} tone="local" />
        </div>
        <div className="space-y-2 text-center">
          <Box title={t('abDiagSupabase')} sub={t('abDiagSupabaseSub')} tone="data" />
        </div>
      </div>
      <div className="flex flex-wrap justify-center gap-4 text-[11px] font-display text-muted">
        <span className="inline-flex items-center gap-1.5"><i className="w-3 h-3 rounded-sm bg-warn-light" style={BORDER} />{t('abDiagOpenRouter')}</span>
        <span className="inline-flex items-center gap-1.5"><i className="w-3 h-3 rounded-sm bg-ok-light" style={BORDER} />{t('abDiagLocal')}</span>
        <span className="inline-flex items-center gap-1.5"><i className="w-3 h-3 rounded-sm bg-accent-light" style={BORDER} />{t('abDiagSupabase')}</span>
      </div>
    </div>
  )
}

/** A left-to-right sequence of numbered steps; `tones` colours each step by where it runs. */
export function StepFlow({ steps, tones = [], testId }) {
  return (
    <ol className="flex flex-wrap items-stretch gap-2" data-testid={testId}>
      {steps.map((label, i) => (
        <li key={i} className="flex items-center gap-2">
          <Box title={`${i + 1}. ${label}`} tone={tones[i] || 'neutral'} className="h-full flex items-center min-w-[108px]" />
          {i < steps.length - 1 && <Arrow />}
        </li>
      ))}
    </ol>
  )
}

export function WorkflowFlow() {
  const { t } = useLanguage()
  const steps = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => t(`abFlow${n}`))
  // where each step runs: upload/preprocess/quant/translation/PDF locally on the backend; the AI scan is hosted
  const tones = ['neutral', 'local', 'local', 'hosted', 'local', 'data', 'data', 'local']
  return <StepFlow steps={steps} tones={tones} testId="workflow-flow" />
}

export function TranslationFlow() {
  const { t } = useLanguage()
  const steps = [1, 2, 3, 4, 5, 6, 7].map((n) => t(`abTransFlow${n}`))
  return (
    <div className="space-y-2">
      <StepFlow steps={steps} tones={['hosted', 'local', 'local', 'local', 'local', 'local', 'neutral']} testId="translation-flow" />
      <p className="text-[12px] font-display text-muted">{t('abTransFallback')}</p>
    </div>
  )
}
