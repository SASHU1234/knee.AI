import { useState } from 'react'
import { sampleImageUrl } from '../lib/api'
import { ARCH_DETAILS, CAPABILITY_DETAILS, MODELS, STACK, STATUS } from '../lib/aboutData'
import { useLanguage } from '../lib/LanguageContext'
import { ArchDiagram, TranslationFlow, WorkflowFlow } from '../components/AboutDiagrams'
import { Card } from '../components/ui'
import Icon from '../components/Icon'

const SUPPORT_EMAIL = 'knee.reply@gmail.com'

const CAPS = [
  { id: 'vision', icon: 'search' }, { id: 'chat', icon: 'chat' }, { id: 'advice', icon: 'leaf' },
  { id: 'quant', icon: 'ruler' }, { id: 'implant', icon: 'implant' }, { id: 'provenance', icon: 'shield' },
  { id: 'longitudinal', icon: 'history' }, { id: 'review', icon: 'check' }, { id: 'demo', icon: 'sparkle' },
]
const NAV = [
  ['about-intro', 'abIntroTitle'], ['about-problem', 'abProblemTitle'], ['about-capabilities', 'abCapTitle'],
  ['about-workflow', 'abFlowTitle'], ['about-architecture', 'abArchTitle'], ['about-stack', 'abStackTitle'],
  ['about-language', 'abLangTitle'], ['about-status', 'abStatusTitle'], ['about-security', 'abSecTitle'],
  ['about-limits', 'abLimTitle'], ['about-project', 'abProjectTitle'],
]
const STATUS_STYLE = { ok: 'bg-ok-light text-ok', config: 'bg-warn-light text-warn', demo: 'bg-accent-light text-accent' }

/** Technical detail disclosure. The bullet text comes from aboutData.js and is English by design. */
function Details({ items, label }) {
  return (
    <details className="group mt-3">
      <summary className="cursor-pointer text-[12px] font-display font-semibold text-accent hover:underline list-none flex items-center gap-1">
        <Icon name="chevron" size={12} className="transition-transform group-open:rotate-90" />{label}
      </summary>
      <ul className="mt-2 space-y-1.5 list-disc pl-5 text-[12px] text-muted font-display leading-relaxed" lang="en">
        {items.map((x, i) => <li key={i}>{x}</li>)}
      </ul>
    </details>
  )
}

function SectionTitle({ id, eyebrow, title, intro }) {
  return (
    <div id={id} className="scroll-mt-24">
      {eyebrow && <p className="eyebrow mb-0.5">{eyebrow}</p>}
      <h3 className="text-[17px] font-display font-bold text-navy">{title}</h3>
      {intro && <p className="text-[13px] text-muted font-display mt-1 max-w-3xl leading-relaxed">{intro}</p>}
    </div>
  )
}

function SampleImage() {
  const { t } = useLanguage()
  const [ok, setOk] = useState(true)
  if (!ok) return null
  return (
    <figure className="w-full sm:w-[200px] shrink-0">
      {/* a real synthetic sample radiograph shipped with the app; hidden if the backend is unreachable */}
      <img src={sampleImageUrl('/api/samples/OAI_sample_03/image')} alt="Synthetic sample knee radiograph (OAI_sample_03)" loading="lazy"
           onError={() => setOk(false)} className="w-full h-auto rounded-[10px] bg-black object-contain" style={{ border: '2px solid #2D2016' }} />
      <figcaption className="mt-1.5 text-[10.5px] font-display text-muted leading-snug">{t('abBadge2')} · OAI_sample_03</figcaption>
    </figure>
  )
}

