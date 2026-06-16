export function isStructuredCitation(source) {
  return Boolean(
    source
    && typeof source === 'object'
    && Number.isInteger(source.id)
    && typeof source.filename === 'string'
    && typeof source.excerpt === 'string'
  )
}

export function hasAssetPreview(source) {
  return Boolean(
    isStructuredCitation(source)
    && source.preview_available === true
    && typeof source.document_id === 'string'
    && source.document_id
    && typeof source.asset_id === 'string'
    && source.asset_id
  )
}

export function assetPreviewPath(source) {
  if (!hasAssetPreview(source)) return null
  return `/documents/${encodeURIComponent(source.document_id)}/assets/${encodeURIComponent(source.asset_id)}/content`
}

export function sourceLocation(source, locale = 'ru') {
  if (!isStructuredCitation(source)) return ''
  if (Number.isInteger(source.page) && source.page > 0) {
    return translate(locale, 'citations.page', { page: source.page })
  }
  return translate(locale, 'citations.fragment', { index: (source.chunk_index ?? 0) + 1 })
}

export function sourceLabel(source, locale = 'ru') {
  if (!isStructuredCitation(source)) return String(source ?? '')
  const location = Number.isInteger(source.page) && source.page > 0
    ? translate(locale, 'citations.pageShort', { page: source.page })
    : translate(locale, 'citations.fragmentShort', { index: (source.chunk_index ?? 0) + 1 })
  return `[${source.id}] ${source.filename} · ${location}`
}

export function sourceScoreLabel(source, locale = 'ru') {
  if (!isStructuredCitation(source)) return ''
  const score = Number(source.score)
  if (!Number.isFinite(score)) return translate(locale, 'citations.relevanceEmpty')

  const percent = score <= 1 ? score * 100 : score
  const clamped = Math.max(0, Math.min(100, Math.round(percent)))
  return translate(locale, 'citations.relevance', { percent: clamped })
}

function fragmentPlural(count, locale = 'ru') {
  if (locale === 'en') {
    return translate(locale, count === 1 ? 'citations.oneFragment' : 'citations.manyFragments')
  }
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return translate(locale, 'citations.oneFragment')
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return translate(locale, 'citations.fewFragments')
  return translate(locale, 'citations.manyFragments')
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

export function citationGroupLabel(group, locale = 'ru') {
  if (!group || group.type !== 'document') return ''
  if (group.fragmentCount === 1) return sourceLocation(group.citations[0], locale).toLowerCase()
  return `${group.fragmentCount} ${fragmentPlural(group.fragmentCount, locale)}`
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
import { translate } from '../i18n/index.js'
