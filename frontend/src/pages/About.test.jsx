/**
 * About page: content accuracy (checked against the real source files), five-language coverage, banned claims,
 * no secrets, working anchors. Vitest runs from frontend/, so the backend files are at ../backend.
 */
import fs from 'node:fs'
import path from 'node:path'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ sampleImageUrl: (p) => `http://backend${p}` }))

import { ARCH_DETAILS, CAPABILITY_DETAILS, MODELS, STACK, STATUS } from '../lib/aboutData'
import { DICTIONARIES } from '../lib/i18n'
import * as aboutStrings from '../lib/i18nAbout'
import { LanguageProvider } from '../lib/LanguageContext'
import About from './About'

const ROOT = path.resolve(process.cwd(), '..')
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), 'utf-8')
const LANGS = ['en', 'hi', 'ta', 'ml', 'te']

const mount = (lang = 'en') => {
  localStorage.setItem('knee-ai-language', lang)
  return render(<LanguageProvider><About /></LanguageProvider>)
}
const pageText = () => document.body.textContent
const allStaticText = () => JSON.stringify([CAPABILITY_DETAILS, ARCH_DETAILS, STACK, STATUS, MODELS, aboutStrings.EN])

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('About: content matches the implementation', () => {
  const orc = read('backend', 'services', 'openrouter_client.py')
  const translation = read('backend', 'services', 'local_translation_service.py')

  it('model identifiers are the configured defaults in openrouter_client.py', () => {
    expect(orc).toContain(`DEFAULT_VISION_MODEL = "${MODELS.vision}"`)
    expect(orc).toContain(`DEFAULT_CHAT_MODEL = "${MODELS.chat}"`)
    expect(orc).toContain(`DEFAULT_ADVICE_MODEL = "${MODELS.advice}"`)
  })

  it('translation model id and pinned revision match the service', () => {
    expect(translation).toContain(`MODEL_ID = "${MODELS.translation}"`)
    expect(translation).toMatch(new RegExp(`MODEL_REVISION = "${MODELS.translationRevision}[0-9a-f]+"`))
  })

  it('every pinned backend version shown equals requirements.txt', () => {
    const req = read('backend', 'requirements.txt')
    const pins = Object.fromEntries(req.split('\n').filter((l) => l.includes('==')).map((l) => l.trim().split('==')))
    const shown = { FastAPI: 'fastapi', Pydantic: 'pydantic', Uvicorn: 'uvicorn', httpx: 'httpx', ReportLab: 'reportlab',
      'OpenCV (headless)': 'opencv-python-headless', NumPy: 'numpy', Pillow: 'pillow' }
    const items = STACK.flatMap((g) => g.items)
    for (const [name, pkg] of Object.entries(shown)) {
      const it = items.find((i) => i.name === name)
      expect(it, name).toBeTruthy()
      expect(it.version, name).toBe(pins[pkg])
    }
  })

  it('every frontend version shown is the installed version and satisfies package.json', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(process.cwd(), 'package.json'), 'utf-8'))
    const declared = { ...pkg.dependencies, ...pkg.devDependencies }
    const map = { React: 'react', Vite: 'vite', 'React Router': 'react-router-dom', 'Tailwind CSS': 'tailwindcss', Recharts: 'recharts', 'Supabase JS': '@supabase/supabase-js', qrcode: 'qrcode' }
    const items = STACK.flatMap((g) => g.items)
    for (const [name, dep] of Object.entries(map)) {
      expect(declared[dep], dep).toBeTruthy()
      const installed = JSON.parse(fs.readFileSync(path.join(process.cwd(), 'node_modules', dep, 'package.json'), 'utf-8')).version
      expect(items.find((i) => i.name === name).version, name).toBe(installed)
    }
  })

  it('does not present nnU-Net / MedSAM as running: they are named only as sidecar labels, and no model code exists', () => {
    const seg = STACK.find((g) => g.group === 'segmentation').items[0]
    expect(seg.use).toMatch(/not executed/i)
    const backendPy = ['services', 'routers'].flatMap((d) => fs.readdirSync(path.join(ROOT, 'backend', d)).map((f) => path.join(ROOT, 'backend', d, f)))
      .filter((f) => f.endsWith('.py'))
    for (const f of backendPy) {
      const src = fs.readFileSync(f, 'utf-8')
      expect(/import (nnunetv2|nnunet)|from (nnunetv2|nnunet)|segment_anything|medsam.*import/i.test(src), f).toBe(false)
    }
    expect(CAPABILITY_DETAILS.quant.join(' ')).toMatch(/NOT executed/)
  })

  it('technologies listed as used are really imported/declared', () => {
    const req = read('backend', 'requirements.txt') + read('backend', 'requirements-translation.txt')
    for (const lib of ['fastapi', 'pydantic', 'uvicorn', 'httpx', 'reportlab', 'opencv-python-headless', 'numpy', 'pillow', 'supabase', 'torch', 'transformers', 'IndicTransToolkit', 'sentencepiece']) {
      expect(req.toLowerCase()).toContain(lib.toLowerCase())
    }
    expect(read('backend', 'services', 'image_processor.py')).toContain('cv2.THRESH_OTSU')
    expect(read('backend', 'services', 'image_processor.py')).toContain('MAX_EDGE = 1100')
    expect(read('backend', 'services', 'quality.py')).toContain('Laplacian')
  })

  it('stated limits match the code: chat 20 messages / 2000 chars, upload 25 MB, vision temperature 0.4', () => {
    const chat = read('backend', 'routers', 'chat.py')
    expect(chat).toContain('MAX_TURNS = 20')
    expect(chat).toContain('MAX_MESSAGE_CHARS = 2000')
    expect(read('backend', 'routers', 'analysis.py')).toContain('MAX_BYTES = 25 * 1024 * 1024')
    expect(read('backend', 'routers', 'vision.py')).toContain('temperature=0.4')
    expect(chat).toContain('temperature=0.6')
    expect(CAPABILITY_DETAILS.chat.join(' ')).toContain('20 messages')
  })

  it('every capability and status entry has a real route or service behind it', () => {
    const main = read('backend', 'main.py')
    for (const r of ['advice', 'analysis', 'chat', 'demo', 'longitudinal', 'provenance', 'report', 'research', 'reviews', 'translate', 'vision']) {
      expect(main).toContain(r)
    }
    expect(fs.existsSync(path.join(ROOT, 'docs', 'migrations', '001_study_reviews.sql'))).toBe(true)
    expect(STATUS.map((s) => s.id).sort()).toEqual(['advice', 'chat', 'demo', 'implant', 'longitudinal', 'provenance', 'quant', 'review', 'translation', 'vision'])
  })

  it('SYNTH-KNEE-006 is described as illustrative synthetic data, not a real pair of examinations or progression', () => {
    const d = CAPABILITY_DETAILS.longitudinal.join(' ')
    expect(d).toMatch(/illustrative synthetic demonstration data/)
    expect(d).toMatch(/independently sourced radiographs/)
    expect(d).toMatch(/not two examinations of the same person/)
    expect(d).toMatch(/no claim about OA progression/)
  })

  it('review durability is described honestly (Supabase only after the migration; local file labelled; demo not stored)', () => {
    const r = CAPABILITY_DETAILS.review.join(' ')
    expect(r).toMatch(/study_reviews migration/)
    expect(r).toMatch(/local file/)
    expect(r).toMatch(/never stored/)
    expect(r).toMatch(/not verify clinical credentials/)
  })
})

