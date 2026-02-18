<script setup>
import { computed } from 'vue'

const props = defineProps({
  latestVersion: {
    type: Object,
    required: true,
    validator: (value) => {
      return value && typeof value.version_uid === 'string'
    }
  }
})

// Latest version UID formatted as DID
const latestVersionDID = computed(() => {
  if (!props.latestVersion?.version_uid) return null
  return `did:web:did.amd.com:${props.latestVersion.version_uid}`
})

// Format creation date
const formattedCreationDate = computed(() => {
  if (!props.latestVersion?.creation_date) return null
  return new Date(props.latestVersion.creation_date).toLocaleDateString()
})
</script>

<template>
  <v-card
    class="mb-4"
    color="warning"
    variant="tonal"
  >
    <v-card-title class="d-flex align-center">
      <v-icon start color="warning">mdi-alert-circle</v-icon>
      <span>Newer Version Available</span>
    </v-card-title>
    <v-card-text>
      <v-row>
        <v-col cols="12" sm="4">
          <div class="text-subtitle-2 text-grey-darken-1">Version</div>
          <div class="text-body-1 mt-1 font-weight-medium">{{ latestVersion.version }}</div>
        </v-col>
        <v-col cols="12" sm="4">
          <div class="text-subtitle-2 text-grey-darken-1">Creation Date</div>
          <div class="text-body-1 mt-1 font-weight-medium">
            {{ formattedCreationDate }}
          </div>
        </v-col>
        <v-col v-if="latestVersion.revoked" cols="12" sm="4">
          <v-chip color="error" size="small">Revoked</v-chip>
        </v-col>
      </v-row>
      <v-row class="mt-2">
        <v-col cols="12">
          <router-link
            :to="`/${latestVersion.version_uid}`"
            class="text-primary font-weight-medium"
          >
            <v-icon size="small" start>mdi-open-in-new</v-icon>
            View Latest Version
          </router-link>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
</template>
