import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') }
  },
  build: {
    rollupOptions: {
      output: {
        // Split the heavy vendor libs out of the app chunk: the app code
        // changes on every release, vendors rarely — cached separately.
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia'],
          markdown: ['markdown-it', 'dompurify', 'highlight.js'],
          charts: ['chart.js'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, '')
      }
    }
  }
})
