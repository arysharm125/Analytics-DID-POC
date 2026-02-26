import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchArtefactOverview, fetchVC, fetchArtefact as fetchArtefactApi, fetchProvenance as fetchProvenanceApi, fetchArtefactVersions as fetchArtefactVersionsApi } from '@/services/api'

export const useDIDStore = defineStore('did', () => {
  // State
  const currentOverview = ref(null)
  const loading = ref(false)
  const error = ref(null)

  // Cache for previously fetched overviews
  const overviewCache = ref(new Map())

  /**
   * Fetch artefact overview by identifier (DID string or UID)
   * @param {string} identifier
   * @returns {Promise<Object>} Overview data with digital_artefact and optional latest_version
   */
  async function fetchOverviewByIdentifier(identifier) {
    loading.value = true
    error.value = null

    try {
      // Check cache first
      if (overviewCache.value.has(identifier)) {
        currentOverview.value = overviewCache.value.get(identifier)
        return currentOverview.value
      }

      const data = await fetchArtefactOverview(identifier)
      currentOverview.value = data

      // Cache the result
      overviewCache.value.set(identifier, data)

      return data
    } catch (err) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Issue a Verifiable Credential for the given identifier
   * @param {string} identifier - DID string or UID
   * @returns {Promise<Object>} The issued VC
   */
  async function issueVC(identifier) {
    return await fetchVC(identifier)
  }

  /**
   * Fetch full artefact data (including metadata) for the given identifier
   * @param {string} identifier - DID string or UID
   * @returns {Promise<Object>} The full artefact data
   */
  async function fetchArtefact(identifier) {
    return await fetchArtefactApi(identifier)
  }

  /**
   * Fetch provenance tree for the given identifier
   * @param {string} identifier - DID string or UID
   * @param {Object} [options] - Optional query parameters
   * @param {number} [options.depth=3] - Maximum depth to recurse (1-10)
   * @param {number} [options.maxChildren=10] - Maximum children before truncating recursion (1-100)
   * @returns {Promise<Object>} The provenance tree response with root_uid, max_depth, max_children, and provenance array
   */
  async function fetchProvenance(identifier, options = {}) {
    return await fetchProvenanceApi(identifier, options)
  }

  /**
   * Fetch all versions of an artefact for the given identifier
   * @param {string} identifier - DID string or UID
   * @returns {Promise<Object>} The versions response with external_uid and versions array
   */
  async function fetchVersions(identifier) {
    return await fetchArtefactVersionsApi(identifier)
  }

  /**
   * Clear the current overview data
   */
  function clearCurrent() {
    currentOverview.value = null
    error.value = null
  }

  /**
   * Clear the cache
   */
  function clearCache() {
    overviewCache.value.clear()
  }

  return {
    // State
    currentOverview,
    loading,
    error,

    // Actions
    fetchOverviewByIdentifier,
    issueVC,
    fetchArtefact,
    fetchProvenance,
    fetchVersions,
    clearCurrent,
    clearCache
  }
})
