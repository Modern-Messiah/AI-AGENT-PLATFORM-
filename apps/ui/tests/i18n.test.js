import test from 'node:test'
import assert from 'node:assert/strict'

import {
  formatLocaleDate,
  localeTag,
  normalizeLocale,
  translate,
} from '../src/i18n/index.js'


test('normalizes supported interface locales', () => {
  assert.equal(normalizeLocale('en'), 'en')
  assert.equal(normalizeLocale('ru-RU'), 'ru')
  assert.equal(normalizeLocale('de'), 'ru')
  assert.equal(localeTag('en'), 'en-US')
})


test('translates keys and interpolates named parameters', () => {
  assert.equal(translate('ru', 'common.cancel'), 'Отмена')
  assert.equal(translate('en', 'common.cancel'), 'Cancel')
  assert.equal(
    translate('en', 'documents.readyCount', { ready: 3, total: 5 }),
    '3 of 5 ready for answers in all chats',
  )
})


test('describes GitHub URL checks without technical file counts', () => {
  assert.equal(
    translate('ru', 'documents.githubReady', { files: 100, images: 8 }),
    'Источник подходит',
  )
  assert.equal(
    translate('en', 'documents.githubReady', { files: 100, images: 8 }),
    'Source is ready',
  )
})


test('falls back to Russian text for an unknown key or locale', () => {
  assert.equal(translate('de', 'common.save'), 'Сохранить')
  assert.equal(translate('en', 'missing.translation'), 'missing.translation')
})


test('formats dates using the selected interface locale', () => {
  const date = '2026-06-07T09:00:00Z'
  assert.equal(formatLocaleDate(date, 'ru'), '07.06.2026')
  assert.equal(formatLocaleDate(date, 'en'), '06/07/2026')
})


test('translates the theme picker and every available theme', () => {
  assert.equal(translate('ru', 'settings.theme'), 'Тема интерфейса')
  assert.equal(translate('en', 'settings.theme'), 'Interface theme')
  assert.equal(translate('ru', 'settings.themeGraphite'), 'Графит')
  assert.equal(translate('en', 'settings.themeGraphite'), 'Graphite')
  assert.equal(translate('ru', 'settings.themePine'), 'Хвоя')
  assert.equal(translate('en', 'settings.themePine'), 'Pine')
  assert.equal(translate('ru', 'settings.themePlum'), 'Сливовая схема')
  assert.equal(translate('en', 'settings.themePlum'), 'Plum Circuit')
  assert.equal(translate('ru', 'settings.themePorcelain'), 'Фарфор')
  assert.equal(translate('en', 'settings.themePorcelain'), 'Porcelain')
  assert.equal(translate('ru', 'settings.themeDaylight'), 'Дневной свет')
  assert.equal(translate('en', 'settings.themeDaylight'), 'Daylight')
})
