import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildCitationDocumentRoute,
  buildCitationRoute,
  citationIsReferenced,
  citationGroupIsReferenced,
  citationGroupLabel,
  citationGroupMarker,
  groupCitationsByDocument,
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


test('groups multiple citation fragments from the same document', () => {
  const groups = groupCitationsByDocument([
    { ...citation, id: 1, chunk_id: 'chunk-1', chunk_index: 0 },
    { ...citation, id: 2, chunk_id: 'chunk-2', chunk_index: 2 },
    { ...citation, id: 3, document_id: 'document-2', filename: 'other.pdf' },
    'legacy.txt',
  ])

  assert.equal(groups.length, 3)
  assert.equal(groups[0].type, 'document')
  assert.equal(groups[0].filename, 'corporate-contract.pdf')
  assert.equal(groups[0].fragmentCount, 2)
  assert.deepEqual(groups[0].citations.map(item => item.chunk_id), ['chunk-1', 'chunk-2'])
  assert.equal(citationGroupMarker(groups[0]), '[1-2]')
  assert.equal(citationGroupLabel(groups[0]), '2 фрагмента')
  assert.equal(citationGroupIsReferenced('Answer uses [2].', groups[0]), true)
  assert.equal(citationGroupIsReferenced('Answer uses [3].', groups[0]), false)
  assert.deepEqual(buildCitationDocumentRoute(groups[0]), { path: '/documents/document-1' })
  assert.equal(groups[2].type, 'legacy')
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
