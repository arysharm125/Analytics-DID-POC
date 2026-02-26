import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env from project root (parent directory)
  const rootEnv = loadEnv(mode, path.resolve(__dirname, '..'), '')

  // Use token from .env or fallback to dev default
  const didcheckToken = rootEnv.DIDCHECK_ACCESS_TOKEN || 'dev-token-12345'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@contexts': fileURLToPath(new URL('../contexts', import.meta.url))
      }
    },
    server: {
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
          headers: {
            'X-API-Token': didcheckToken
          }
        }
      }
    }
  }
})
