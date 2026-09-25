import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CONFIDENCE_HIGH,
  CONFIDENCE_MEDIUM,
  confidenceBadgeClass,
  confidenceBand,
} from '../src/utils/confidence.js'


test('bands follow the calibrated thresholds', () => {
  assert.equal(confidenceBand(0.95), 'high')
  assert.equal(confidenceBand(0.75), 'high')
  assert.equal(confidenceBand(0.74), 'medium')
  assert.equal(confidenceBand(0.5), 'medium')
  assert.equal(confidenceBand(0.45), 'low')
  assert.equal(confidenceBand(0.0), 'low')
})


test('non-numeric confidence renders no badge', () => {
  assert.equal(confidenceBand(undefined), null)
  assert.equal(confidenceBand(null), null)
  assert.equal(confidenceBand('nonsense'), null)
  assert.equal(confidenceBand(NaN), null)
  assert.equal(confidenceBadgeClass(undefined), null)
})


test('badge classes map to the semantic colors', () => {
  assert.equal(confidenceBadgeClass(0.9), 'badge badge-green')
  assert.equal(confidenceBadgeClass(0.6), 'badge badge-yellow')
  assert.equal(confidenceBadgeClass(0.2), 'badge badge-red')
})


test('thresholds match the backend calibration contract', () => {
  // calibrate_confidence: cited answers >= 0.5 (0.35 + 0.55*semantic), cap 0.95;
  // uncited answers cap at 0.45 -> 'low'. Keep the UI bands in sync with that.
  assert.ok(CONFIDENCE_HIGH >= 0.7 && CONFIDENCE_HIGH < 0.95)
  assert.ok(CONFIDENCE_MEDIUM > 0.45)
  assert.equal(confidenceBand(0.45), 'low')  // the uncited cap
})
