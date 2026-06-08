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

function fragmentPlural(count) {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return 'фрагмент'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'фрагмента'
  return 'фрагментов'
}

export function groupCitationsByDocument(sources = []) {
  const groups = []
  const documentGroups = new Map()

  sources.forEach((source, index) => {
    if (!isStructuredCitation(source)) {
      groups.push({
        type: 'legacy',
        key: `legacy:${index}:${String(source ?? '')}`,
        label: String(source ?? ''),
        source,
      })
      return
    }

    const documentKey = source.document_id || source.filename || `citation:${source.id}`
    if (!documentGroups.has(documentKey)) {
      const group = {
        type: 'document',
        key: `document:${documentKey}`,
        documentId: source.document_id || null,
        filename: source.filename,
        citations: [],
        fragmentCount: 0,
      }
      documentGroups.set(documentKey, group)
      groups.push(group)
    }

    const group = documentGroups.get(documentKey)
    group.citations.push(source)
    group.fragmentCount = group.citations.length
  })

  return groups
}

export function citationGroupMarker(group) {
  if (!group || group.type !== 'document') return ''
  const ids = group.citations.map(source => source.id).filter(Number.isInteger)
  if (!ids.length) return ''
  const sorted = [...ids].sort((a, b) => a - b)
  const isRange = sorted.every((id, index) => index === 0 || id === sorted[index - 1] + 1)
  if (sorted.length > 1 && isRange) return `[${sorted[0]}-${sorted[sorted.length - 1]}]`
  return `[${sorted.join(',')}]`
}

export function citationGroupLabel(group) {
  if (!group || group.type !== 'document') return ''
  if (group.fragmentCount === 1) return sourceLocation(group.citations[0]).toLowerCase()
  return `${group.fragmentCount} ${fragmentPlural(group.fragmentCount)}`
}

export function citationGroupIsReferenced(answer, group) {
  if (!group || group.type !== 'document') return false
  return group.citations.some(source => citationIsReferenced(answer, source))
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

export function buildCitationDocumentRoute(group) {
  const firstCitation = group?.type === 'document' ? group.citations?.[0] : group
  if (!isStructuredCitation(firstCitation) || !firstCitation.document_id) {
    return { path: '/documents' }
  }
  return { path: `/documents/${firstCitation.document_id}` }
}
