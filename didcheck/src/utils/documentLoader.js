/**
 * Browser-compatible document loader for JSON-LD processing
 * Resolves contexts and DID documents for VC verification
 */

import * as credentialsContext from '@digitalbazaar/credentials-context'
import * as multikeyContext from '@digitalbazaar/multikey-context'

// Import bundled contexts
import credentialsV1Context from '@/assets/contexts/credentials-v1.json'
import dataIntegrityV2Context from '@/assets/contexts/data-integrity-v2.json'
import digitalArtefactsV1Context from '@/assets/contexts/digital-artefacts-v1.json'

// Cache for fetched DID documents
const didDocumentCache = new Map()

/**
 * Clear the DID document cache
 * Useful for testing or when DID documents might have changed
 */
export function clearDocumentCache() {
  didDocumentCache.clear()
}

/**
 * Custom document loader for Verifiable Credentials verification
 *
 * Resolves:
 * - JSON-LD contexts from @digitalbazaar packages
 * - Bundled local contexts (credentials, data-integrity, digital-artefacts)
 * - did:web:did.amd.com:{division} DID documents via API
 * - Verification method fragments (e.g., did:web:did.amd.com:advisory#key20260216)
 *
 * @param {string} url - The URL to load
 * @returns {Promise<{contextUrl: null, document: object, documentUrl: string}>}
 */
export async function documentLoader(url) {
  // 1. Handle credentials context from @digitalbazaar/credentials-context
  const context = credentialsContext.contexts.get(url)
  if (context) {
    return { contextUrl: null, document: context, documentUrl: url }
  }

  // 2. Handle multikey context from @digitalbazaar/multikey-context
  if (url === multikeyContext.constants.CONTEXT_URL) {
    return {
      contextUrl: null,
      document: multikeyContext.contexts.get(url),
      documentUrl: url
    }
  }

  // 3. Handle bundled contexts with explicit URL mapping
  if (url === 'https://www.w3.org/2018/credentials/v1') {
    return { contextUrl: null, document: credentialsV1Context, documentUrl: url }
  }
  if (url === 'https://w3id.org/security/data-integrity/v2') {
    return { contextUrl: null, document: dataIntegrityV2Context, documentUrl: url }
  }
  if (url === 'https://did.amd.com/contexts/digitalArtefacts/v1') {
    return { contextUrl: null, document: digitalArtefactsV1Context, documentUrl: url }
  }

  // 4. Handle did:web:did.amd.com:{division} DID resolution
  if (url.startsWith('did:web:did.amd.com:')) {
    return await resolveDIDWeb(url)
  }

  // 5. Fallback: throw error for unresolved URLs
  throw new Error(`Unable to load document: ${url}`)
}

/**
 * Resolve a did:web:did.amd.com:{division} DID or verification method
 *
 * @param {string} url - The DID or verification method URL
 * @returns {Promise<{contextUrl: null, document: object, documentUrl: string}>}
 */
async function resolveDIDWeb(url) {
  // Extract division from DID
  // e.g., "did:web:did.amd.com:advisory#key123" -> "advisory"
  // e.g., "did:web:did.amd.com:advisory" -> "advisory"
  const didWithoutFragment = url.split('#')[0]
  const division = didWithoutFragment.replace('did:web:did.amd.com:', '')

  // Check if this looks like a division (simple string) vs a UUID artefact DID
  // Division names are lowercase letters, digits, underscores, starting with a letter
  const isDivision = /^[a-z][a-z0-9_]*$/.test(division)

  if (!isDivision) {
    throw new Error(`Cannot resolve DID: ${url} - only division DIDs are supported for verification`)
  }

  // Check cache first
  if (!didDocumentCache.has(division)) {
    // Fetch from backend API
    const response = await fetch(`/api/${division}/did.json`)
    if (!response.ok) {
      throw new Error(`Failed to fetch DID document for division: ${division} (HTTP ${response.status})`)
    }
    const didDocument = await response.json()
    didDocumentCache.set(division, didDocument)
  }

  const didDocument = didDocumentCache.get(division)

  // If requesting a specific verification method (URL has fragment)
  if (url.includes('#')) {
    const fragment = url.split('#')[1]

    // Find the verification method in the DID document
    const vm = didDocument.verificationMethod?.find(vm =>
      vm.id === url || vm.id === `#${fragment}` || vm.id.endsWith(`#${fragment}`)
    )

    if (vm) {
      // Include context in the verification method for proper suite matching
      const vmWithContext = {
        '@context': didDocument['@context'],
        ...vm
      }
      return {
        contextUrl: null,
        document: vmWithContext,
        documentUrl: url
      }
    }

    throw new Error(`Verification method not found: ${url}`)
  }

  // Return the full DID document
  return { contextUrl: null, document: didDocument, documentUrl: url }
}

export default {
  documentLoader,
  clearDocumentCache
}
