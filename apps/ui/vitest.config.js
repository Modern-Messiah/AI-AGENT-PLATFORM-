import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

// Render tests for the component layer (markdown chat rendering, badges,
// modals). Run with: npm run test:render — needs the DOM (happy-dom).
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/render/**/*.spec.js'],
  },
})
