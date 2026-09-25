// Bands for the calibrated confidence the backend attaches to answers
// (calibrate_confidence: retrieval-score derived, capped 0.95; answers
// without cited sources cap at 0.45). Messages without a numeric
// confidence (welcome notes, errors) show no badge at all.

export const CONFIDENCE_HIGH = 0.75
export const CONFIDENCE_MEDIUM = 0.5

export function confidenceBand(value) {
  // Number(null) === 0 and Number('') === 0 — reject empties explicitly
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  if (num >= CONFIDENCE_HIGH) return 'high'
  if (num >= CONFIDENCE_MEDIUM) return 'medium'
  return 'low'
}

export function confidenceBadgeClass(value) {
  const band = confidenceBand(value)
  if (!band) return null
  return {
    high: 'badge badge-green',
    medium: 'badge badge-yellow',
    low: 'badge badge-red',
  }[band]
}
