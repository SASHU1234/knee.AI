import { Component, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  downloadReport, getDemoCachedAi, getDemoCase, getDemoCaseProvenance, getDemoLongitudinal,
  getVisionObservations, listDemoCases, listDemoSeries, sampleImageUrl,
} from '../lib/api'
import { useLanguage } from '../lib/LanguageContext'
import {
  MODE_CACHED, MODE_LIVE, STAGES, completed, describeAiSource, goTo, initialDemoState, isFirst, isLast, next, prev,
  progressPct, restart, setMode,
} from '../lib/demoSteps'
import { Card, ErrorNote, Spinner } from '../components/ui'
import { ImplantTable, MeniscusTable, QualityCard } from '../components/AnalysisShell'
import EvidencePanel from '../components/EvidencePanel'
import ReviewPanel from '../components/ReviewPanel'
import LongitudinalView from '../components/LongitudinalView'
import LanguageSwitcher from '../components/LanguageSwitcher'
import TranslatedBlock from '../components/TranslatedBlock'
import Viewer from '../components/Viewer'
import Icon from '../components/Icon'

/** A crash inside one stage must never blank the whole demo: show the error and let the user move on. */
class StageBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null } }
  static getDerivedStateFromError(error) { return { error } }
  componentDidUpdate(prev) { if (prev.stage !== this.props.stage && this.state.error) this.setState({ error: null }) }
  render() {
    if (this.state.error) return <ErrorNote>{this.props.message}</ErrorNote>
    return this.props.children
  }
}

/**
 * Guided demonstration. It drives the real backend: the case is analysed in memory by the normal builder,
 * AI Visual Scan is the real /api/vision call in Live mode, the report is the existing PDF service, and
 * provenance/comparison/review use the same services as real studies. Nothing is saved to the user's
 * history. Pre-generated text is labelled as such and is never substituted for a failed live call.
 */
