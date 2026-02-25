<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDIDStore } from '@/stores/did'
import { validateVCStructure } from '@/utils/vcValidation'
import NewerVersionAlert from '@/components/NewerVersionAlert.vue'
import DebugCanonicalization from '@/components/DebugCanonicalization.vue'
import { DEBUG_CANONICALIZATION_ENABLED } from '@/utils/featureFlags.js'

// Props from router
const props = defineProps({
  validationId: {
    type: String,
    required: true
  }
})

const router = useRouter()
const didStore = useDIDStore()

// State
const vcData = ref(null)
const vcFilename = ref(null)
const parseError = ref(null)
const validationResult = ref(null)
const loading = ref(true)
const fetchingOverview = ref(false)
const overviewData = ref(null)
const overviewError = ref(null)

// Storage key helpers using validation ID
const storageKey = (suffix) => `vc-${props.validationId}-${suffix}`

// Save validation results to sessionStorage for browser back/forward
const saveResultsToStorage = () => {
  if (validationResult.value) {
    sessionStorage.setItem(storageKey('result'), JSON.stringify(validationResult.value))
  }
  if (overviewData.value) {
    sessionStorage.setItem(storageKey('overview'), JSON.stringify(overviewData.value))
  }
  if (overviewError.value) {
    sessionStorage.setItem(storageKey('overviewError'), overviewError.value)
  }
  // Save vcData only in debug mode for canonicalization comparison
  if (DEBUG_CANONICALIZATION_ENABLED && vcData.value) {
    sessionStorage.setItem(storageKey('vcData'), JSON.stringify(vcData.value))
  }
}

// Try to restore cached results from sessionStorage
const restoreFromStorage = () => {
  const cachedResult = sessionStorage.getItem(storageKey('result'))
  const cachedFilename = sessionStorage.getItem(storageKey('filename'))

  if (cachedResult && cachedFilename) {
    try {
      validationResult.value = JSON.parse(cachedResult)
      vcFilename.value = cachedFilename

      const cachedOverview = sessionStorage.getItem(storageKey('overview'))
      if (cachedOverview) {
        overviewData.value = JSON.parse(cachedOverview)
      }

      const cachedOverviewError = sessionStorage.getItem(storageKey('overviewError'))
      if (cachedOverviewError) {
        overviewError.value = cachedOverviewError
      }

      // Restore vcData if in debug mode
      if (DEBUG_CANONICALIZATION_ENABLED) {
        const cachedVcData = sessionStorage.getItem(storageKey('vcData'))
        if (cachedVcData) {
          vcData.value = JSON.parse(cachedVcData)
        }
      }

      return true
    } catch {
      // If parsing fails, fall through to process file
    }
  }
  return false
}

// Computed properties
const latestVersion = computed(() => overviewData.value?.latest_version ?? null)
const digitalArtefact = computed(() => overviewData.value?.digital_artefact ?? null)

// Build DID from version_uid
const versionDID = computed(() => {
  if (!validationResult.value?.versionUid) return null
  return `did:web:did.amd.com:${validationResult.value.versionUid}`
})

const goHome = () => {
  router.push('/')
}

// Process the file from sessionStorage
const processFile = async () => {
  loading.value = true
  parseError.value = null
  validationResult.value = null
  overviewData.value = null
  overviewError.value = null

  try {
    // Get file content from sessionStorage using validation ID
    const fileContent = sessionStorage.getItem(storageKey('content'))
    vcFilename.value = sessionStorage.getItem(storageKey('filename'))

    if (!fileContent) {
      parseError.value = 'No VC file content provided. Please go back and select a file.'
      return
    }

    // Parse the JSON content
    try {
      vcData.value = JSON.parse(fileContent)
    } catch (err) {
      parseError.value = `Invalid JSON: ${err.message}`
      return
    }

    // Validate the VC structure (async - includes proof verification)
    validationResult.value = await validateVCStructure(vcData.value)

    // If we have a valid versionUid, fetch the overview
    if (validationResult.value.versionUid) {
      await fetchOverview(validationResult.value.versionUid)
    }

    // Save results to sessionStorage for browser back/forward
    saveResultsToStorage()

    // Clear raw content from storage - no longer needed after results are saved
    sessionStorage.removeItem(storageKey('content'))
  } finally {
    loading.value = false
  }
}

const fetchOverview = async (versionUid) => {
  fetchingOverview.value = true
  overviewError.value = null

  try {
    const data = await didStore.fetchOverviewByIdentifier(versionUid)
    overviewData.value = data
  } catch (err) {
    overviewError.value = err.message || 'Failed to fetch version information'
  } finally {
    fetchingOverview.value = false
  }
}

// Get the icon and color for a validation check
const getCheckIcon = (check) => {
  return check.passed
    ? { icon: 'mdi-check-circle', color: 'success' }
    : { icon: 'mdi-close-circle', color: 'error' }
}

onMounted(async () => {
  // Try to restore cached results from sessionStorage first (browser back/forward)
  if (restoreFromStorage()) {
    loading.value = false
    return
  }
  // Otherwise, process the file normally
  await processFile()
})
</script>