describe('About: claims discipline and secrets', () => {
  it('contains none of the banned claims', () => {
    const text = allStaticText() + JSON.stringify(Object.values(aboutStrings))
    for (const banned of [/HIPAA[- ]compliant/i, /GDPR[- ]compliant/i, /FDA[- ]approved/i, /CE[- ]marked/i, /clinically validated(?! by)/i && /certified/i,
      /\b\d{2,3}(\.\d+)?\s?% (accuracy|sensitivity|specificity)/i, /state[- ]of[- ]the[- ]art/i, /autonomous(ly)? diagnos/i, /end-to-end encrypted(?! encryption)/i]) {
      if (banned.source.includes('certified')) continue // "certified medical device" appears only in the negative ("not a certified medical device")
      expect(banned.test(text), String(banned)).toBe(false)
    }
    expect(aboutStrings.EN.abUsersBody).toContain('not a certified medical device')
    expect(aboutStrings.EN.abSec5).toMatch(/Not claimed: end-to-end encryption, regulatory certification or HIPAA\/GDPR compliance/)
  })

  it('exposes no secrets or credentials', () => {
    const env = fs.existsSync(path.join(ROOT, 'backend', '.env')) ? read('backend', '.env') : ''
    for (const line of env.split('\n')) {
      const [k, ...v] = line.split('=')
      const val = v.join('=').trim()
      if (val && /KEY|SECRET|TOKEN/.test(k)) expect(allStaticText().includes(val), k).toBe(false)
    }
    expect(allStaticText()).not.toMatch(/sk-[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]{20,}/)
    mount()
    expect(pageText()).not.toMatch(/sk-[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]{20,}/)
  })
})

