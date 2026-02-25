<script setup>
import { ref, computed, onMounted } from 'vue'
import { canonicalizeVC } from '@/utils/proofVerification.js'
import { fetchCanonicalizedVC } from '@/services/api.js'

const props = defineProps({
  vcData: {
    type: Object,
    required: true
  },
  versionUid: {
    type: String,
    required: true
  }
})

// State
const expanded = ref(false)
const loading = ref(false)
const backendNquads = ref(null)
const frontendNquads = ref(null)
const backendError = ref(null)
const frontendError = ref(null)

// Computed
const nquadsMatch = computed(() => {
  if (!backendNquads.value || !frontendNquads.value) return null
  return backendNquads.value === frontendNquads.value
})

const statusColor = computed(() => {
  if (nquadsMatch.value === null) return 'grey'
  return nquadsMatch.value ? 'success' : 'error'
})

const statusIcon = computed(() => {
  if (nquadsMatch.value === null) return 'mdi-help-circle'
  return nquadsMatch.value ? 'mdi-check-circle' : 'mdi-alert-circle'
})

const statusText = computed(() => {
  if (nquadsMatch.value === null) return 'Not compared'
  return nquadsMatch.value ? 'Canonicalization matches' : 'Canonicalization mismatch'
})

// Methods
const loadCanonicalization = async () => {
  if (backendNquads.value && frontendNquads.value) {
    return // Already loaded
  }

  loading.value = true
  backendError.value = null
  frontendError.value = null

  try {
    // Fetch backend canonicalization
    try {
      backendNquads.value = await fetchCanonicalizedVC(props.versionUid)
    } catch (err) {
      backendError.value = err.message || 'Failed to fetch backend N-Quads'
    }

    // Compute frontend canonicalization
    try {
      frontendNquads.value = await canonicalizeVC(props.vcData)
    } catch (err) {
      frontendError.value = err.message || 'Failed to canonicalize VC'
    }
  } finally {
    loading.value = false
  }
}

const copyToClipboard = async (text, label) => {
  try {
    await navigator.clipboard.writeText(text)
    // Could show a snackbar here if desired
  } catch (err) {
    console.error(`Failed to copy ${label}:`, err)
  }
}

const toggleExpanded = () => {
  expanded.value = !expanded.value
  if (expanded.value) {
    loadCanonicalization()
  }
}

// Auto-load on mount if already expanded
onMounted(() => {
  if (expanded.value) {
    loadCanonicalization()
  }
})
</script>

<template>
  <v-card class="mb-4">
    <v-card-title class="d-flex align-center cursor-pointer" @click="toggleExpanded">
      <v-icon start color="orange">mdi-bug</v-icon>
      Debug: VC Canonicalization
      <v-chip :color="statusColor" size="small" class="ml-3">
        <v-icon start :icon="statusIcon" size="small" />
        {{ statusText }}
      </v-chip>
      <v-spacer />
      <v-btn
        :icon="expanded ? 'mdi-chevron-up' : 'mdi-chevron-down'"
        variant="text"
        size="small"
      />
    </v-card-title>

    <v-expand-transition>
      <div v-show="expanded">
        <v-card-text>
          <v-alert type="info" variant="tonal" class="mb-4">
            <v-alert-title>Debug Tool</v-alert-title>
            This compares the canonicalized (N-Quads) representation of the VC between
            backend and frontend. Both should match for signature verification to work.
          </v-alert>

          <!-- Loading State -->
          <div v-if="loading" class="text-center pa-4">
            <v-progress-circular indeterminate color="primary" />
            <div class="mt-2 text-grey">Loading canonicalization...</div>
          </div>

          <!-- Comparison View -->
          <v-row v-else>
            <!-- Backend N-Quads -->
            <v-col cols="12" md="6">
              <div class="d-flex align-center mb-2">
                <h4>Backend N-Quads</h4>
                <v-spacer />
                <v-btn
                  v-if="backendNquads"
                  size="small"
                  variant="text"
                  prepend-icon="mdi-content-copy"
                  @click="copyToClipboard(backendNquads, 'backend')"
                >
                  Copy
                </v-btn>
              </div>

              <v-alert v-if="backendError" type="error" variant="tonal">
                {{ backendError }}
              </v-alert>

              <v-textarea
                v-else-if="backendNquads"
                :model-value="backendNquads"
                readonly
                variant="outlined"
                rows="15"
                class="monospace-text"
                hide-details
              />
            </v-col>

            <!-- Frontend N-Quads -->
            <v-col cols="12" md="6">
              <div class="d-flex align-center mb-2">
                <h4>Frontend N-Quads</h4>
                <v-spacer />
                <v-btn
                  v-if="frontendNquads"
                  size="small"
                  variant="text"
                  prepend-icon="mdi-content-copy"
                  @click="copyToClipboard(frontendNquads, 'frontend')"
                >
                  Copy
                </v-btn>
              </div>

              <v-alert v-if="frontendError" type="error" variant="tonal">
                {{ frontendError }}
              </v-alert>

              <v-textarea
                v-else-if="frontendNquads"
                :model-value="frontendNquads"
                readonly
                variant="outlined"
                rows="15"
                class="monospace-text"
                hide-details
              />
            </v-col>
          </v-row>
        </v-card-text>
      </div>
    </v-expand-transition>
  </v-card>
</template>

<style scoped>
.cursor-pointer {
  cursor: pointer;
}

.monospace-text :deep(textarea) {
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
}
</style>
