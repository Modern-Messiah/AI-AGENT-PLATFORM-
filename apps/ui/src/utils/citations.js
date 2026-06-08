export function isStructuredCitation(source) {
  return Boolean(
    source
    && typeof source === 'object'
    && Number.isInteger(source.id)
    && typeof source.filename === 'string'
    && typeof source.excerpt === 'string'
  )
}

export function sourceLocation(source) {
  if (!isStructuredCitation(source)) return ''
  if (Number.isInteger(source.page) && source.page > 0) {
    return `Страница ${source.page}`
  }
  return `Фрагмент ${(source.chunk_index ?? 0) + 1}`
}

export function sourceLabel(source) {
  if (!isStructuredCitation(source)) return String(source ?? '')
  const location = Number.isInteger(source.page) && source.page > 0
    ? `стр. ${source.page}`
    : `фрагмент ${(source.chunk_index ?? 0) + 1}`
  return `[${source.id}] ${source.filename} · ${location}`
}

export function sourceScoreLabel(source) {
  if (!isStructuredCitation(source)) return ''
  const score = Number(source.score)
  if (!Number.isFinite(score)) return 'релевантность —'

  const percent = score <= 1 ? score * 100 : score
  const clamped = Math.max(0, Math.min(100, Math.round(percent)))
  return `релевантность ${clamped}%`
}

export function citationIsReferenced(answer, source) {
  if (!isStructuredCitation(source)) return false
  return String(answer ?? '').includes(`[${source.id}]`)
}

export function buildCitationRoute(source) {
  if (!isStructuredCitation(source) || !source.document_id) {
    return { path: '/documents' }
  }

  const route = { path: `/documents/${source.document_id}` }
  if (source.chunk_id) {
    route.query = { chunk: source.chunk_id }
  }
  return route
}
