import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getDemoCaseProvenance, getProvenance, imageUrl } from '../lib/api'
import { useLanguage } from '../lib/LanguageContext'
import { ErrorNote, Spinner } from './ui'
import Icon from './Icon'

/** Which in-app place shows a given provenance section. Demo mode has no study routes to open. */
export function sectionTarget(section, studyId) {
  if (!section) return null
  if (section === 'ai-visual-scan' || section === 'imaging-viewer') return { scroll: section }
  if (!studyId) return null
  if (section === 'meniscus-measurements' || section === 'image-quality') return { route: `/oa/${studyId}` }
  if (section === 'implant-sizing') return { route: `/implant/${studyId}` }
  return null
}

const fmtTime = (s) => (s ? String(s).replace('T', ' ').replace(/\.\d+/, '').replace(/\+00:00$/, ' UTC') : null)

function Limits({ items }) {
  if (!items?.length) return null
  return (
    <ul className="mt-1.5 list-disc pl-4 text-[11px] text-muted font-display leading-snug">
      {items.map((l, i) => <li key={i}>{l}</li>)}
    </ul>
  )
}

function GoButton({ target, onGo, label }) {
  if (!target) return null
  return (
    <button type="button" onClick={() => onGo(target)} className="inline-flex items-center gap-1 text-[11px] font-display font-semibold text-accent hover:underline">
      {label} <Icon name="chevron" size={11} />
    </button>
  )
}

/**
 * Expandable "Clinical Evidence & Provenance" section. Fetches lazily on first open, shows only what the
 * backend recorded and reports everything else as unavailable. AI observations are shown with the
 * server-verified signature status; there are no confidence values or saliency maps to show.
 */
