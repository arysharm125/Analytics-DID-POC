/**
 * Feature flags for DIDCheck
 *
 * Uses Vite's built-in environment detection to enable/disable features
 * based on the build mode (development vs production).
 */

/**
 * Debug canonicalization feature
 * - Enabled in development (npm run dev)
 * - Disabled in production builds (npm run build)
 */
export const DEBUG_CANONICALIZATION_ENABLED = import.meta.env.DEV

export default {
  DEBUG_CANONICALIZATION_ENABLED
}
