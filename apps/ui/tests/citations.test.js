import test from 'node:test'
import assert from 'node:assert/strict'

import {
  citationIsReferenced,
  isStructuredCitation,
  sourceLabel,
  sourceLocation,
} from '../src/utils/citations.js'


const citation = {
  id: 2,
  filename: 'corporate-contract.pdf',
  page: 8,
  chunk_index: 14,
  excerpt: 'Exact supporting excerpt.',
}


test('recognizes structured and legacy sources', () => {
  assert.equal(isStructuredCitation(citation), true)
  assert.equal(isStructuredCitation('legacy.txt'), false)
})


test('formats citation labels without truncating filenames', () => {
  assert.equal(sourceLabel(citation), '[2] corporate-contract.pdf · стр. 8')
  assert.equal(sourceLocation(citation), 'Страница 8')
  assert.equal(
    sourceLabel({ ...citation, page: null }),
    '[2] corporate-contract.pdf · фрагмент 15',
  )
})


test('detects whether the answer contains a citation marker', () => {
  assert.equal(citationIsReferenced('The answer is supported [2].', citation), true)
  assert.equal(citationIsReferenced('The answer has no marker.', citation), false)
})