export default function EvidencePanel({ studyId, demoSource, aiItems = [], defaultOpen = false }) {
  const { t } = useLanguage()
  const navigate = useNavigate()
  const [open, setOpen] = useState(defaultOpen)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const aiKey = aiItems.map((a) => a.provenance?.content_sha256).join(',')

  useEffect(() => {
    if (!open || (!studyId && !demoSource)) return undefined
    let live = true
    setLoading(true)
    setError('')
    const req = demoSource ? getDemoCaseProvenance(demoSource) : getProvenance(studyId, aiItems)
    req.then((d) => live && setData(d)).catch((e) => live && setError(e.message)).finally(() => live && setLoading(false))
    return () => { live = false }
  }, [open, studyId, demoSource, aiKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const go = (target) => {
    if (target.scroll) document.getElementById(target.scroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    else if (target.route) navigate(target.route)
  }

  // Demo cases keep their AI text on the page, not in the server: show them from props.
  const ai = demoSource ? aiItems.map((a) => ({
    finding_id: `ai:${a.provenance?.kind}:${(a.provenance?.content_sha256 || '').slice(0, 16)}`,
    title: a.label, source: { type: a.provenance?.live === false ? 'pre_generated_demo_fixture' : 'vision_model', provider: a.provenance?.provider, model: a.provenance?.model },
    generated_at: a.provenance?.generated_at, source_image: a.provenance?.source_image, section: 'ai-visual-scan',
    verified: null, verification_note: a.provenance?.live === false ? 'pre-written demonstration text, not model output' : null,
  })) : (data?.ai_observations || [])

  const quant = (data?.provenance || []).filter((p) => ['quantitative_measurement', 'rule_based_classification', 'model_or_heuristic_grade'].includes(p.category))
  const implant = (data?.provenance || []).filter((p) => p.category === 'implant_sizing')
  const quality = (data?.provenance || []).filter((p) => p.category === 'image_quality')
  const origin = data?.origin
  const meta = data?.study

  return (
    <section className="card" id="evidence-panel">
      <button
        type="button"
        className="w-full card-head text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="evidence-body"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="w-9 h-9 rounded-[10px] bg-accent-light text-accent flex items-center justify-center shrink-0"><Icon name="shield" size={17} /></span>
          <div className="min-w-0">
            <p className="eyebrow mb-0.5">{t('evidenceEyebrow')}</p>
            <h2 className="card-title truncate">{t('evidenceTitle')}</h2>
          </div>
        </div>
        <Icon name="chevron" size={15} className={`text-muted transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>

      {open && (
        <div id="evidence-body" className="card-pad space-y-6">
          <p className="text-[12px] text-muted font-display leading-relaxed">{t('evidenceIntro')}</p>
          {loading && <Spinner label={t('evidenceLoading')} />}
          <ErrorNote>{error}</ErrorNote>

          {data && (
            <>
              <div>
                <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t('evidenceStudy')}</h3>
                <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-[12px] font-display">
                  {[
                    ['Study ID', meta?.study_id], ['Modality', meta?.modality], ['Laterality', meta?.laterality],
                    ['Age / sex', [meta?.age, meta?.sex].filter(Boolean).join(' / ') || null],
                    ['Analysed', fmtTime(meta?.analysis_timestamp)], ['Source file', meta?.source_filename],
                    ['Image size (px)', meta?.image_size_px?.every(Boolean) ? meta.image_size_px.join(' x ') : null],
                    ['Image hash', meta?.image_hash_prefix],
                  ].map(([k, v]) => (
                    <div key={k}><dt className="text-muted">{k}</dt><dd className="text-navy font-semibold break-all">{v ?? <span className="text-muted font-normal">not recorded</span>}</dd></div>
                  ))}
                </dl>
                {data.images?.original && (
                  <a className="mt-2 inline-flex items-center gap-1 text-[12px] font-display font-semibold text-accent hover:underline"
                     href={imageUrl(data.images.original)} target="_blank" rel="noreferrer">
                    <Icon name="search" size={13} /> {t('evidenceViewImage')}
                  </a>
                )}
              </div>

              <div>
                <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t('evidenceOrigin')}</h3>
                <div className="rounded-[10px] bg-page px-3.5 py-3 text-[12px] font-display text-navy" style={{ border: '2px solid #2D2016' }}>
                  <p className="font-semibold">{origin?.label}</p>
                  <p className="text-muted mt-1">{t('evidenceAlgorithm')}: {origin?.algorithm} · {origin?.segmentation}</p>
                  <p className="text-muted mt-1">{origin?.note}</p>
                </div>
              </div>

              <div>
                <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t('evidenceAiObs')}</h3>
                {ai.length === 0 ? (
                  <p className="text-[12px] text-muted font-display">{t('evidenceNoAi')}</p>
                ) : ai.map((o) => (
                  <div key={o.finding_id} className="rounded-[10px] bg-surface px-3.5 py-3 mb-2 text-[12px] font-display" style={{ border: '2px solid #2D2016' }}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-navy">{o.title}</span>
                      <span className="pill bg-accent-light text-accent">AI</span>
                      {o.verified === true && <span className="pill bg-ok-light text-ok">{t('evidenceVerified')}</span>}
                      {o.verified === false && <span className="pill bg-warn-light text-warn">{t('evidenceUnverified')}</span>}
                    </div>
                    <p className="text-muted mt-1">
                      {t('evidenceProvider')}: {o.source?.provider || 'n/a'} · {t('evidenceModel')}: {o.source?.model || 'n/a'}
                      {o.generated_at ? ` · ${t('evidenceGenerated')}: ${fmtTime(o.generated_at)}` : ''}
                      {o.source_image ? ` · ${t('evidenceSourceImage')}: ${o.source_image}` : ''}
                    </p>
                    {o.verification_note && <p className="text-muted mt-1">{o.verification_note}</p>}
                    <Limits items={o.limitations} />
                    <GoButton target={sectionTarget(o.section, studyId)} onGo={go} label={t('evidenceGoTo')} />
                  </div>
                ))}
              </div>

              {[['evidenceQuant', quant], ['evidenceImplant', implant], ['evidenceQuality', quality]].map(([key, rows]) => rows.length > 0 && (
                <div key={key}>
                  <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t(key)}</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12px] font-display">
                      <thead><tr><th className="th">{t('longMeasurement')}</th><th className="th">{t('evidenceValue')}</th><th className="th">{t('evidenceSide')}</th><th className="th">{t('evidenceSource')}</th><th className="th" /></tr></thead>
                      <tbody>
                        {rows.map((r) => (
                          <tr key={r.finding_id} className="row-hover align-top">
                            <td className="px-4 py-2 text-navy font-semibold">{r.title}</td>
                            <td className="px-4 py-2 whitespace-nowrap">{String(r.value)}{r.unit ? ` ${r.unit}` : ''}{r.match_pct != null ? ` (${r.match_pct}% match)` : ''}</td>
                            <td className="px-4 py-2">{r.side || '-'}</td>
                            <td className="px-4 py-2 text-muted">
                              {r.source?.algorithm || r.source?.type}
                              <Limits items={r.limitations} />
                            </td>
                            <td className="px-4 py-2"><GoButton target={sectionTarget(r.section, studyId)} onGo={go} label={t('evidenceGoTo')} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}

              {data.unavailable?.length > 0 && (
                <div>
                  <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t('evidenceUnavailable')}</h3>
                  <ul className="space-y-1 text-[12px] font-display text-muted">
                    {data.unavailable.filter((u) => !(demoSource && u.field === 'ai_observations')).map((u) => <li key={u.field}><b className="text-navy">{u.field}</b>: {u.reason}</li>)}
                  </ul>
                </div>
              )}

              <div>
                <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t('evidenceLimitations')}</h3>
                <ul className="list-disc pl-4 space-y-1 text-[12px] font-display text-muted">
                  {(data.notes || []).map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
