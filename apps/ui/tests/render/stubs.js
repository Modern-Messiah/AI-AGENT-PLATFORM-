// i18n stub for component render tests: resolves keys via the real
// dictionary so labels match production, params via {name} interpolation.
import { translate } from '../../src/i18n/index.js'

export function createI18nStub(locale = 'ru') {
  return (key, params) => translate(locale, key, params)
}
