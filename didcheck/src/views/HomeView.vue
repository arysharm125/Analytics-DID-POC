<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { extractVCId } from '@/utils/vcValidation'

const router = useRouter()
const identifier = ref('')
const loading = ref(false)
const errorMessage = ref('')

// VC File validation state
const vcFile = ref(null)
const vcFileError = ref('')
const vcLoading = ref(false)
const isDraggingOver = ref(false)

// UUID regex pattern (8-4-4-4-12 hex format)
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// DID web pattern for did:web:did.amd.com:
const DID_WEB_PATTERN = /^did:web:did\.amd\.com:.+$/

// Pattern to extract UUID-like strings from pasted content
const UUID_EXTRACT_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

const isValidIdentifier = computed(() => {
  const trimmed = identifier.value.trim()
  if (!trimmed) return false
  return UUID_PATTERN.test(trimmed) || DID_WEB_PATTERN.test(trimmed)
})

const handlePaste = (event) => {
  const pastedText = event.clipboardData?.getData('text') || ''
  const match = pastedText.match(UUID_EXTRACT_PATTERN)
  if (match) {
    event.preventDefault()
    identifier.value = match[0]
  }
}

const checkIdentifier = async () => {
  if (!isValidIdentifier.value) return

  errorMessage.value = ''
  loading.value = true

  try {
    router.push(`/did/${encodeURIComponent(identifier.value.trim())}`)
  } catch (err) {
    await handleError(err)
  } finally {
    loading.value = false
  }
}

const handleError = async (err) => {
  console.error('Error during identifier check:', err)

  if (err.response) {
    try {
      const data = typeof err.response.data === 'string'
        ? JSON.parse(err.response.data)
        : err.response.data

      if (typeof data.detail === 'string') {
        errorMessage.value = data.detail
        console.error('Error detail:', data.detail)
      } else if (data.detail?.msg && typeof data.detail.msg === 'string') {
        errorMessage.value = data.detail.msg
        console.error('Error detail.msg:', data.detail.msg)
      } else {
        errorMessage.value = `Error: ${err.response.status}`
      }
    } catch (parseErr) {
      errorMessage.value = `Error: ${err.response.status}`
    }
  } else {
    errorMessage.value = err.message || 'An unexpected error occurred'
  }
}

// VC File handlers
const onVCFileSelected = (event) => {
  const files = event.target?.files || event
  if (files && files.length > 0) {
    vcFile.value = files[0]
    vcFileError.value = ''
  }
}

const clearVCFile = () => {
  vcFile.value = null
  vcFileError.value = ''
}

const validateVCFile = async () => {
  if (!vcFile.value) return

  vcLoading.value = true
  vcFileError.value = ''

  try {
    // Read file content
    const content = await vcFile.value.text()

    // Try to parse the VC and extract its ID
    let validationId
    try {
      const vc = JSON.parse(content)
      // Use VC's own id field if it's a valid AMD DID, otherwise generate random UUID
      validationId = extractVCId(vc) || crypto.randomUUID()
    } catch {
      // If JSON parsing fails, use random UUID (validation view will show the parse error)
      validationId = crypto.randomUUID()
    }

    // Store content in sessionStorage with ID prefix
    sessionStorage.setItem(`vc-${validationId}-content`, content)
    sessionStorage.setItem(`vc-${validationId}-filename`, vcFile.value.name)

    // Navigate to validation page with unique ID
    router.push({ name: 'validate-vc', params: { validationId } })
  } catch (err) {
    vcFileError.value = `Failed to read file: ${err.message}`
  } finally {
    vcLoading.value = false
  }
}

// Drag and drop handlers
const onDragOver = (event) => {
  event.preventDefault()
  isDraggingOver.value = true
}

const onDragLeave = () => {
  isDraggingOver.value = false
}

const onDrop = (event) => {
  event.preventDefault()
  isDraggingOver.value = false

  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    const file = files[0]
    if (file.type === 'application/json' || file.name.endsWith('.json')) {
      vcFile.value = file
      vcFileError.value = ''
    } else {
      vcFileError.value = 'Please drop a JSON file'
    }
  }
}
</script>

