import { useCallback, useEffect, useState } from 'react'
import { listReviews, submitReview } from '../lib/api'
import { useLanguage } from '../lib/LanguageContext'
import { ErrorNote, Spinner } from './ui'
import Icon from './Icon'

export const STATE_STYLE = {
  pending_review: 'bg-page text-muted',
  confirmed: 'bg-ok-light text-ok',
  needs_further_review: 'bg-warn-light text-warn',
  disagreed: 'bg-danger-light text-danger',
}
const STATE_KEY = {
  pending_review: 'reviewPending',
  confirmed: 'reviewConfirmed',
  needs_further_review: 'reviewNeedsFurther',
  disagreed: 'reviewDisagreed',
}
const newRequestId = () =>
  (globalThis.crypto?.randomUUID?.() ?? `r-${Date.now()}-${Math.random().toString(16).slice(2)}`).slice(0, 64)

/** Findings from this session's AI text become reviewable items alongside the stored ones. */
export function aiFindings(aiItems) {
  return aiItems.map((a) => ({
    finding_id: `ai:${a.provenance.kind}:${a.provenance.content_sha256.slice(0, 16)}`,
    title: a.label, kind: 'ai_observation', _ai: { provenance: a.provenance, text: a.text },
  }))
}

/**
 * Clinical Review. A decision is a new audit event; the reviewed result is never modified.
 * - Real study: decisions go to POST /api/reviews (reviewer = authenticated account, derived server-side)
 *   and the panel shows where they are stored.
 * - Demo (`demo` + `demoFindings`): everything is simulated and kept in component state only; it is
 *   labelled as such and never presented as a clinical approval.
 */
