/**
 * API Service for communicating with the DID backend
 *
 * The Vite proxy configuration routes /api/* to the backend,
 * stripping the /api prefix.
 */

import { useAuthStore } from '@/stores/auth'

const API_BASE = '/api'

/**
 * Generic fetch wrapper with error handling and authentication
 */
async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`
  const authStore = useAuthStore()

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers
  }

  // Add Bearer token if authenticated
  if (authStore.accessToken) {
    headers['Authorization'] = `Bearer ${authStore.accessToken}`
  }

  const response = await fetch(url, { ...options, headers })

  // Handle 401 Unauthorized - redirect to login
  if (response.status === 401) {
    authStore.logout()
    authStore.redirectToLogin()
    throw new Error('Authentication required')
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || errorData.message || `HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * Fetch DID/UID information by identifier
 * @param {string} identifier - DID string or UID
 * @returns {Promise<Object>} DID data
 */
export async function fetchDIDByIdentifier(identifier) {
  // Determine if it's a DID or UID and use appropriate endpoint
  return request(`/did/${encodeURIComponent(identifier)}`)
}

/**
 * Fetch artefact overview by identifier
 * @param {string} identifier - DID string or UID
 * @returns {Promise<Object>} Artefact overview with digital_artefact and optional latest_version
 */
export async function fetchArtefactOverview(identifier) {
  return request(`/didcheck/${encodeURIComponent(identifier)}/overview`)
}

/**
 * Fetch a Verifiable Credential by DID or UID.
 * @param {string} did_or_uid - The VC identifier
 * @returns {Promise<Object>} The VC
 */
export async function fetchVC(did_or_uid) {
  return request(`/didcheck/${encodeURIComponent(did_or_uid)}/vc.json`)
}

/**
 * Fetch full artefact data (including metadata) by DID or UID.
 * @param {string} did_or_uid - The artefact identifier
 * @returns {Promise<Object>} The full artefact data
 */
export async function fetchArtefact(did_or_uid) {
  return request(`/didcheck/${encodeURIComponent(did_or_uid)}/artefact.json`)
}

/**
 * Fetch recursive provenance tree by DID or UID.
 * @param {string} did_or_uid - The artefact identifier
 * @param {Object} [options] - Optional query parameters
 * @param {number} [options.depth=3] - Maximum depth to recurse (1-10)
 * @param {number} [options.maxChildren=10] - Maximum children before truncating recursion (1-100)
 * @returns {Promise<Object>} The provenance tree response with root_uid, max_depth, max_children, and provenance array
 */
export async function fetchProvenance(did_or_uid, options = {}) {
  const params = new URLSearchParams()
  if (options.depth !== undefined) {
    params.append('depth', options.depth)
  }
  if (options.maxChildren !== undefined) {
    params.append('max_children', options.maxChildren)
  }
  const queryString = params.toString()
  const endpoint = `/didcheck/${encodeURIComponent(did_or_uid)}/provenance${queryString ? `?${queryString}` : ''}`
  return request(endpoint)
}

/**
 * Fetch all versions of an artefact by DID or UID.
 * @param {string} did_or_uid - The artefact identifier
 * @returns {Promise<Object>} The versions response with external_uid and versions array
 */
export async function fetchArtefactVersions(did_or_uid) {
  return request(`/didcheck/${encodeURIComponent(did_or_uid)}/versions`)
}

/**
 * Fetch paginated descendants of an artefact by DID or UID.
 * @param {string} did_or_uid - The artefact identifier
 * @param {Object} [options] - Optional query parameters
 * @param {number} [options.page=1] - Page number (1-indexed)
 * @param {number} [options.pageSize=20] - Items per page (1-100)
 * @returns {Promise<Object>} The descendants response with descendants array and pagination metadata
 */
export async function fetchDescendants(did_or_uid, options = {}) {
  const params = new URLSearchParams()
  if (options.page !== undefined) {
    params.append('page', options.page)
  }
  if (options.pageSize !== undefined) {
    params.append('page_size', options.pageSize)
  }
  const queryString = params.toString()
  const endpoint = `/didcheck/${encodeURIComponent(did_or_uid)}/descendants${queryString ? `?${queryString}` : ''}`
  return request(endpoint)
}

/**
 * Check the status of a DID
 * @param {string} identifier - DID or UID
 * @returns {Promise<Object>} Status information
 */
export async function checkDIDStatus(identifier) {
  if (identifier.startsWith('did:')) {
    return request(`/didcheck/${encodeURIComponent(identifier)}/status`)
  } else {
    return request(`/didcheck/uid/${identifier}/status`)
  }
}

/**
 * Fetch canonicalized VC in N-Quads format (debug endpoint)
 * @param {string} uid - The VC identifier
 * @returns {Promise<string>} The canonicalized VC as N-Quads text
 */
export async function fetchCanonicalizedVC(uid) {
  const url = `${API_BASE}/didcheck/${encodeURIComponent(uid)}/vc.nq`

  const response = await fetch(url)

  if (!response.ok) {
    const errorText = await response.text().catch(() => '')
    throw new Error(errorText || `HTTP ${response.status}`)
  }

  return response.text()
}

/**
 * Fetch version diff between two artefact versions
 * @param {string} sourceUid - The base version UID (currently viewed version)
 * @param {string} targetUid - The version UID to compare against
 * @returns {Promise<Object>} The diff response with field-level differences
 */
export async function fetchVersionDiff(sourceUid, targetUid) {
  return request(`/didcheck/${encodeURIComponent(sourceUid)}/diff/${encodeURIComponent(targetUid)}`)
}

export default {
  fetchDIDByIdentifier,
  fetchArtefactOverview,
  fetchVC,
  fetchArtefact,
  fetchProvenance,
  fetchArtefactVersions,
  fetchDescendants,
  checkDIDStatus,
  fetchCanonicalizedVC,
  fetchVersionDiff
}