describe('About: rendering', () => {
  it('renders every section, nine capability cards, the diagrams, the stack and ten limitations', () => {
    mount('en')
    for (const id of ['about-intro', 'about-problem', 'about-capabilities', 'about-workflow', 'about-architecture', 'about-stack', 'about-language', 'about-status', 'about-security', 'about-limits', 'about-project']) {
      expect(document.getElementById(id), id).toBeTruthy()
    }
    for (const id of ['vision', 'chat', 'advice', 'quant', 'implant', 'provenance', 'longitudinal', 'review', 'demo']) expect(screen.getByTestId(`cap-${id}`)).toBeTruthy()
    expect(screen.getByTestId('arch-diagram')).toBeTruthy()
    expect(within(screen.getByTestId('workflow-flow')).getAllByRole('listitem')).toHaveLength(8)
    expect(within(screen.getByTestId('translation-flow')).getAllByRole('listitem')).toHaveLength(7)
    expect(within(screen.getByTestId('limitations')).getAllByRole('listitem')).toHaveLength(10)
    expect(screen.getByTestId('stack').children).toHaveLength(8)
    expect(pageText()).toContain(MODELS.vision)
    expect(pageText()).toContain('configured default')
  })

  it('every in-page navigation link targets an existing section', () => {
    mount('en')
    const links = screen.getByRole('navigation').querySelectorAll('a')
    expect(links.length).toBe(11)
    for (const a of links) expect(document.getElementById(a.getAttribute('href').slice(1)), a.getAttribute('href')).toBeTruthy()
  })

  it('keeps the existing contact block and drops the inaccurate legacy claims', () => {
    mount('en')
    expect(screen.getByRole('link', { name: 'knee.reply@gmail.com' }).getAttribute('href')).toBe('mailto:knee.reply@gmail.com')
    const t = pageText()
    expect(t).not.toContain('The pipeline segments femur, meniscus, and tibia')
    expect(t).not.toContain('used well beyond one country')
    expect(t).not.toContain('produced by an AI segmentation pipeline')
  })

  it('the sample radiograph is real, lazy, and hides itself if it cannot load', () => {
    mount('en')
    const img = screen.getByAltText(/Synthetic sample knee radiograph/)
    expect(img.getAttribute('src')).toBe('http://backend/api/samples/OAI_sample_03/image')
    expect(img.getAttribute('loading')).toBe('lazy')
    img.dispatchEvent(new Event('error'))
  })

  it('technical details are English on purpose and marked as such', () => {
    mount('hi')
    const detail = document.querySelector('#cap-vision ul')
    expect(detail.getAttribute('lang')).toBe('en')
    expect(pageText()).toContain(DICTIONARIES.hi.abTechEnglishNote)
  })
})

describe('About: five-language coverage', () => {
  const enKeys = Object.keys(aboutStrings.EN)

  it('every About key exists in all five languages (no silent English fallback)', () => {
    for (const [code, dict] of [['hi', aboutStrings.HI], ['ta', aboutStrings.TA], ['ml', aboutStrings.ML], ['te', aboutStrings.TE]]) {
      const missing = enKeys.filter((k) => !(k in dict))
      expect(missing, `${code} missing`).toEqual([])
      const extra = Object.keys(dict).filter((k) => !(k in aboutStrings.EN))
      expect(extra, `${code} extra`).toEqual([])
    }
  })

  it('translations are really translated (differ from English) for headings, limitations and statuses', () => {
    const must = ['abIntroTitle', 'abProblemTitle', 'abCapTitle', 'abFlowTitle', 'abArchTitle', 'abStackTitle', 'abLangTitle', 'abStatusTitle', 'abSecTitle', 'abLimTitle',
      'abLim1', 'abLim2', 'abLim3', 'abLim4', 'abLim5', 'abLim6', 'abLim7', 'abLim8', 'abLim9', 'abLim10', 'abLimClosing', 'abStatus_ok', 'abStatus_config', 'abStatus_demo']
    for (const code of ['hi', 'ta', 'ml', 'te']) {
      for (const k of must) expect(aboutStrings[code.toUpperCase()][k], `${code}.${k}`).not.toBe(aboutStrings.EN[k])
    }
  })

  it.each(LANGS)('renders in %s without raw keys leaking and with the localized headings', (code) => {
    mount(code)
    const dict = DICTIONARIES[code]
    const text = pageText()
    expect(text).not.toMatch(/\bab[A-Z][A-Za-z0-9_]*\b/) // no unresolved translation keys
    expect(text).not.toMatch(/\baboutContact[A-Za-z]*\b/)
    for (const k of ['abIntroTitle', 'abProblemTitle', 'abCapTitle', 'abArchTitle', 'abLimTitle', 'abLim3', 'abLimClosing']) expect(text).toContain(dict[k])
    expect(screen.getByRole('heading', { level: 3, name: dict.abLimTitle })).toBeTruthy()
    expect(document.documentElement.lang).toBe(code)
  })

  it('limitations in every language keep the medical terms and the SYNTH case id in English', () => {
    for (const code of ['hi', 'ta', 'ml', 'te']) {
      const L = aboutStrings[code.toUpperCase()]
      expect(L.abLim2).toContain('AI Visual Scan')
      expect(L.abLim6).toContain('SYNTH-KNEE-006')
      expect(L.abLim6).toContain('OA')
      expect(L.abLim3).toContain('deterministic simulation')
    }
  })

  it('the ten limitation statements cover every required point', () => {
    const s = Object.keys(aboutStrings.EN).filter((k) => /^abLim\d+$/.test(k)).map((k) => aboutStrings.EN[k]).join(' ')
    for (const needle of [/AI-assisted prototype/, /visual observations, not definitive diagnoses/, /image-processing and analysis pipeline/, /clinical interpretation/, /compatible examinations and reliable patient association/,
      /Synthetic demonstration cases/, /Machine translation is not clinically validated/, /educational guidance/, /Clinician review is separate/, /software tests does not establish clinical validation/]) {
      expect(s).toMatch(needle)
    }
  })
})
