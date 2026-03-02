/**
 * Test document loader that uses fixtures instead of HTTP calls
 *
 * This loader resolves:
 * - JSON-LD contexts from @digitalbazaar packages and bundled contexts
 * - DID documents from fixture files (instead of API calls)
 * - Verification method fragments
 */

import { readFileSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import * as credentialsContext from '@digitalbazaar/credentials-context'
import * as multikeyContext from '@digitalbazaar/multikey-context'

// Import bundled contexts
import credentialsV1Context from '@contexts/credentials-v1.json' assert { type: 'json' }
import dataIntegrityV2Context from '@contexts/data-integrity-v2.json' assert { type: 'json' }
import digitalArtefactsV1Context from '@contexts/digital-artefacts-v1.json' assert { type: 'json' }

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Path to fixtures directory
const FIXTURES_DIR = path.resolve(__dirname, '../../../tests/fixtures/vc_compat')

// Cache for loaded DID documents
const didDocumentCache = new Map()

/**
 * Load a DID document from fixtures
 *
 * @param {string} division - The division name (e.g., 'advisory', 'epdw')
 * @returns {object} The DID document
 */
function loadDIDDocumentFromFixture(division) {
  if (didDocumentCache.has(division)) {
    return didDocumentCache.get(division)
  }

  const didFilePath = path.join(FIXTURES_DIR, `${division}_did.json`)

  try {
    const didDocument = JSON.parse(readFileSync(didFilePath, 'utf-8'))
    didDocumentCache.set(division, didDocument)
    return didDocument
  } catch (error) {
    throw new Error(
      `Failed to load DID document for division: ${division} from ${didFilePath}. ` +
      `Make sure to run 'pytest -m vc_compat' first to generate fixtures. Error: ${error.message}`
    )
  }
}

/**
 * Test document loader for VC verification
 *
 * @param {string} url - The URL to load
 * @returns {Promise<{contextUrl: null, document: object, documentUrl: string}>}
 */
export async function testDocumentLoader(url) {
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

  // 4. Handle did:web:did.amd.com:{division} DID resolution from fixtures
  if (url.startsWith('did:web:did.amd.com:')) {
    return await resolveDIDFromFixture(url)
  }

  // 5. Fallback: throw error for unresolved URLs
  throw new Error(`Unable to load document: ${url}`)
}

/**
 * Resolve a did:web:did.amd.com:{division} DID or verification method from fixtures
 *
 * @param {string} url - The DID or verification method URL
 * @returns {Promise<{contextUrl: null, document: object, documentUrl: string}>}
 */
async function resolveDIDFromFixture(url) {
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

  // Load DID document from fixture
  const didDocument = loadDIDDocumentFromFixture(division)

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

export default testDocumentLoader