<template>
  <v-container>
    <v-row justify="center">
      <v-col cols="12" md="10" lg="8">
        <!-- Back button -->
        <v-btn
          variant="text"
          color="primary"
          class="mb-4"
          @click="goHome"
        >
          <v-icon start>mdi-arrow-left</v-icon>
          Back to Search
        </v-btn>

        <!-- Loading state -->
        <v-card v-if="loading" class="pa-6">
          <v-skeleton-loader type="article" />
        </v-card>

        <!-- Parse error state -->
        <v-alert
          v-else-if="parseError"
          type="error"
          variant="tonal"
          class="mb-4"
        >
          <v-alert-title>Failed to Process VC</v-alert-title>
          {{ parseError }}
        </v-alert>

        <!-- Validation Results -->
        <template v-else-if="validationResult">
          <!-- Validation Status Card -->
          <v-card class="mb-4">
            <v-card-title class="d-flex align-center">
              <v-icon start :color="validationResult.valid ? 'success' : 'error'">
                {{ validationResult.valid ? 'mdi-check-decagram' : 'mdi-alert-decagram' }}
              </v-icon>
              VC Validation Results
              <v-chip
                :color="validationResult.valid ? 'success' : 'error'"
                size="small"
                class="ml-3"
              >
                {{ validationResult.valid ? 'Valid' : 'Invalid' }}
              </v-chip>
            </v-card-title>

            <v-card-text>
              <v-list density="compact">
                <v-list-item
                  v-for="(check, index) in validationResult.checks"
                  :key="index"
                  class="px-0"
                >
                  <template #prepend>
                    <v-icon
                      :icon="getCheckIcon(check).icon"
                      :color="getCheckIcon(check).color"
                      size="small"
                      class="mr-3"
                    />
                  </template>
                  <v-list-item-title class="font-weight-medium">
                    {{ check.name }}
                  </v-list-item-title>
                  <v-list-item-subtitle>
                    {{ check.message }}
                  </v-list-item-subtitle>
                  <template v-if="check.value" #append>
                    <code class="text-caption text-grey-darken-1">{{ check.value }}</code>
                  </template>
                </v-list-item>
              </v-list>
            </v-card-text>
          </v-card>

          <!-- Version UID Link Card (if we have a valid versionUid) -->
          <v-card v-if="validationResult.versionUid" class="mb-4">
            <v-card-title class="d-flex align-center">
              <v-icon start>mdi-identifier</v-icon>
              Version Reference
            </v-card-title>
            <v-card-text>
              <div class="text-subtitle-2 text-grey mb-1">Version DID</div>
              <div class="d-flex align-center">
                <router-link
                  :to="`/${validationResult.versionUid}`"
                  class="text-primary text-mono"
                >
                  {{ versionDID }}
                </router-link>
                <router-link
                  :to="`/${validationResult.versionUid}`"
                  class="ml-3 text-primary text-decoration-none d-inline-flex align-center"
                >
                  <v-icon size="small" class="mr-1">mdi-open-in-new</v-icon>
                  View Details
                </router-link>
              </div>
            </v-card-text>
          </v-card>

          <!-- Overview Loading -->
          <v-card v-if="fetchingOverview" class="mb-4 pa-4">
            <v-progress-circular indeterminate color="primary" size="24" class="mr-3" />
            Fetching version information...
          </v-card>

          <!-- Overview Error -->
          <v-alert
            v-else-if="overviewError"
            type="warning"
            variant="tonal"
            class="mb-4"
          >
            <v-alert-title>Could not fetch version information</v-alert-title>
            {{ overviewError }}
          </v-alert>

          <!-- Newer Version Alert -->
          <NewerVersionAlert
            v-if="latestVersion"
            :latest-version="latestVersion"
          />

          <!-- Digital Artefact Info (if fetched successfully) -->
          <v-card v-if="digitalArtefact" class="mb-4">
            <v-card-title class="d-flex align-center">
              <v-icon start>mdi-file-document-check-outline</v-icon>
              Registered Artefact Information
            </v-card-title>
            <v-card-text>
              <v-row>
                <v-col cols="12" sm="4">
                  <div class="text-subtitle-2 text-grey">Version</div>
                  <div class="text-body-1 mt-1 font-weight-medium">
                    {{ digitalArtefact.version }}
                  </div>
                </v-col>
                <v-col cols="12" sm="4">
                  <div class="text-subtitle-2 text-grey">Creation Date</div>
                  <div class="text-body-1 mt-1 font-weight-medium">
                    {{ new Date(digitalArtefact.creation_date).toLocaleDateString() }}
                  </div>
                </v-col>
                <v-col cols="12" sm="4">
                  <div class="text-subtitle-2 text-grey">Division</div>
                  <div class="text-body-1 mt-1 font-weight-medium">
                    {{ digitalArtefact.division }}
                  </div>
                </v-col>
              </v-row>
              <v-row v-if="digitalArtefact.revoked" class="mt-2">
                <v-col cols="12">
                  <v-chip color="error" size="small">
                    <v-icon start size="small">mdi-cancel</v-icon>
                    Revoked
                  </v-chip>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- Debug Canonicalization Panel (dev mode only) -->
          <DebugCanonicalization
            v-if="DEBUG_CANONICALIZATION_ENABLED && validationResult.versionUid && vcData"
            :vc-data="vcData"
            :version-uid="validationResult.versionUid"
          />
        </template>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
code {
  background-color: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.text-mono {
  font-family: monospace;
}
</style>
