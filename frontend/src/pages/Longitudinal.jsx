import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { compareStudies, getComparisonCandidates, getMeasurementSeries, listAnalyses } from '../lib/api'
import { useLanguage } from '../lib/LanguageContext'
import { fmtDate } from '../lib/longitudinalFormat'
import { Empty, ErrorNote, Spinner } from '../components/ui'
import LongitudinalView from '../components/LongitudinalView'

/**
 * Longitudinal Comparison for one study (the "current" examination). The backend finds candidate
 * earlier/later examinations of the same patient name within this account, validates comparability
 * and returns plain arithmetic differences; this page only lets the user pick and displays the result.
 */
export default function Longitudinal() {
  const { id } = useParams()
  const { t } = useLanguage()
  const [currentId, setCurrentId] = useState(id || null)
  const [timeline, setTimeline] = useState(null)
  const [previousId, setPreviousId] = useState('')
  const [comparison, setComparison] = useState(null)
  const [series, setSeries] = useState(null)
  const [measurement, setMeasurement] = useState('meniscus:mean')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  // no study in the URL: start from the most recent one
  useEffect(() => {
    if (id) { setCurrentId(id); return }
    listAnalyses().then(({ items }) => setCurrentId(items[0]?.analysis_id || null)).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    if (!currentId) return undefined
    let live = true
    setLoading(true)
    setError('')
    setComparison(null)
    getComparisonCandidates(currentId)
      .then((tl) => {
        if (!live) return
        setTimeline(tl)
        const earlier = tl.studies.filter((s) => !s.is_current && s.relation === 'earlier' && s.comparable_with_current)
        setPreviousId(earlier.length ? earlier[earlier.length - 1].study_id : '')
      })
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false))
    return () => { live = false }
  }, [currentId])

  useEffect(() => {
    if (!previousId || !currentId) return undefined
    let live = true
    compareStudies(previousId, currentId).then((c) => live && setComparison(c)).catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [previousId, currentId])

  useEffect(() => {
    if (!currentId || !timeline) return undefined
    let live = true
    getMeasurementSeries(currentId, measurement).then((s) => live && setSeries(s)).catch(() => live && setSeries(null))
    return () => { live = false }
  }, [currentId, measurement, timeline])

  if (loading && !timeline) return <Spinner label={t('loadingAnalysis')} />
  if (!currentId) return <Empty title={t('longTitle')} body={t('longNoCandidates')} cta={{ to: '/new', label: t('startNewAnalysis') }} />

  const options = (timeline?.studies || []).filter((s) => !s.is_current && s.relation === 'earlier')
  const noOthers = timeline && timeline.studies.length <= 1

  return (
    <div className="space-y-6">
      <div>
        <h2 className="page-title">{t('longTitle')}</h2>
        <p className="text-[13px] text-muted mt-1 max-w-3xl">{t('longIntro')}</p>
      </div>
      <ErrorNote>{error}</ErrorNote>

      {noOthers ? (
        <Empty title={t('longTitle')} body={t('longNoCandidates')} cta={{ to: '/new', label: t('startNewAnalysis') }} />
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-4">
            <label className="text-[12px] font-display font-semibold text-navy">
              {t('longPrevious')}
              <select className="input mt-1 block min-w-[260px]" value={previousId} onChange={(e) => setPreviousId(e.target.value)} aria-label={t('longSelectPrevious')}>
                <option value="">{t('longSelectPrevious')}</option>
                {options.map((s) => (
                  <option key={s.study_id} value={s.study_id}>
                    {fmtDate(s.examined_at)} · {s.side} · {s.modality}{s.comparable_with_current ? '' : ` - ${t('longNotComparable')}`}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[12px] font-display font-semibold text-navy">
              {t('longMeasurement')}
              <select className="input mt-1 block min-w-[220px]" value={measurement} onChange={(e) => setMeasurement(e.target.value)}>
                {(comparison?.measurements || [{ id: 'meniscus:mean', label: 'Meniscus thickness - mean' }]).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
          </div>
          <LongitudinalView comparison={comparison} series={series} timeline={timeline} />
        </>
      )}
    </div>
  )
}
