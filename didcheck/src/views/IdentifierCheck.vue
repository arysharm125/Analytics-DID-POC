<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDIDStore } from '@/stores/did'
import { verifyFileAgainstMultihash } from '@/utils/multihash'
import NewerVersionAlert from '@/components/NewerVersionAlert.vue'

const props = defineProps({
  identifier: {
    type: String,
    required: true
  }
})

const router = useRouter()
const didStore = useDIDStore()

const loading = ref(true)
const error = ref(null)
const overviewData = ref(null)
const issuingVC = ref(false)
const issuedVC = ref(null)
const fetchingArtefact = ref(false)
const fetchedArtefact = ref(null)
const fetchingProvenance = ref(false)
const fetchedProvenance = ref(null)
const fetchingVersions = ref(false)
const fetchedVersions = ref(null)
const fetchingDescendants = ref(false)
const fetchedDescendants = ref(null)
const descendantsPage = ref(1)

// Version diff state
const showDiffDialog = ref(false)
const fetchingDiff = ref(false)
const diffData = ref(null)
const compareVersionUid = ref(null)

// Binary file verification state
const selectedFile = ref(null)
const verificationStatus = ref(null) // null, 'verifying', 'success', 'error'
const verificationMessage = ref('')

// Digital artefact from overview response
const digitalArtefact = computed(() => overviewData.value?.digital_artefact ?? null)

// Whether the artefact has a hash for verification
const hasArtefactHash = computed(() => !!digitalArtefact.value?.artefact_hash)

// Latest version info (if newer version exists)
const latestVersion = computed(() => overviewData.value?.latest_version ?? null)

// Whether the artefact has provenance
const hasProvenance = computed(() => digitalArtefact.value?.has_provenance ?? false)

// Build the DID from external_uid
const displayDID = computed(() => {
  if (!digitalArtefact.value?.external_uid) return null
  return `did:web:did.amd.com:${digitalArtefact.value.external_uid}`
})

// Version UID formatted as DID
const versionDID = computed(() => {
  if (!digitalArtefact.value?.version_uid) return null
  return `did:web:did.amd.com:${digitalArtefact.value.version_uid}`
})

/**
 * Resets all artefact-specific state to initial values.
 * Should be called when navigating to a new identifier.
 */
const resetArtefactState = () => {
  // Verifiable Credential state
  issuedVC.value = null

  // Artefact metadata state
  fetchedArtefact.value = null

  // Provenance state
  fetchedProvenance.value = null

  // Versions state
  fetchedVersions.value = null

  // Descendants state
  fetchedDescendants.value = null
  descendantsPage.value = 1

  // File verification state
  selectedFile.value = null
  verificationStatus.value = null
  verificationMessage.value = ''
}

// Transform provenance tree to v-treeview format
const provenanceTreeItems = computed(() => {
  const provenance = fetchedProvenance.value?.provenance
  if (!provenance || provenance.length === 0) return []

  const transformNode = (node) => {
    const item = {
      id: node.uid,
      title: `did:web:did.amd.com:${node.uid}`,
      uid: node.uid,
      division: node.division,
      artefact_type: node.artefact_type,
      truncated: node.truncated,
    }
    if (node.children && node.children.length > 0) {
      item.children = node.children.map(transformNode)
    }
    return item
  }

  return provenance.map(transformNode)
})

const fetchIdentifierData = async () => {
  loading.value = true
  error.value = null
  resetArtefactState()

  try {
    const data = await didStore.fetchOverviewByIdentifier(props.identifier)
    overviewData.value = data
  } catch (err) {
    error.value = err.message || 'Failed to fetch identifier data'
    overviewData.value = null
  } finally {
    loading.value = false
  }
}

const issueVC = async () => {
  if (!digitalArtefact.value?.version_uid) return

  issuingVC.value = true
  try {
    const vc = await didStore.issueVC(digitalArtefact.value.version_uid)
    issuedVC.value = vc
  } catch (err) {
    error.value = err.message || 'Failed to issue Verifiable Credential'
  } finally {
    issuingVC.value = false
  }
}