<template>
  <v-container class="fill-height">
    <v-row justify="center" align="center">
      <v-col cols="12" md="8" lg="6">
        <!-- DID Check Card -->
        <v-card class="pa-6 mb-6">
          <v-card-title class="text-h4 text-center mb-4">
            DID Check
          </v-card-title>

          <v-card-subtitle class="text-center mb-6">
            Verify the validity and status of a DID or UID
          </v-card-subtitle>

          <v-card-text>
            <v-alert
              v-if="errorMessage"
              type="error"
              closable
              class="mb-4"
              @click:close="errorMessage = ''"
            >
              {{ errorMessage }}
            </v-alert>

            <v-form @submit.prevent="checkIdentifier">
              <v-text-field
                v-model="identifier"
                label="Enter DID or UID"
                placeholder="did:web:did.amd.com:123 or 550e8400-e29b-41d4-a716-446655440000"
                variant="outlined"
                clearable
                prepend-inner-icon="mdi-identifier"
                :loading="loading"
                :error="identifier.trim() !== '' && !isValidIdentifier"
                :hint="identifier.trim() !== '' && !isValidIdentifier ? 'Enter a valid UUID or did:web:did.amd.com:... identifier' : ''"
                persistent-hint
                @keyup.enter="checkIdentifier"
                @paste="handlePaste"
              />

              <v-btn
                color="primary"
                size="large"
                block
                :disabled="!isValidIdentifier"
                :loading="loading"
                @click="checkIdentifier"
              >
                <v-icon start>mdi-magnify</v-icon>
                Check Status
              </v-btn>
            </v-form>
          </v-card-text>
        </v-card>

        <!-- VC Validation Card -->
        <v-card class="pa-6">
          <v-card-title class="text-h4 text-center mb-4">
            <v-icon start size="large">mdi-certificate</v-icon>
            VC Validation
          </v-card-title>

          <v-card-subtitle class="text-center mb-6">
            Validate a Verifiable Credential file
          </v-card-subtitle>

          <v-card-text>
            <v-alert
              v-if="vcFileError"
              type="error"
              closable
              class="mb-4"
              @click:close="vcFileError = ''"
            >
              {{ vcFileError }}
            </v-alert>

            <!-- Drag and drop zone -->
            <div
              class="drop-zone mb-4"
              :class="{ 'drop-zone-active': isDraggingOver, 'drop-zone-has-file': vcFile }"
              @dragover="onDragOver"
              @dragleave="onDragLeave"
              @drop="onDrop"
            >
              <template v-if="!vcFile">
                <v-icon size="48" color="grey-lighten-1" class="mb-2">mdi-file-upload-outline</v-icon>
                <div class="text-body-1 text-grey-darken-1 mb-2">
                  Drag and drop a VC JSON file here
                </div>
                <div class="text-caption text-grey">or</div>
                <v-btn
                  variant="outlined"
                  color="primary"
                  class="mt-2"
                  @click="$refs.vcFileInput.click()"
                >
                  <v-icon start>mdi-folder-open</v-icon>
                  Browse Files
                </v-btn>
              </template>
              <template v-else>
                <v-icon size="48" color="success" class="mb-2">mdi-file-check</v-icon>
                <div class="text-body-1 font-weight-medium mb-1">{{ vcFile.name }}</div>
                <div class="text-caption text-grey">
                  {{ (vcFile.size / 1024).toFixed(1) }} KB
                </div>
                <v-btn
                  variant="text"
                  color="error"
                  size="small"
                  class="mt-2"
                  @click.stop="clearVCFile"
                >
                  <v-icon start size="small">mdi-close</v-icon>
                  Remove
                </v-btn>
              </template>
            </div>

            <!-- Hidden file input -->
            <input
              ref="vcFileInput"
              type="file"
              accept=".json,application/json"
              class="d-none"
              @change="onVCFileSelected"
            />

            <v-btn
              color="primary"
              size="large"
              block
              :disabled="!vcFile"
              :loading="vcLoading"
              @click="validateVCFile"
            >
              <v-icon start>mdi-check-decagram</v-icon>
              Validate VC
            </v-btn>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
.drop-zone {
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  background-color: #fafafa;
}

.drop-zone:hover {
  border-color: #1976d2;
  background-color: #f0f7ff;
}

.drop-zone-active {
  border-color: #1976d2;
  background-color: #e3f2fd;
  border-style: solid;
}

.drop-zone-has-file {
  border-color: #4caf50;
  background-color: #f1f8e9;
  border-style: solid;
}
</style>
