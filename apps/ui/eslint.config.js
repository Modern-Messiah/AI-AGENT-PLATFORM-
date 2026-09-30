import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**'],
  },
  js.configs.recommended,
  // essential = correctness rules only; template formatting stays with the
  // editor (the codebase predates ESLint and has its own consistent style).
  ...pluginVue.configs['flat/essential'],
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser },
    },
  },
  {
    files: ['tests/**/*.js', 'scripts/**/*.js', '*.config.js', 'e2e/**/*.js'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    rules: {
      // try {} catch {} around localStorage/sessionStorage is the deliberate
      // "storage may not exist" pattern across stores and utils.
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
]
