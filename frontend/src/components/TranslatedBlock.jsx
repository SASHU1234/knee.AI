import { useLanguage } from '../lib/LanguageContext'
import { useTranslatedText } from '../lib/useTranslatedText'

/**
 * Renders an English AI-generated string in the website's current language.
 * The English `source` is never altered; see useTranslatedText.
 */
export default function TranslatedBlock({ source, studyId, feature, contentType, className = '', as: Tag = 'p' }) {
  const { t } = useLanguage()
  const { text, loading, error, translated, rejected } = useTranslatedText(source, { studyId, feature, contentType })
  return (
    <>
      <Tag className={className} aria-busy={loading}>{text}</Tag>
      {loading && (
        <p className="mt-2 text-[11px] text-muted font-display" role="status">{t('translating')}</p>
      )}
      {translated && (
        <p className="mt-2 text-[10.5px] text-muted font-display leading-snug">{t('machineTranslatedNote')}</p>
      )}
      {error && (
        <p className="mt-2 text-[10.5px] text-muted font-display leading-snug" role="status">{t(rejected ? 'translationRejected' : 'translationUnavailable')}</p>
      )}
    </>
  )
}
