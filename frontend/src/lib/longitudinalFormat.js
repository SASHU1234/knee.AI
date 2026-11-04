/** Presentation-only formatting for longitudinal values. Rounding happens here and nowhere else. */
export function fmtValue(v, unit, decimals = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return null
  return `${Number(v).toFixed(decimals)}${unit ? ` ${unit}` : ''}`
}

export function fmtSigned(v, unit, decimals = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return null
  const n = Number(v)
  const body = Math.abs(n).toFixed(decimals)
  // a difference that rounds to zero is shown unsigned so "-0.00" never appears
  const sign = Number(body) === 0 ? '' : n > 0 ? '+' : '-'
  return `${sign}${body}${unit ? ` ${unit}` : ''}`
}

export function fmtPct(v, decimals = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return null
  const body = Math.abs(Number(v)).toFixed(decimals)
  const sign = Number(body) === 0 ? '' : v > 0 ? '+' : '-'
  return `${sign}${body}%`
}

export const fmtDate = (iso) => (iso ? String(iso).slice(0, 10) : null)

/** Chart rows: actual examination dates and stored values; a missing value stays null (no interpolation). */
export function chartRows(points) {
  return points.map((p) => ({
    t: new Date(p.examined_at).getTime(),
    label: fmtDate(p.examined_at),
    value: p.value === undefined ? null : p.value,
    study_id: p.study_id,
  }))
}