export default function ReviewPanel({ studyId, aiItems = [], demo = false, demoFindings = [] }) {
  const { t } = useLanguage()
  const [data, setData] = useState(null) // { findings, events, persistence, persistence_note }
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(!demo)
  const [busy, setBusy] = useState('')
  const [comments, setComments] = useState({})
  const [notice, setNotice] = useState('')
  const [simEvents, setSimEvents] = useState([]) // demo only

  const load = useCallback(() => {
    if (demo) return Promise.resolve()
    setLoading(true)
    return listReviews(studyId).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }, [studyId, demo])

  useEffect(() => { load() }, [load])

  const ai = aiFindings(aiItems)
  const baseFindings = demo
    ? demoFindings.map((f) => ({ ...f, state: simEvents.filter((e) => e.finding_id === f.finding_id).slice(-1)[0]?.new_state || 'pending_review' }))
    : (data?.findings || [])
  const aiRows = ai.map((f) => ({ ...f, state: (demo ? simEvents : data?.events || []).filter((e) => e.finding_id === f.finding_id).slice(-1)[0]?.new_state || 'pending_review' }))
  const findings = [...aiRows, ...baseFindings.filter((f) => !aiRows.some((a) => a.finding_id === f.finding_id))]
  const events = demo ? simEvents : (data?.events || [])

  const decide = async (finding, decision) => {
    setBusy(finding.finding_id + decision)
    setError('')
    setNotice('')
    const comment = (comments[finding.finding_id] || '').trim()
    try {
      if (demo) {
        const prev = simEvents.filter((e) => e.finding_id === finding.finding_id).slice(-1)[0]?.new_state || 'pending_review'
        setSimEvents((ev) => [...ev, {
          review_id: `demo-${ev.length + 1}`, finding_id: finding.finding_id, finding_title: finding.title, decision, comment,
          previous_state: prev, new_state: decision, created_at: new Date().toISOString(), simulated: true,
        }])
        setNotice(t('reviewSaved'))
      } else {
        const res = await submitReview({
          study_id: studyId, finding_id: finding.finding_id, decision, comment: comment || undefined,
          request_id: newRequestId(), expected_previous_state: finding.state,
          ...(finding._ai ? { ai: finding._ai } : {}),
        })
        setNotice(res.review.duplicate ? t('reviewDuplicate') : t('reviewSaved'))
        await load()
      }
      setComments((c) => ({ ...c, [finding.finding_id]: '' }))
    } catch (e) {
      setError(e.message)
      if (!demo) load() // a conflict means the status moved: show the current one
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="card" id="clinical-review">
      <div className="card-head">
        <div className="flex items-center gap-3 min-w-0">
          <span className="w-9 h-9 rounded-[10px] bg-ok-light text-ok flex items-center justify-center shrink-0"><Icon name="check" size={17} /></span>
          <div className="min-w-0">
            <p className="eyebrow mb-0.5">{t('reviewReviewer')}</p>
            <h2 className="card-title truncate">{t('reviewTitle')}</h2>
          </div>
        </div>
      </div>
      <div className="card-pad space-y-5">
        {demo ? (
          <div className="rounded-[10px] bg-warn-light px-3.5 py-2.5 text-[12px] font-display text-navy" style={{ border: '2px solid #2D2016' }} role="status">
            {t('reviewDemoBanner')}
          </div>
        ) : (
          <p className="text-[12px] text-muted font-display leading-relaxed">{t('reviewIntro')}</p>
        )}
        <p className="text-[11px] text-muted font-display">{t('reviewerNote')}</p>
        {!demo && data && <p className="text-[11px] text-muted font-display">{t('reviewStoredAt')}: <b className="text-navy">{data.persistence}</b> - {data.persistence_note}</p>}

        {loading && <Spinner label="..." />}
        <ErrorNote>{error}</ErrorNote>
        {notice && <p className="text-[12px] font-display text-ok" role="status">{notice}</p>}

        <ul className="space-y-3">
          {findings.map((f) => (
            <li key={f.finding_id} className="rounded-[10px] bg-surface px-3.5 py-3" style={{ border: '2px solid #2D2016' }}>
              <div className="flex flex-wrap items-center gap-2 text-[12px] font-display">
                <span className="font-semibold text-navy">{f.title}</span>
                {f.value != null && <span className="text-muted">{String(f.value)}{f.unit ? ` ${f.unit}` : ''}</span>}
                <span className={`pill ${STATE_STYLE[f.state] || STATE_STYLE.pending_review}`} data-testid={`state-${f.finding_id}`}>{t(STATE_KEY[f.state] || 'reviewPending')}</span>
              </div>
              {f._ai && <p className="mt-1.5 text-[11px] text-muted font-display line-clamp-3" title={f._ai.text}>{t('reviewAiText')}: {f._ai.text}</p>}
              <textarea
                className="input mt-2 w-full text-[12px] resize-none" rows={2} maxLength={1000}
                placeholder={t('reviewComment')} aria-label={`${t('reviewComment')} - ${f.title}`}
                value={comments[f.finding_id] || ''} onChange={(e) => setComments((c) => ({ ...c, [f.finding_id]: e.target.value }))}
              />
              <div className="mt-2 flex flex-wrap gap-2">
                {[['confirmed', 'reviewConfirm'], ['needs_further_review', 'reviewNeedsAction'], ['disagreed', 'reviewDisagree']].map(([d, k]) => (
                  <button key={d} type="button" className="btn-ghost h-8 px-3 text-[12px]" disabled={!!busy}
                          onClick={() => decide(f, d)} data-testid={`${d}-${f.finding_id}`}>{t(k)}</button>
                ))}
              </div>
            </li>
          ))}
        </ul>

        <div>
          <h3 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-2">{t('reviewHistory')}</h3>
          {events.length === 0 ? (
            <p className="text-[12px] text-muted font-display">{t('reviewNoHistory')}</p>
          ) : (
            <ol className="space-y-1.5 text-[12px] font-display" data-testid="review-history">
              {events.map((e) => (
                <li key={e.review_id} className="flex flex-wrap gap-x-2 text-muted">
                  <span className="text-navy font-semibold">{String(e.created_at).replace('T', ' ').slice(0, 19)}</span>
                  <span>{e.finding_title || e.finding_id}</span>
                  <span>{t(STATE_KEY[e.previous_state] || 'reviewPending')} → <b className="text-navy">{t(STATE_KEY[e.new_state])}</b></span>
                  {e.simulated && <span className="pill bg-warn-light text-warn">{t('demoSimulatedOnly')}</span>}
                  {e.comment && <span className="italic">"{e.comment}"</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  )
}
