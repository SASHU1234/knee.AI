import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./supabase', () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: { access_token: 'tok' } } }) } },
}))

import { analyze } from './api'

const patient = { name: 'SYNTH-KNEE-006', age: 54, sex: 'Female', imaging_type: 'X-ray', affected_side: 'Right' }
const file = new File([new Uint8Array([1, 2, 3])], 'knee.webp', { type: 'image/webp' })
let sent

beforeEach(() => {
  sent = null
  globalThis.fetch = vi.fn(async (url, opts) => { sent = { url, form: opts.body }; return { ok: true, json: async () => ({ analysis_id: 'a1' }) } })
})

describe('analyze() upload', () => {
  it('sends the optional longitudinal fields only when they were filled in', async () => {
    await analyze(file, { ...patient, synthetic_patient_id: 'SYNTH-KNEE-006', examined_date: '2022-03-14', imaging_view: 'AP standing' })
    expect(sent.form.get('synthetic_patient_id')).toBe('SYNTH-KNEE-006')
    expect(sent.form.get('examined_date')).toBe('2022-03-14')
    expect(sent.form.get('imaging_view')).toBe('AP standing')
    expect(sent.form.get('affected_side')).toBe('Right')
    expect(sent.form.get('file').name).toBe('knee.webp')
  })

  it('leaves the request exactly as before when they are blank', async () => {
    await analyze(file, { ...patient, synthetic_patient_id: '', examined_date: '', imaging_view: '' })
    for (const k of ['synthetic_patient_id', 'examined_date', 'imaging_view']) expect(sent.form.has(k)).toBe(false)
    expect([...sent.form.keys()].sort()).toEqual(['affected_side', 'age', 'file', 'imaging_type', 'name', 'sex'])
  })
})
