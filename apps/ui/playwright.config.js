import { defineConfig } from '@playwright/test'

// Browser e2e against a LIVE local stack:
//   docker compose up -d (API_PORT=8001 when 8000 is busy)
//   E2E_API_BASE_URL=http://127.0.0.1:8001 npx playwright test
// Requires ADMIN_SECRET (read from .env or the environment) to mint a
// throwaway tenant key. Not part of CI: CI has no live stack.
export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: process.env.E2E_UI_BASE_URL || 'http://localhost:5173',
    headless: true,
    locale: 'ru-RU',
  },
  reporter: [['list']],
  outputDir: './e2e/.artifacts',
})