export default function GuidedDemo() {
  const { t } = useLanguage()
  const [state, setState] = useState(initialDemoState)
  const [cases, setCases] = useState([])
  const [source, setSource] = useState('OAI_sample_03')
  const [record, setRecord] = useState(null)
  const [caseError, setCaseError] = useState('')
  const [ai, setAi] = useState(null) // { mode, text, provenance, label }
  const [aiError, setAiError] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [longi, setLongi] = useState(null)
  const [longiError, setLongiError] = useState('')
  const [seriesList, setSeriesList] = useState([])
  const [seriesId, setSeriesId] = useState('DEMO-SERIES-001')
  const [prov, setProv] = useState(null)
  const [report, setReport] = useState({ busy: false, done: false, error: '' })

  useEffect(() => { listDemoCases().then((d) => setCases(d.items)).catch((e) => setCaseError(e.message)) }, [])

  // Prepare the case when it is chosen (cheap, no AI). Everything expensive waits for its own stage.
  useEffect(() => {
    let live = true
    setRecord(null)
    setCaseError('')
    setAi(null)
    setAiError('')
    setProv(null)
    getDemoCase(source).then((r) => live && setRecord(r)).catch((e) => live && setCaseError(e.message))
    return () => { live = false }
  }, [source])

  const stage = STAGES[state.index].id

  // Stage-triggered loads
  useEffect(() => {
    if (stage === 'review' && !prov) getDemoCaseProvenance(source).then(setProv).catch(() => setProv({ provenance: [] }))
    if (stage === 'longitudinal' && !seriesList.length) listDemoSeries().then((d) => setSeriesList(d.items)).catch(() => {})
  }, [stage]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (stage !== 'longitudinal') return undefined
    let live = true
    setLongi(null)
    setLongiError('')
    getDemoLongitudinal(seriesId).then((d) => live && setLongi(d)).catch((e) => live && setLongiError(e.message))
    return () => { live = false }
  }, [stage, seriesId])

  const runLive = async () => {
    setAiBusy(true); setAiError(''); setAi(null)
    try {
      const res = await getVisionObservations(record.images.variants.none, record)
      setAi({ mode: MODE_LIVE, text: res.observations, provenance: res.provenance })
    } catch (e) {
      setAiError(e.message) // stays an error: no silent fallback to cached text
    } finally { setAiBusy(false) }
  }
  const loadCached = async () => {
    setAiBusy(true); setAiError(''); setAi(null)
    try {
      const res = await getDemoCachedAi(source)
      if (!res.valid) setAiError(`${t('demoInvalidCached')}: ${res.reason}`)
      else setAi({ mode: MODE_CACHED, text: res.visual_scan, provenance: res.provenance })
    } catch (e) { setAiError(e.message) } finally { setAiBusy(false) }
  }

  const makeReport = useCallback(async () => {
    setReport({ busy: true, done: false, error: '' })
    try { await downloadReport(record); setReport({ busy: false, done: true, error: '' }) }
    catch (e) { setReport({ busy: false, done: false, error: e.message }) }
  }, [record])

  const aiItems = ai ? [{ provenance: { ...ai.provenance, kind: 'visual_scan', content_sha256: ai.provenance?.content_sha256 || '' }, text: ai.text, label: 'AI Visual Scan observation' }] : []
  const source_ = describeAiSource(ai)
  const done = completed(state)

  const aiBlock = ai && (
    <div className="space-y-2">
      <p className="text-[12px] font-display font-semibold" style={{ color: source_.kind === 'live' ? '#2D9F6F' : '#B8860B' }} data-testid="ai-source-label">
        {t(source_.labelKey)}
      </p>
      <TranslatedBlock source={ai.text} studyId={record?.analysis_id} feature={`demo-ai-${ai.mode}`} contentType="visual_observations"
                       className="text-[13px] text-navy font-display leading-relaxed whitespace-pre-wrap" />
    </div>
  )

  const body = () => {
    if (caseError && !record) return <ErrorNote>{caseError}</ErrorNote>
    if (!record) return <Spinner label={t('demoLoading')} />
    switch (stage) {
      case 'overview':
        return (
          <div className="space-y-4">
            <label className="text-[12px] font-display font-semibold text-navy block">
              {t('demoCase')}
              <select className="input mt-1 block min-w-[280px]" value={source} onChange={(e) => setSource(e.target.value)}>
                {(cases.length ? cases : [{ source, label: source }]).map((c) => <option key={c.source} value={c.source}>{c.label}</option>)}
              </select>
            </label>
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-[13px] font-display">
              {[['Patient', record.patient.name], ['Age', record.patient.age], ['Sex', record.patient.sex], ['Modality', record.patient.imaging_type],
                ['Laterality', record.patient.affected_side], ['Analysed', String(record.created_at).replace('T', ' ')],
                ['Examination date', 'not recorded by the platform'], ['Status', 'Analysed (synthetic reference case, in memory only)']].map(([k, v]) => (
                <div key={k}><dt className="text-muted text-[11px]">{k}</dt><dd className="text-navy font-semibold">{v}</dd></div>
              ))}
            </dl>
          </div>
        )
      case 'image':
        return (
          <div className="space-y-4">
            <Viewer result={record} />
            <QualityCard quality={record.quality} uncertainty={record.uncertainty} />
          </div>
        )
      case 'ai':
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2" role="group">
              {[[MODE_CACHED, 'demoModeCached'], [MODE_LIVE, 'demoModeLive']].map(([m, k]) => (
                <button key={m} type="button" className={state.mode === m ? 'btn-primary h-9 px-4 text-[12px]' : 'btn-ghost h-9 px-4 text-[12px]'}
                        aria-pressed={state.mode === m} onClick={() => { setState((s) => setMode(s, m)); setAi(null); setAiError('') }}>{t(k)}</button>
              ))}
            </div>
            {state.mode === MODE_LIVE ? (
              <button type="button" className="btn-primary" onClick={runLive} disabled={aiBusy}><Icon name="sparkle" size={15} />{aiBusy ? t('scanningImage') : t('demoRunLive')}</button>
            ) : (
              <button type="button" className="btn-primary" onClick={loadCached} disabled={aiBusy}><Icon name="file" size={15} />{t('demoLoadCached')}</button>
            )}
            {aiBusy && <Spinner label="..." />}
            <ErrorNote>{aiError}</ErrorNote>
            {aiBlock}
          </div>
        )
      case 'quant':
        return (
          <div className="space-y-4">
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 text-[13px] font-display">
              {[['Classification (rule-based)', record.meniscus.assessment?.classification],
                ['KL grade (estimated)', record.meniscus.kl_grade?.grade],
                ['Mean thickness', record.meniscus.assessment?.mean_thickness_mm != null ? `${record.meniscus.assessment.mean_thickness_mm} mm` : null],
                ['Minimum thickness', record.meniscus.assessment?.min_thickness_mm != null ? `${record.meniscus.assessment.min_thickness_mm} mm` : null]].map(([k, v]) => (
                <div key={k}><dt className="text-muted text-[11px]">{k}</dt><dd className="text-navy font-semibold">{v ?? 'not available'}</dd></div>
              ))}
            </dl>
            {record.meniscus.population_comparison?.length
              ? <MeniscusTable rows={record.meniscus.population_comparison} sex={record.patient.sex} />
              : <p className="text-[12px] text-muted font-display">Population comparison is not available for this case.</p>}
          </div>
        )
      case 'implant':
        return record.implant?.primary ? <ImplantTable implant={record.implant} /> : <p className="text-[12px] text-muted font-display">No implant sizing is available for this case.</p>
      case 'language':
        return (
          <div className="space-y-4">
            <p className="text-[13px] text-muted font-display">{t('demoLanguageHint')}</p>
            <LanguageSwitcher />
            {ai ? aiBlock : <p className="text-[12px] text-muted font-display">{t('demoNoAiYet')}</p>}
          </div>
        )
      case 'provenance':
        return <EvidencePanel demoSource={source} aiItems={aiItems} defaultOpen />
      case 'longitudinal':
        return (
          <div className="space-y-4">
            {seriesList.length > 1 && (
              <label className="text-[12px] font-display font-semibold text-navy block">
                {t('demoSeries')}
                <select className="input mt-1 block min-w-[320px]" value={seriesId} onChange={(e) => setSeriesId(e.target.value)}>
                  {seriesList.map((s) => <option key={s.series_id} value={s.series_id}>{s.label}</option>)}
                </select>
              </label>
            )}
            {longiError ? <ErrorNote>{longiError}</ErrorNote> : !longi ? <Spinner label="..." /> : (
              <LongitudinalView comparison={longi.comparison} series={longi.series} timeline={longi.timeline} notes={longi.notes}
                                imageOverride={longi.image_url ? sampleImageUrl(longi.image_url) : undefined} demoLabel={longi.label} rejectedExample={longi.rejected_example} />
            )}
          </div>
        )
      case 'review':
        if (!prov) return <Spinner label="..." />
        return <ReviewPanel demo demoFindings={prov.provenance.slice(0, 8).map((p) => ({ finding_id: p.finding_id, title: p.title, kind: p.category, value: p.value, unit: p.unit }))} aiItems={aiItems} />
      case 'report':
        return (
          <div className="space-y-3">
            <button type="button" className="btn-primary" onClick={makeReport} disabled={report.busy}><Icon name="download" size={15} />{report.busy ? '...' : t('demoGenerateReport')}</button>
            {report.done && <p className="text-[12px] font-display text-ok" role="status">{t('demoReportDone')}</p>}
            <ErrorNote>{report.error}</ErrorNote>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="page-title">{t('demoTitle')}</h2>
          <p className="text-[13px] text-muted mt-1">{t('demoEntrySub')}</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={() => { setState((s) => restart(s)); setAi(null); setAiError(''); setReport({ busy: false, done: false, error: '' }) }}>{t('demoRestart')}</button>
          <Link to="/" className="btn-ghost h-9 px-3 text-[12px]">{t('demoExit')}</Link>
        </div>
      </div>

      <div className="rounded-[10px] bg-warn-light px-3.5 py-2.5 text-[12px] font-display text-navy" style={{ border: '2px solid #2D2016' }} role="status">
        {t('demoSyntheticBanner')}
      </div>

      <div aria-label="progress" className="space-y-2">
        <div className="h-2 rounded-full bg-page overflow-hidden" style={{ border: '1.5px solid #2D2016' }}>
          <div className="h-full bg-accent transition-all" style={{ width: `${progressPct(state)}%` }} data-testid="demo-progress" />
        </div>
        <ol className="flex flex-wrap gap-1.5">
          {STAGES.map((s, i) => (
            <li key={s.id}>
              <button type="button" onClick={() => setState((st) => goTo(st, i))} aria-current={i === state.index ? 'step' : undefined}
                      className={`pill ${i === state.index ? 'bg-accent text-white' : done[i] ? 'bg-ok-light text-ok' : 'bg-page text-muted'}`}>
                {i + 1}. {t(s.titleKey)}
              </button>
            </li>
          ))}
        </ol>
      </div>

      <Card eyebrow={`${t('demoStage')} ${state.index + 1} ${t('demoOf')} ${STAGES.length}`} title={t(STAGES[state.index].titleKey)} icon="layers">
        <StageBoundary stage={stage} message={t('demoStageUnavailable')}>{body()}</StageBoundary>
      </Card>

      <div className="flex justify-between">
        <button type="button" className="btn-ghost" onClick={() => setState((s) => prev(s))} disabled={isFirst(state)}>{t('demoPrev')}</button>
        {isLast(state)
          ? <Link to="/" className="btn-primary">{t('demoExit')}</Link>
          : <button type="button" className="btn-primary" onClick={() => setState((s) => next(s))}>{t('demoNext')}</button>}
      </div>
    </div>
  )
}