export default function About() {
  const { t } = useLanguage()
  const capTitle = (id) => t(`abCap_${id}_t`)

  return (
    <div className="space-y-10">
      {/* 1. Hero / introduction */}
      <section id="about-intro" className="scroll-mt-24 space-y-5">
        <div>
          <h2 className="page-title">Knee.AI</h2>
          <p className="text-[14px] text-muted mt-1 font-display max-w-3xl">{t('abTagline')}</p>
          <div className="flex flex-wrap gap-2 mt-3">
            <span className="pill bg-accent-light text-accent">{t('abBadge1')}</span>
            <span className="pill bg-warn-light text-warn">{t('abBadge2')}</span>
            <span className="pill bg-danger-light text-danger">{t('abBadge3')}</span>
          </div>
        </div>

        <Card eyebrow="Platform" title={t('abIntroTitle')} icon="activity" tone="green">
          <div className="flex flex-col sm:flex-row gap-5">
            <div className="space-y-4 min-w-0">
              <p className="text-[13px] text-navy font-display leading-relaxed">{t('abIntroBody')}</p>
              <div>
                <h4 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-1.5">{t('abDiffTitle')}</h4>
                <ul className="list-disc pl-5 space-y-1 text-[13px] text-navy font-display leading-relaxed">
                  {[1, 2, 3].map((n) => <li key={n}>{t(`abDiff${n}`)}</li>)}
                </ul>
              </div>
              <div>
                <h4 className="text-[12px] font-display font-bold text-navy uppercase tracking-wider mb-1.5">{t('abUsersTitle')}</h4>
                <p className="text-[13px] text-muted font-display leading-relaxed">{t('abUsersBody')}</p>
              </div>
            </div>
            <SampleImage />
          </div>
        </Card>

        <nav aria-label={t('abNavLabel')} className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-display text-muted mr-1">{t('abNavLabel')}:</span>
          {NAV.map(([id, key]) => (
            <a key={id} href={`#${id}`} className="pill bg-page text-navy hover:bg-accent-light">{t(key)}</a>
          ))}
        </nav>
        <p className="text-[11px] text-muted font-display">{t('abTechEnglishNote')}</p>
      </section>

      {/* 2. Problem */}
      <section className="space-y-4">
        <SectionTitle id="about-problem" eyebrow="Context" title={t('abProblemTitle')} intro={t('abProblemIntro')} />
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[1, 2, 3, 4, 5, 6, 7].map((n) => (
            <div key={n} className="rounded-[12px] bg-surface p-4" style={{ border: '2px solid #2D2016' }}>
              <p className="text-[13px] font-display font-bold text-navy">{t(`abProb${n}T`)}</p>
              <p className="text-[12px] text-muted font-display leading-relaxed mt-1">{t(`abProb${n}B`)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 3. Capabilities */}
      <section className="space-y-4">
        <SectionTitle id="about-capabilities" eyebrow="Features" title={t('abCapTitle')} intro={t('abCapIntro')} />
        <div className="grid gap-3">
          {CAPS.map(({ id, icon }) => {
            const st = STATUS.find((s) => s.id === id)
            return (
              <div key={id} id={`cap-${id}`} className="card card-pad" data-testid={`cap-${id}`}>
                <div className="flex items-start gap-3">
                  <span className="w-9 h-9 rounded-[10px] bg-accent-light text-accent flex items-center justify-center shrink-0"><Icon name={icon} size={17} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-[14px] font-display font-bold text-navy">{capTitle(id)}</h4>
                      {st && <span className={`pill ${STATUS_STYLE[st.status]}`}>{t(`abStatus_${st.status}`)}</span>}
                    </div>
                    <p className="text-[13px] text-muted font-display leading-relaxed mt-1">{t(`abCap_${id}_s`)}</p>
                    <Details items={CAPABILITY_DETAILS[id]} label={t('abDetails')} />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 4. Workflow */}
      <section className="space-y-4">
        <SectionTitle id="about-workflow" eyebrow="Workflow" title={t('abFlowTitle')} intro={t('abFlowIntro')} />
        <Card eyebrow="Pipeline" title={t('abFlowTitle')} icon="layers" tone="amber"><WorkflowFlow /></Card>
      </section>

      {/* 5. Architecture */}
      <section className="space-y-4">
        <SectionTitle id="about-architecture" eyebrow="Engineering" title={t('abArchTitle')} intro={t('abArchIntro')} />
        <Card eyebrow="Architecture" title={t('abArchTitle')} icon="layers" tone="blue"><ArchDiagram /></Card>
        <div className="grid gap-3">
          {['frontend', 'backend', 'ai', 'image', 'translation', 'data'].map((k) => (
            <div key={k} className="card card-pad" data-testid={`arch-${k}`}>
              <h4 className="text-[14px] font-display font-bold text-navy">{t(`abArch_${k}`)}</h4>
              {k === 'translation' && <div className="mt-3"><TranslationFlow /></div>}
              <Details items={ARCH_DETAILS[k]} label={t('abDetails')} />
            </div>
          ))}
        </div>
      </section>

      {/* 6. Technology stack */}
      <section className="space-y-4">
        <SectionTitle id="about-stack" eyebrow="Stack" title={t('abStackTitle')} intro={t('abStackIntro')} />
        <div className="grid md:grid-cols-2 gap-3" data-testid="stack">
          {STACK.map((g) => (
            <div key={g.group} className="card card-pad">
              <h4 className="text-[13px] font-display font-bold text-navy mb-2">{t(`abStackGroup_${g.group}`)}</h4>
              <ul className="space-y-2" lang="en">
                {g.items.map((it) => (
                  <li key={it.name} className="text-[12px] font-display leading-snug">
                    <span className="font-semibold text-navy">{it.name}</span>
                    {it.version && <span className="text-muted"> · {it.version}</span>}
                    {it.core === false && <span className="pill bg-page text-muted ml-1.5">{t('abOptional')}</span>}
                    <p className="text-muted mt-0.5">{it.use}</p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* 7. Multilingual */}
      <section className="space-y-4">
        <SectionTitle id="about-language" eyebrow="Languages" title={t('abLangTitle')} intro={t('abLangLead')} />
        <div className="grid sm:grid-cols-2 gap-3">
          {[['abLangGen', 'abLangGenBody'], ['abLangLocal', 'abLangLocalBody'], ['abLangTerms', 'abLangTermsBody'], ['abLangVerify', 'abLangVerifyBody']].map(([h, b]) => (
            <div key={h} className="rounded-[12px] bg-surface p-4" style={{ border: '2px solid #2D2016' }}>
              <p className="text-[13px] font-display font-bold text-navy">{t(h)}</p>
              <p className="text-[12px] text-muted font-display leading-relaxed mt-1">{t(b)}</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-muted font-display" lang="en">English · हिन्दी · தமிழ் · മലയാളം · తెలుగు · {MODELS.translation} (rev. {MODELS.translationRevision})</p>
      </section>

      {/* 8. What is operational */}
      <section className="space-y-4">
        <SectionTitle id="about-status" eyebrow="Status" title={t('abStatusTitle')} intro={t('abStatusIntro')} />
        <div className="card overflow-x-auto">
          <table className="w-full text-[12px] font-display" data-testid="status-table">
            <tbody>
              {STATUS.map((s) => (
                <tr key={s.id} className="row-hover align-top">
                  <td className="td font-semibold text-navy">{s.id === 'translation' ? t('abArch_translation') : capTitle(s.id)}</td>
                  <td className="td whitespace-nowrap"><span className={`pill ${STATUS_STYLE[s.status]}`}>{t(`abStatus_${s.status}`)}</span></td>
                  <td className="td text-muted" lang="en">{s.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 9. Security */}
      <section className="space-y-4">
        <SectionTitle id="about-security" eyebrow="Security" title={t('abSecTitle')} intro={t('abSecIntro')} />
        <Card eyebrow="Privacy" title={t('abSecTitle')} icon="shield" tone="blue">
          <ul className="list-disc pl-5 space-y-1.5 text-[13px] text-navy font-display leading-relaxed">
            {[1, 2, 3, 4, 5].map((n) => <li key={n}>{t(`abSec${n}`)}</li>)}
          </ul>
        </Card>
      </section>

      {/* 10. Limitations: prominent */}
      <section className="space-y-4">
        <SectionTitle id="about-limits" eyebrow="Clinical Use" title={t('abLimTitle')} intro={t('abLimIntro')} />
        <Card eyebrow="Clinical Use" title={t('abLimTitle')} icon="shield" tone="red">
          <ol className="space-y-2 text-[13px] text-navy font-display leading-relaxed" data-testid="limitations">
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <li key={n} className="flex gap-3"><span className="font-bold text-danger w-5 shrink-0">{n}.</span><span>{t(`abLim${n}`)}</span></li>
            ))}
          </ol>
          <p className="mt-4 text-[13px] font-display font-semibold text-navy">{t('abLimClosing')}</p>
        </Card>
      </section>

      {/* 11. Project information (existing contact block) */}
      <section className="space-y-4">
        <SectionTitle id="about-project" eyebrow="Support" title={t('abProjectTitle')} />
        <Card eyebrow="Support" title={t('aboutContactTitle')} icon="globe" tone="blue">
          <p className="text-[13px] text-muted font-display leading-relaxed mb-5">{t('abContactBody')}</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="rounded-[12px] bg-page p-4" style={{ border: '2px solid #2D2016' }}>
              <div className="flex items-center gap-2.5 mb-2">
                <Icon name="mail" size={16} className="text-accent" />
                <span className="text-[13px] font-display font-bold text-navy">{t('aboutEmailLabel')}</span>
              </div>
              <a href={`mailto:${SUPPORT_EMAIL}`} className="text-[14px] font-display font-semibold text-accent hover:text-navy transition-colors duration-150 break-all">{SUPPORT_EMAIL}</a>
              <p className="mt-2 text-[11px] text-muted font-display leading-relaxed">{t('abContactEmailNote')}</p>
            </div>
            <div className="rounded-[12px] bg-page p-4" style={{ border: '2px solid #2D2016' }}>
              <div className="flex items-center gap-2.5 mb-2">
                <Icon name="chat" size={15} className="text-accent" />
                <span className="text-[13px] font-display font-bold text-navy">{t('aboutChatLabel')}</span>
              </div>
              <p className="text-[12px] text-muted font-display leading-relaxed">{t('aboutChatNote')}</p>
            </div>
          </div>
        </Card>
      </section>
    </div>
  )
}
