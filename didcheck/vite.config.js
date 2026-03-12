import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import path from 'path'
import viteCompression from 'vite-plugin-compression2'

import fs from 'fs'
import crypto from 'crypto'
import zlib from 'zlib'

/*
// Custom plugin to copy context files to assets
function copyContextFilesPlugin() {
  return {
    name: 'copy-context-files',
    apply: 'build',
    generateBundle(options) {
      const contextDir = path.resolve(__dirname, '../contexts')

      // Read all files in the contexts directory
      const files = fs.readdirSync(contextDir)

      // Filter for .json files and copy them
      files.forEach(file => {
        if (file.endsWith('.json')) {
          const filePath = path.join(contextDir, file)
          const content = fs.readFileSync(filePath, 'utf-8')

          // Generate SHA256 hash of the content for cache busting
          const hash = crypto.createHash('sha256').update(content).digest('hex').substring(0, 8)

          // Create filename with hash: credentials-v1.<hash>.json
          const baseName = file.replace('.json', '')
          const hashedFileName = `${baseName}.${hash}.json`

          // Emit uncompressed version
          this.emitFile({
            type: 'asset',
            fileName: `contexts/${hashedFileName}`,
            source: content
          })

          // Emit gzip compressed version: credentials-v1.<hash>.json.gz
          const compressed = zlib.gzipSync(content)
          this.emitFile({
            type: 'asset',
            fileName: `contexts/${hashedFileName}.gz`,
            source: compressed
          })
        }
      })
    }
  }
}
  */

function viteCompressionPlugin() {
    // gzip + brotli in one plugin
    return viteCompression({
      include: [/\.(js|mjs|css|html|svg|json|jsonld|wasm)$/i],
      threshold: 0,
      // Generate gzip
      gzip: true,
      // Brotli ignored for now (alpine-nginx-slim doesn't ship with module).
      // brotli: true,
      // Keep original files
      deleteOriginalAssets: false,
    })
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load .env from project root (parent directory)
  const rootEnv = loadEnv(mode, path.resolve(__dirname, '..'), '')

  // Use token from .env or fallback to dev default
  const didcheckToken = rootEnv.DIDCHECK_ACCESS_TOKEN || 'dev-token-12345'

  return {
    plugins: [vue(), viteCompressionPlugin() /*, copyContextFilesPlugin()*/],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@contexts': fileURLToPath(new URL('../contexts', import.meta.url))
      }
    },
    server: {
      proxy: { // Upstream proxy to /api.
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
