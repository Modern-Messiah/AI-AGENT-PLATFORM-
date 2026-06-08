import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildCitationRoute,
  citationIsReferenced,
  isStructuredCitation,
  sourceLabel,
  sourceLocation,
  sourceScoreLabel,
} from '../src/utils/citations.js'


const citation = {
  id: 2,
  document_id: 'document-1',
  chunk_id: 'chunk-9',
  filename: 'corporate-contract.pdf',
  page: 8,
  chunk_index: 14,
  score: 0.567,
  excerpt: 'Exact supporting excerpt.',
}


test('recognizes structured and legacy sources', () => {
  assert.equal(isStructuredCitation(citation), true)
  assert.equal(isStructuredCitation('legacy.txt'), false)
})


test('formats citation labels without truncating filenames', () => {
  assert.equal(sourceLabel(citation), '[2] corporate-contract.pdf · стр. 8')
  assert.equal(sourceLocation(citation), 'Страница 8')
  assert.equal(sourceScoreLabel(citation), 'релевантность 57%')
  assert.equal(
    sourceLabel({ ...citation, page: null }),
    '[2] corporate-contract.pdf · фрагмент 15',
  )
})


test('detects whether the answer contains a citation marker', () => {
  assert.equal(citationIsReferenced('The answer is supported [2].', citation), true)
  assert.equal(citationIsReferenced('The answer has no marker.', citation), false)
})


test('builds route to the cited document chunk', () => {
  assert.deepEqual(buildCitationRoute(citation), {
    path: '/documents/document-1',
    query: { chunk: 'chunk-9' },
  })
})
