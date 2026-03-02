import { defineConfig } from 'vitest/config'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    // Only include tests in this directory
    include: ['**/*.test.js'],
    exclude: ['node_modules/**'],
  },
  resolve: {
    alias: {
      // Resolve @contexts to the contexts directory (three levels up)
      '@contexts': path.resolve(__dirname, '../../../contexts'),
      // Resolve @fixtures to the test fixtures directory
      '@fixtures': path.resolve(__dirname, '../../../tests/fixtures/vc_compat'),
    }
  }
})
