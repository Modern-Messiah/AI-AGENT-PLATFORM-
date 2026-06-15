import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { localeTag, translate } from '@/i18n'

export function useI18n() {
  const settings = useSettingsStore()
  const locale = computed({
    get: () => settings.locale,
    set: value => settings.setLocale(value),
  })
  const t = (key, params) => translate(settings.locale, key, params)

  return {
    locale,
    localeTag: computed(() => localeTag(settings.locale)),
    setLocale: settings.setLocale,
    t,
  }
}