const downloadVC = () => {
  if (!issuedVC.value) return

  const blob = new Blob([JSON.stringify(issuedVC.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `vc-${digitalArtefact.value.version_uid}.json`
  a.click()
  URL.revokeObjectURL(url)
}

const fetchArtefactData = async () => {
  if (!digitalArtefact.value?.version_uid) return

  fetchingArtefact.value = true
  try {
    const artefact = await didStore.fetchArtefact(digitalArtefact.value.version_uid)
    fetchedArtefact.value = artefact
  } catch (err) {
    error.value = err.message || 'Failed to fetch artefact data'
  } finally {
    fetchingArtefact.value = false
  }
}

const downloadArtefact = () => {
  if (!fetchedArtefact.value) return

  const blob = new Blob([JSON.stringify(fetchedArtefact.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `artefact-${digitalArtefact.value.version_uid}.json`
  a.click()
  URL.revokeObjectURL(url)
}

const fetchProvenanceData = async () => {
  if (!digitalArtefact.value?.version_uid) return

  fetchingProvenance.value = true
  try {
    const provenance = await didStore.fetchProvenance(digitalArtefact.value.version_uid)
    fetchedProvenance.value = provenance
  } catch (err) {
    error.value = err.message || 'Failed to fetch provenance data'
  } finally {
    fetchingProvenance.value = false
  }
}

const fetchVersionsData = async () => {
  if (!digitalArtefact.value?.version_uid) return

  fetchingVersions.value = true
  try {
    const versions = await didStore.fetchVersions(digitalArtefact.value.version_uid)
    fetchedVersions.value = versions
  } catch (err) {
    error.value = err.message || 'Failed to fetch versions data'
  } finally {
    fetchingVersions.value = false
  }
}

const fetchDescendantsData = async (page = 1) => {
  if (!digitalArtefact.value?.version_uid) return

  fetchingDescendants.value = true
  descendantsPage.value = page
  try {
    const descendants = await didStore.fetchDescendants(digitalArtefact.value.version_uid, {
      page: page,
      pageSize: 20
    })
    fetchedDescendants.value = descendants
  } catch (err) {
    error.value = err.message || 'Failed to fetch descendants data'
  } finally {
    fetchingDescendants.value = false
  }
}

const loadNextDescendantsPage = () => {
  if (fetchedDescendants.value?.has_more) {
    fetchDescendantsData(descendantsPage.value + 1)
  }
}

const loadPreviousDescendantsPage = () => {
  if (descendantsPage.value > 1) {
    fetchDescendantsData(descendantsPage.value - 1)
  }
}

const goHome = () => {
  router.push('/')
}

const navigateToVersion = (versionUid) => {
  router.push(`/did/${versionUid}`)
}

// Compare version with current version
const compareVersion = async (targetVersionUid) => {
  if (!digitalArtefact.value?.version_uid) return

  fetchingDiff.value = true
  diffData.value = null
  compareVersionUid.value = targetVersionUid
  showDiffDialog.value = true

  try {
    const diff = await didStore.fetchVersionDiff(
      digitalArtefact.value.version_uid,
      targetVersionUid
    )
    diffData.value = diff
  } catch (err) {
    error.value = err.message || 'Failed to fetch version diff'
    showDiffDialog.value = false
  } finally {
    fetchingDiff.value = false
  }
}

// Close diff dialog
const closeDiffDialog = () => {
  showDiffDialog.value = false
  diffData.value = null
  compareVersionUid.value = null
}

// Check if a field has changes in the diff
const hasDiffChanges = (diff) => {
  if (!diff) return false
  return !!(
    diff.artefact_hash ||
    diff.artefact_metadata ||
    diff.provenance ||
    diff.backlink ||
    diff.division ||
    diff.artefact_type
  )
}

// Handle file selection
const onFileSelected = (event) => {
  const files = event.target.files
  if (files && files.length > 0) {
    selectedFile.value = files[0]
    verificationStatus.value = null
    verificationMessage.value = ''
  }
}

// Verify the selected file against the artefact hash
const verifyFile = async () => {
  if (!selectedFile.value || !digitalArtefact.value?.artefact_hash) {
    return
  }

  verificationStatus.value = 'verifying'
  verificationMessage.value = 'Verifying file...'

  try {
    const result = await verifyFileAgainstMultihash(
      selectedFile.value,
      digitalArtefact.value.artefact_hash
    )

    if (result.success) {
      verificationStatus.value = 'success'
      verificationMessage.value = result.message
    } else {
      verificationStatus.value = 'error'
      verificationMessage.value = result.message
    }
  } catch (err) {
    verificationStatus.value = 'error'
    verificationMessage.value = `Verification failed: ${err.message}`
  }
}

// Clear file selection
const clearFile = () => {
  selectedFile.value = null
  verificationStatus.value = null
  verificationMessage.value = ''
}

onMounted(() => {
  fetchIdentifierData()
})

watch(() => props.identifier, () => {
  fetchIdentifierData()
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

        <!-- Error state -->
        <v-alert
          v-else-if="error"
          type="error"
          variant="tonal"
          class="mb-4"
        >
          <v-alert-title>Error</v-alert-title>
          {{ error }}
        </v-alert>

        <!-- Main content -->
        <template v-else-if="digitalArtefact">
          <!-- New Version Available Alert Card -->
          <NewerVersionAlert
            v-if="latestVersion"
            :latest-version="latestVersion"
          />

          <!-- Identifier Info Card -->
          <v-card class="mb-4">
            <v-card-title class="d-flex flex-column align-start">
              <div class="d-flex align-center mb-2">
                <v-chip
                  color="primary"
                  class="mr-3"
                  size="small"
                >
                  DID
                </v-chip>
                <v-chip
                  v-if="digitalArtefact.revoked"
                  color="error"
                  size="small"
                >
                  Revoked
                </v-chip>
              </div>
              <router-link
                :to="`/did/${digitalArtefact.external_uid}`"
                class="text-mono text-body-1 text-primary"
              >
                {{ displayDID }}
              </router-link>
            </v-card-title>

            <v-card-text>
              <!-- Row 1: Version, Creation Date, Division -->
              <v-row>
                <v-col cols="12" sm="4">
                  <div class="text-subtitle-2 text-grey">Version</div>
                  <div class="text-body-1 mt-1 font-weight-medium">{{ digitalArtefact.version }}</div>
                </v-col>

                <v-col cols="12" sm="4">
                  <div class="text-subtitle-2 text-grey">Creation Date</div>
                  <div class="text-body-1 mt-1 font-weight-medium">
                    {{ new Date(digitalArtefact.creation_date).toLocaleDateString() }}
                  </div>
                </v-col>

                <v-col cols="12" sm="4">
                  <div class="text-subtitle-2 text-grey">Division</div>
                  <div class="text-body-1 mt-1 font-weight-medium">{{ digitalArtefact.division }}</div>
                </v-col>
              </v-row>

              <!-- Row 2: Artefact Type and Backlink -->
              <v-row v-if="digitalArtefact.artefact_type || digitalArtefact.backlink" class="mt-2">
                <v-col v-if="digitalArtefact.artefact_type" cols="12" sm="6">
                  <div class="text-subtitle-2 text-grey">Artefact Type</div>
                  <div class="text-body-1 mt-1">
                    <v-chip size="small" color="primary" variant="outlined">
                      {{ digitalArtefact.artefact_type }}
                    </v-chip>
                  </div>
                </v-col>

                <v-col v-if="digitalArtefact.backlink" cols="12" sm="6">
                  <div class="text-subtitle-2 text-grey">Backlink</div>
                  <div class="text-body-1 mt-1">
                    <v-btn
                      :href="digitalArtefact.backlink"
                      target="_blank"
                      variant="text"
                      color="primary"
                      size="small"
                      class="pa-0"
                      style="text-transform: none; min-width: auto;"
                    >
                      <v-icon start size="small">mdi-open-in-new</v-icon>
                      View in Originating System
                    </v-btn>
                  </div>
                </v-col>
              </v-row>

              <!-- Row 2.5: Update Message and Updated By -->
              <v-row v-if="digitalArtefact.update_message || digitalArtefact.updated_by" class="mt-2">
                <v-col v-if="digitalArtefact.updated_by" cols="12" sm="6">
                  <div class="text-subtitle-2 text-grey">Updated By</div>
                  <div class="text-body-1 mt-1">{{ digitalArtefact.updated_by }}</div>
                </v-col>

                <v-col v-if="digitalArtefact.update_message" cols="12" :sm="digitalArtefact.updated_by ? 6 : 12">
                  <div class="text-subtitle-2 text-grey">Update Message</div>
                  <div class="text-body-1 mt-1">{{ digitalArtefact.update_message }}</div>
                </v-col>
              </v-row>

              <!-- Row 3: Artefact Hash -->
              <v-row v-if="digitalArtefact.artefact_hash" class="mt-2">
                <v-col cols="12">
                  <div class="text-subtitle-2 text-grey">Artefact Hash</div>
                  <div class="text-body-1 mt-1 text-mono text-truncate">
                    {{ digitalArtefact.artefact_hash }}
                  </div>
                </v-col>
              </v-row>

              <!-- Row 4: Version UID -->
              <v-row class="mt-2">
                <v-col cols="12">
                  <div class="text-subtitle-2 text-grey">Version UID</div>
                  <div class="text-body-1 mt-1 text-mono">
                    <router-link :to="`/did/${digitalArtefact.version_uid}`" class="text-primary">
                      {{ versionDID }}
                    </router-link>
                  </div>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- Verifiable Credential Card -->
          <v-card class="mb-4">
            <v-card-title class="d-flex align-center justify-space-between">
              <div class="d-flex align-center">
                <v-icon start>mdi-certificate</v-icon>
                Verifiable Credential
              </div>
              <!-- Issue VC button (before VC is issued) -->
              <v-btn
                v-if="!issuedVC"
                color="primary"
                variant="elevated"
                :loading="issuingVC"
                @click="issueVC"
              >
                <v-icon start>mdi-certificate-outline</v-icon>
                Issue VC
              </v-btn>
              <!-- Download button (after VC is issued) -->
              <v-btn
                v-else
                icon="mdi-download"
                variant="text"
                color="primary"
                @click="downloadVC"
                title="Download VC"
              />
            </v-card-title>

            <!-- VC details (shown after issuance) -->
            <v-card-text v-if="issuedVC">
              <v-row>
                <v-col v-if="issuedVC.issuanceDate" cols="12" sm="6">
                  <div class="text-subtitle-2 text-grey">Issuance Date</div>
                  <div class="text-body-1 mt-1">
                    {{ new Date(issuedVC.issuanceDate).toLocaleDateString() }}
                  </div>
                </v-col>

                <v-col v-if="issuedVC.issuer" cols="12" sm="6">
                  <div class="text-subtitle-2 text-grey">Issuer</div>
                  <div class="text-body-1 mt-1 text-mono text-truncate">{{ issuedVC.issuer }}</div>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- Digital Artefact Data Card -->
          <v-card class="mb-4">
            <v-card-title class="d-flex align-center justify-space-between">
              <div class="d-flex align-center">
                <v-icon start>mdi-file-document-outline</v-icon>
                Digital Artefact Metadata
              </div>
              <!-- Fetch Artefact button (before artefact is fetched) -->
              <v-btn
                v-if="!fetchedArtefact"
                color="primary"
                variant="elevated"
                :loading="fetchingArtefact"
                @click="fetchArtefactData"
              >
                <v-icon start>mdi-download-outline</v-icon>
                Fetch Artefact
              </v-btn>
              <!-- Download button (after artefact is fetched) -->
              <v-btn
                v-else
                icon="mdi-download"
                variant="text"
                color="primary"
                @click="downloadArtefact"
                title="Download Artefact JSON"
              />
            </v-card-title>

            <!-- Artefact data (shown after fetch) -->
            <v-card-text v-if="fetchedArtefact">
              <pre class="artefact-json text-mono">{{ JSON.stringify(fetchedArtefact, null, 2) }}</pre>
            </v-card-text>
          </v-card>

          <!-- Binary File Verification Card (only shown if artefact_hash exists) -->
          <v-card v-if="hasArtefactHash" class="mb-4">
            <v-card-title class="d-flex align-center">
              <v-icon start>mdi-file-check-outline</v-icon>
              Binary File Verification
            </v-card-title>

            <v-card-text>
              <p class="text-body-2 text-grey mb-4">
                Upload a file to verify it matches the registered artefact hash.
              </p>

              <!-- File input -->
              <div class="d-flex align-center gap-3 mb-4">
                <v-file-input
                  v-model="selectedFile"
                  label="Select file to verify"
                  variant="outlined"
                  density="compact"
                  prepend-icon=""
                  prepend-inner-icon="mdi-file-outline"
                  hide-details
                  class="flex-grow-1"
                  @change="onFileSelected"
                  @click:clear="clearFile"
                />
                <v-btn
                  color="primary"
                  variant="elevated"
                  :disabled="!selectedFile"
                  :loading="verificationStatus === 'verifying'"
                  @click="verifyFile"
                >
                  <v-icon start>mdi-check-circle-outline</v-icon>
                  Verify
                </v-btn>
              </div>

              <!-- Verification result -->
              <v-alert
                v-if="verificationStatus === 'success'"
                type="success"
                variant="tonal"
                class="mt-4"
              >
                <template #prepend>
                  <v-icon size="large">mdi-check-circle</v-icon>
                </template>
                <v-alert-title>Verification Successful</v-alert-title>
                {{ verificationMessage }}
              </v-alert>

              <v-alert
                v-else-if="verificationStatus === 'error'"
                type="error"
                variant="tonal"
                class="mt-4"
              >
                <template #prepend>
                  <v-icon size="large">mdi-close-circle</v-icon>
                </template>
                <v-alert-title>Verification Failed</v-alert-title>
                <pre class="verification-error-message">{{ verificationMessage }}</pre>
              </v-alert>
            </v-card-text>
          </v-card>

          <!-- Provenance Card (only shown if has_provenance is true) -->
          <v-card v-if="hasProvenance" class="mb-4">
            <v-card-title class="d-flex align-center justify-space-between">
              <div class="d-flex align-center">
                <v-icon start>mdi-source-branch</v-icon>
                Provenance
              </div>
              <!-- Fetch Provenance button (before provenance is fetched) -->
              <v-btn
                v-if="!fetchedProvenance"
                color="primary"
                variant="elevated"
                :loading="fetchingProvenance"
                @click="fetchProvenanceData"
              >
                <v-icon start>mdi-source-branch-check</v-icon>
                Fetch Provenance
              </v-btn>
            </v-card-title>

            <!-- Provenance tree (shown after fetch) -->
            <template v-if="fetchedProvenance">
              <v-card-text v-if="provenanceTreeItems.length === 0" class="text-grey">
                No provenance records found for this artefact.
              </v-card-text>
              <v-card-text v-else class="pa-0">
                <v-treeview
                  :items="provenanceTreeItems"
                  item-value="id"
                  item-title="title"
                  activatable
                  open-on-click
                  density="compact"
                  class="provenance-tree"
                >
                  <template #prepend="{ item }">
                    <v-icon
                      v-if="item.truncated"
                      size="small"
                      color="warning"
                      title="More provenance available - visit this item to explore"
                    >
                      mdi-dots-horizontal-circle-outline
                    </v-icon>
                    <v-icon v-else-if="item.children" size="small" color="primary">
                      mdi-source-branch
                    </v-icon>
                    <v-icon v-else size="small" color="grey">
                      mdi-file-document-outline
                    </v-icon>
                  </template>
                  <template #title="{ item }">
                    <div class="d-flex align-center">
                      <router-link
                        :to="`/did/${item.uid}`"
                        class="text-primary text-mono provenance-link"
                        @click.stop
                      >
                        {{ item.title }}
                      </router-link>
                      <v-chip
                        v-if="item.division"
                        size="x-small"
                        class="ml-2"
                        variant="outlined"
                      >
                        {{ item.division }}
                      </v-chip>
                      <v-chip
                        v-if="item.artefact_type"
                        size="x-small"
                        class="ml-2"
                        variant="outlined"
                        color="primary"
                      >
                        {{ item.artefact_type }}
                      </v-chip>
                      <v-tooltip v-if="item.truncated" location="top">
                        <template #activator="{ props }">
                          <v-icon
                            v-bind="props"
                            size="x-small"
                            color="warning"
                            class="ml-1"
                          >
                            mdi-alert-circle-outline
                          </v-icon>
                        </template>
                        <span>This item has more provenance. Click to explore.</span>
                      </v-tooltip>
                    </div>
                  </template>
                </v-treeview>
              </v-card-text>
            </template>
          </v-card>

          <!-- Version History Card -->
          <v-card class="mb-4">
            <v-card-title class="d-flex align-center justify-space-between">
              <div class="d-flex align-center">
                <v-icon start>mdi-history</v-icon>
                Version History
              </div>
              <!-- Load Versions button (before versions are fetched) -->
              <v-btn
                v-if="!fetchedVersions"
                color="primary"
                variant="elevated"
                :loading="fetchingVersions"
                @click="fetchVersionsData"
              >
                <v-icon start>mdi-reload</v-icon>
                Load Versions
              </v-btn>
            </v-card-title>

            <!-- Versions list (shown after fetch) -->
            <v-card-text v-if="fetchedVersions">
              <v-table density="compact">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Creation Date</th>
                    <th>Version UID</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="version in fetchedVersions.versions"
                    :key="version.version_uid"
                    :class="{ 'bg-grey-lighten-4': version.version_uid === digitalArtefact.version_uid }"
                  >
                    <td class="font-weight-medium">v{{ version.version }}</td>
                    <td>{{ new Date(version.creation_date).toLocaleDateString() }}</td>
                    <td>
                      <router-link
                        :to="`/did/${version.version_uid}`"
                        class="text-primary text-mono version-link"
                      >
                        {{ version.version_uid }}
                      </router-link>
                    </td>
                    <td>
                      <v-chip
                        v-if="version.revoked"
                        size="x-small"
                        color="error"
                        variant="outlined"
                      >
                        Revoked
                      </v-chip>
                      <v-chip
                        v-else-if="version.version_uid === digitalArtefact.version_uid"
                        size="x-small"
                        color="primary"
                        variant="outlined"
                      >
                        Current
                      </v-chip>
                    </td>
                    <td>
                      <v-btn
                        v-if="version.version_uid !== digitalArtefact.version_uid"
                        size="small"
                        variant="text"
                        color="primary"
                        @click="compareVersion(version.version_uid)"
                      >
                        <v-icon start size="small">mdi-compare</v-icon>
                        Compare
                      </v-btn>
                    </td>
                  </tr>
                </tbody>
              </v-table>
            </v-card-text>
          </v-card>

          <!-- Version Diff Dialog -->
          <v-dialog v-model="showDiffDialog" max-width="800px">
            <v-card>
              <v-card-title class="d-flex align-center justify-space-between">
                <div class="d-flex align-center">
                  <v-icon start>mdi-compare</v-icon>
                  Version Comparison
                </div>
                <v-btn
                  icon="mdi-close"
                  variant="text"
                  @click="closeDiffDialog"
                />
              </v-card-title>

              <v-card-text>
                <template v-if="fetchingDiff">
                  <v-skeleton-loader type="article" />
                </template>

                <template v-else-if="diffData">
                  <!-- Version info header -->
                  <div class="mb-4 pa-3 bg-grey-lighten-4 rounded">
                    <div class="d-flex justify-space-between align-center">
                      <div>
                        <div class="text-caption text-grey">Source Version</div>
                        <div class="text-body-2 font-weight-medium">v{{ diffData.source_version }}</div>
                      </div>
                      <v-icon color="grey">mdi-arrow-right</v-icon>
                      <div>
                        <div class="text-caption text-grey">Target Version</div>
                        <div class="text-body-2 font-weight-medium">v{{ diffData.target_version }}</div>
                      </div>
                    </div>
                  </div>

                  <!-- No changes message -->
                  <v-alert
                    v-if="!hasDiffChanges(diffData)"
                    type="info"
                    variant="tonal"
                    class="mb-4"
                  >
                    No differences found between these versions.
                  </v-alert>

                  <!-- Changes list -->
                  <div v-else class="diff-changes">
                    <!-- Artefact Hash -->
                    <div v-if="diffData.artefact_hash" class="diff-field mb-4">
                      <div class="text-subtitle-2 font-weight-bold mb-2">Artefact Hash</div>
                      <div class="diff-values">
                        <div class="diff-old pa-2 rounded mb-1">
                          <span class="text-caption text-grey">Old:</span>
                          <pre class="text-mono">{{ diffData.artefact_hash.old_value || '(none)' }}</pre>
                        </div>
                        <div class="diff-new pa-2 rounded">
                          <span class="text-caption text-grey">New:</span>
                          <pre class="text-mono">{{ diffData.artefact_hash.new_value || '(none)' }}</pre>
                        </div>
                      </div>
                    </div>

                    <!-- Artefact Type -->
                    <div v-if="diffData.artefact_type" class="diff-field mb-4">
                      <div class="text-subtitle-2 font-weight-bold mb-2">Artefact Type</div>
                      <div class="diff-values">
                        <div class="diff-old pa-2 rounded mb-1">
                          <span class="text-caption text-grey">Old:</span>
                          <span class="ml-2">{{ diffData.artefact_type.old_value || '(none)' }}</span>
                        </div>
                        <div class="diff-new pa-2 rounded">
                          <span class="text-caption text-grey">New:</span>
                          <span class="ml-2">{{ diffData.artefact_type.new_value || '(none)' }}</span>
                        </div>
                      </div>
                    </div>

                    <!-- Division -->
                    <div v-if="diffData.division" class="diff-field mb-4">
                      <div class="text-subtitle-2 font-weight-bold mb-2">Division</div>
                      <div class="diff-values">
                        <div class="diff-old pa-2 rounded mb-1">
                          <span class="text-caption text-grey">Old:</span>
                          <span class="ml-2">{{ diffData.division.old_value || '(none)' }}</span>
                        </div>
                        <div class="diff-new pa-2 rounded">
                          <span class="text-caption text-grey">New:</span>
                          <span class="ml-2">{{ diffData.division.new_value || '(none)' }}</span>
                        </div>
                      </div>
                    </div>

                    <!-- Backlink -->
                    <div v-if="diffData.backlink" class="diff-field mb-4">
                      <div class="text-subtitle-2 font-weight-bold mb-2">Backlink</div>
                      <div class="diff-values">
                        <div class="diff-old pa-2 rounded mb-1">
                          <span class="text-caption text-grey">Old:</span>
                          <span class="ml-2">{{ diffData.backlink.old_value || '(none)' }}</span>
                        </div>
                        <div class="diff-new pa-2 rounded">
                          <span class="text-caption text-grey">New:</span>
                          <span class="ml-2">{{ diffData.backlink.new_value || '(none)' }}</span>
                        </div>
                      </div>
                    </div>

                    <!-- Provenance -->
                    <div v-if="diffData.provenance" class="diff-field mb-4">
                      <div class="text-subtitle-2 font-weight-bold mb-2">Provenance</div>
                      <div v-if="diffData.provenance.added.length > 0" class="mb-2">
                        <div class="text-caption text-success font-weight-bold mb-1">
                          <v-icon size="small" color="success">mdi-plus-circle</v-icon>
                          Added ({{ diffData.provenance.added.length }})
                        </div>
                        <div class="diff-added pa-2 rounded">
                          <div v-for="item in diffData.provenance.added" :key="item" class="text-mono text-body-2">
                            {{ item }}
                          </div>
                        </div>
                      </div>
                      <div v-if="diffData.provenance.removed.length > 0">
                        <div class="text-caption text-error font-weight-bold mb-1">
                          <v-icon size="small" color="error">mdi-minus-circle</v-icon>
                          Removed ({{ diffData.provenance.removed.length }})
                        </div>
                        <div class="diff-removed pa-2 rounded">
                          <div v-for="item in diffData.provenance.removed" :key="item" class="text-mono text-body-2">
                            {{ item }}
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- Artefact Metadata -->
                    <div v-if="diffData.artefact_metadata" class="diff-field mb-4">
                      <div class="text-subtitle-2 font-weight-bold mb-2">Artefact Metadata</div>
                      <div class="diff-values">
                        <div class="diff-old pa-2 rounded mb-1">
                          <span class="text-caption text-grey">Old:</span>
                          <pre class="metadata-json">{{ JSON.stringify(diffData.artefact_metadata.old_value, null, 2) || '(none)' }}</pre>
                        </div>
                        <div class="diff-new pa-2 rounded">
                          <span class="text-caption text-grey">New:</span>
                          <pre class="metadata-json">{{ JSON.stringify(diffData.artefact_metadata.new_value, null, 2) || '(none)' }}</pre>
                        </div>
                      </div>
                    </div>
                  </div>
                </template>
              </v-card-text>

              <v-card-actions>
                <v-spacer />
                <v-btn
                  color="primary"
                  variant="text"
                  @click="closeDiffDialog"
                >
                  Close
                </v-btn>
              </v-card-actions>
            </v-card>
          </v-dialog>

          <!-- Descendants Card -->
          <v-card class="mb-4">
            <v-card-title class="d-flex align-center justify-space-between">
              <div class="d-flex align-center">
                <v-icon start>mdi-source-branch-sync</v-icon>
                Descendants
              </div>
              <!-- Load Descendants button (before descendants are fetched) -->
              <v-btn
                v-if="!fetchedDescendants"
                color="primary"
                variant="elevated"
                :loading="fetchingDescendants"
                @click="fetchDescendantsData(1)"
              >
                <v-icon start>mdi-source-branch-sync</v-icon>
                Load Descendants
              </v-btn>
            </v-card-title>

            <!-- Descendants list (shown after fetch) -->
            <v-card-text v-if="fetchedDescendants">
              <!-- No descendants message -->
              <div v-if="fetchedDescendants.total_count === 0" class="text-grey text-center py-4">
                No descendants found for this artefact.
              </div>

              <!-- Descendants table -->
              <template v-else>
                <!-- Pagination info -->
                <div class="d-flex align-center justify-space-between mb-3 text-body-2 text-grey">
                  <div>
                    Showing {{ fetchedDescendants.descendants.length }} of {{ fetchedDescendants.total_count }} descendant{{ fetchedDescendants.total_count !== 1 ? 's' : '' }}
                  </div>
                  <div v-if="fetchedDescendants.total_count > fetchedDescendants.page_size">
                    Page {{ fetchedDescendants.page }}
                  </div>
                </div>

                <v-table density="compact">
                  <thead>
                    <tr>
                      <th>Division</th>
                      <th>Type</th>
                      <th>Version</th>
                      <th>Creation Date</th>
                      <th>External UID</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="descendant in fetchedDescendants.descendants" :key="descendant.uid">
                      <td>
                        <v-chip size="x-small" variant="outlined">
                          {{ descendant.division }}
                        </v-chip>
                      </td>
                      <td>
                        <v-chip
                          v-if="descendant.artefact_type"
                          size="x-small"
                          color="primary"
                          variant="outlined"
                        >
                          {{ descendant.artefact_type }}
                        </v-chip>
                        <span v-else class="text-grey">—</span>
                      </td>
                      <td class="font-weight-medium">v{{ descendant.version }}</td>
                      <td>{{ new Date(descendant.creation_date).toLocaleDateString() }}</td>
                      <td>
                        <router-link
                          :to="`/did/${descendant.external_uid}`"
                          class="text-primary text-mono version-link"
                        >
                          {{ descendant.external_uid }}
                        </router-link>
                      </td>
                    </tr>
                  </tbody>
                </v-table>

                <!-- Pagination controls -->
                <div v-if="fetchedDescendants.total_count > fetchedDescendants.page_size" class="d-flex justify-center mt-4">
                  <v-btn
                    :disabled="descendantsPage <= 1"
                    variant="text"
                    color="primary"
                    @click="loadPreviousDescendantsPage"
                  >
                    <v-icon start>mdi-chevron-left</v-icon>
                    Previous
                  </v-btn>
                  <v-btn
                    :disabled="!fetchedDescendants.has_more"
                    variant="text"
                    color="primary"
                    @click="loadNextDescendantsPage"
                  >
                    Next
                    <v-icon end>mdi-chevron-right</v-icon>
                  </v-btn>
                </div>
              </template>
            </v-card-text>
          </v-card>
        </template>

        <!-- Not found state -->
        <v-card v-else class="pa-6 text-center">
          <v-icon size="64" color="grey">mdi-help-circle-outline</v-icon>
          <v-card-title>Identifier Not Found</v-card-title>
          <v-card-text>
            The identifier "{{ identifier }}" was not found in the system.
          </v-card-text>
          <v-card-actions class="justify-center">
            <v-btn color="primary" @click="goHome">
              Search Again
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
.text-mono {
  font-family: monospace;
}

.artefact-json {
  background-color: #f5f5f5;
  border-radius: 4px;
  padding: 16px;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  font-size: 0.85rem;
  line-height: 1.4;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.provenance-tree {
  padding: 8px 0;
}

.provenance-tree :deep(.v-treeview-item) {
  padding-left: 8px;
}

.provenance-link {
  font-size: 0.85rem;
  text-decoration: none;
}

.provenance-link:hover {
  text-decoration: underline;
}

.verification-error-message {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: monospace;
  font-size: 0.85rem;
  margin: 0;
  margin-top: 8px;
}

.gap-3 {
  gap: 12px;
}

.version-link {
  font-size: 0.85rem;
  text-decoration: none;
}

.version-link:hover {
  text-decoration: underline;
}

/* Diff display styles */
.diff-old {
  background-color: #ffebee;
  border-left: 3px solid #f44336;
}

.diff-new {
  background-color: #e8f5e9;
  border-left: 3px solid #4caf50;
}

.diff-added {
  background-color: #e8f5e9;
  border-left: 3px solid #4caf50;
}

.diff-removed {
  background-color: #ffebee;
  border-left: 3px solid #f44336;
}

.metadata-json {
  font-family: monospace;
  font-size: 0.85rem;
  margin: 4px 0 0 0;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.diff-field {
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 16px;
}

.diff-field:last-child {
  border-bottom: none;
}
</style>
