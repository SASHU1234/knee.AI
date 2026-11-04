import { Link } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { imageUrl, sampleImageUrl } from '../lib/api'
import { useLanguage } from '../lib/LanguageContext'
import { chartRows, fmtDate, fmtPct, fmtSigned, fmtValue } from '../lib/longitudinalFormat'
import { Card } from './ui'
import Icon from './Icon'

function StudyImage({ study, src, label }) {
  const { t } = useLanguage()
  // a study may carry its own image (demo cases); otherwise the stored variant is served by the backend
  const url = study?.image_url ? sampleImageUrl(study.image_url) : src || (study?.image ? imageUrl(study.image) : '')
  return (
    <figure className="min-w-0">
      <figcaption className="text-[11px] font-display text-muted mb-1.5">
        <b className="text-navy">{label}</b> · {t('longDate')} {fmtDate(study?.examined_at) || '-'} · {study?.side || '-'} · {study?.modality || '-'}
        {study?.image_view ? ` · ${study.image_view}` : ' · view not recorded'}
        {study?.synthetic_patient_id ? ` · ${study.synthetic_patient_id}` : ''}
      </figcaption>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" title="Open full size">
          {/* aspect ratio preserved: width-bound, auto height, never cropped or stretched */}
          <img src={url} alt={`${label} examination`} loading="lazy" className="w-full h-auto max-h-[420px] object-contain rounded-[10px] bg-black" style={{ border: '2px solid #2D2016' }} />
        </a>
      ) : <p className="text-[12px] text-muted">Image unavailable.</p>}
    </figure>
  )
}

/**
 * Presentational longitudinal comparison. Everything shown is what the backend returned:
 * comparability verdict, stored values, plain differences. No progression/improvement wording.
 */
export default function LongitudinalView({ comparison, series, timeline, imageOverride, demoLabel, rejectedExample, notes }) {
  const { t } = useLanguage()
  const cmp = comparison
  const comparable = cmp?.comparability?.comparable
  const rows = series ? chartRows(series.points) : []

  return (
    <div className="space-y-6">
      {demoLabel && (
        <div className="rounded-[10px] bg-warn-light px-3.5 py-2.5 text-[12px] font-display text-navy" style={{ border: '2px solid #2D2016' }} role="status">{demoLabel}</div>
      )}

      {notes?.length > 0 && (
        <ul className="list-disc pl-4 text-[11px] text-muted font-display space-y-0.5" data-testid="case-notes">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
      )}

      {timeline && (
        <Card eyebrow="Timeline" title={t('longTimeline')} icon="history">
          <p className="text-[11px] text-muted font-display mb-3">{timeline.identity_basis}</p>
          <ol className="relative border-l-2 border-navy/30 ml-2 space-y-3" data-testid="timeline">
            {timeline.studies.map((s) => (
              <li key={s.study_id} className="ml-4">
                <span className={`absolute -left-[7px] w-3 h-3 rounded-full ${s.is_current ? 'bg-accent' : 'bg-navy/50'}`} />
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] font-display">
                  <b className="text-navy">{fmtDate(s.examined_at)}</b>
                  <span className="text-muted">{s.side} · {s.modality} · {s.classification || '-'}</span>
                  {s.is_current && <span className="pill bg-accent-light text-accent">{t('longCurrent')}</span>}
                  {!s.is_current && s.comparable_with_current === false && <span className="pill bg-danger-light text-danger" title={(s.reasons || []).join(' ')}>{t('longNotComparable')}</span>}
                  {!s.synthetic && <Link to={`/results/${s.study_id}`} className="text-accent font-semibold hover:underline">{t('longViewStudy')}</Link>}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {cmp && (
        <>
          <div className="grid md:grid-cols-2 gap-4">
            <StudyImage study={cmp.previous} src={imageOverride} label={t('longPrevious')} />
            <StudyImage study={cmp.current} src={imageOverride} label={t('longCurrent')} />
          </div>

          {!comparable ? (
            <div className="rounded-[12px] bg-danger-light px-4 py-3 text-[13px] font-display text-navy" style={{ border: '2px solid #2D2016' }} role="alert">
              <p className="font-bold">{t('longNotComparable')}</p>
              <ul className="mt-1.5 list-disc pl-4 text-[12px]">{cmp.comparability.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          ) : (
            <Card eyebrow={t('longTitle')} title={t('longMeasurement')} icon="ruler">
              <div className="overflow-x-auto">
                <table className="w-full text-[13px] font-display" data-testid="comparison-table">
                  <thead><tr>
                    <th className="th">{t('longMeasurement')}</th><th className="th text-right">{t('longPrevious')}</th>
                    <th className="th text-right">{t('longCurrent')}</th><th className="th text-right">{t('longDifference')}</th><th className="th text-right">{t('longPercent')}</th>
                  </tr></thead>
                  <tbody>
                    {cmp.measurements.map((m) => (
                      <tr key={m.id} className="row-hover" title={m.note || undefined}>
                        <td className="td">{m.label}</td>
                        <td className="td text-right">{fmtValue(m.previous, m.unit) ?? <span className="text-muted">{t('longMissing')}</span>}</td>
                        <td className="td text-right">{fmtValue(m.current, m.unit) ?? <span className="text-muted">{t('longMissing')}</span>}</td>
                        <td className="td text-right font-semibold">{fmtSigned(m.difference, m.unit) ?? '-'}</td>
                        <td className="td text-right">{fmtPct(m.percentage_difference) ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-[12px] text-muted font-display">{t('longInterpretation')}</p>
            </Card>
          )}

          {cmp.comparability.warnings.length > 0 && (
            <div className="rounded-[10px] bg-page px-3.5 py-3 text-[12px] font-display text-muted" style={{ border: '2px solid #2D2016' }}>
              <p className="font-bold text-navy mb-1">{t('longWarnings')}</p>
              <ul className="list-disc pl-4 space-y-0.5">{cmp.comparability.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
        </>
      )}

      {series && (
        <Card eyebrow="Trend" title={`${t('longTrend')}: ${series.measurement.label}`} icon="activity">
          {series.trend_available ? (
            <div style={{ width: '100%', height: 240 }} data-testid="trend-chart">
              <ResponsiveContainer>
                <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E8DCC8" />
                  <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={(v) => fmtDate(new Date(v).toISOString())} fontSize={11} />
                  <YAxis fontSize={11} label={{ value: series.measurement.unit, angle: -90, position: 'insideLeft', fontSize: 11 }} domain={['auto', 'auto']} />
                  <Tooltip labelFormatter={(v) => fmtDate(new Date(v).toISOString())} formatter={(v) => [fmtValue(v, series.measurement.unit), series.measurement.label]} />
                  <Line type="linear" dataKey="value" stroke="#E8772E" strokeWidth={2} dot connectNulls={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-[12px] text-muted font-display">{t('longDirectOnly')}</p>
          )}
          <p className="mt-2 text-[11px] text-muted font-display">{series.note}</p>
          {series.points.some((p) => p.value == null) && <p className="mt-1 text-[11px] text-warn font-display">Some examinations have no stored value for this measurement; gaps are not filled in.</p>}
        </Card>
      )}

      {rejectedExample && (
        <Card eyebrow="Safety check" title={t('longRejectedExample')} icon="alert">
          <ul className="list-disc pl-4 text-[12px] font-display text-muted">{rejectedExample.comparability.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </Card>
      )}
    </div>
  )
}
