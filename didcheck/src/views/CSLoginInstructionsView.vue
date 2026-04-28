<template>
  <v-container class="fill-height" fluid>
    <v-row align="center" justify="center">
      <v-col cols="12" sm="8" md="6">
        <v-card class="elevation-12">
          <v-toolbar color="primary" dark>
            <v-toolbar-title>DIDCheck - Login Required</v-toolbar-title>
          </v-toolbar>
          <v-card-text class="pa-8">
            <v-alert type="info" variant="tonal" class="mb-6">
              <div class="text-h6 mb-2">Login Instructions</div>
              <p class="text-body-1">
                Access EPYC advisory servers and click the login button under "DIDCheck".
              </p>
            </v-alert>
            <v-btn
              color="primary"
              block
              size="large"
              @click="redirectToCSLogin"
              prepend-icon="mdi-login"
            >
              Proceed to Login
            </v-btn>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

function redirectToCSLogin() {
  if (authStore.authConfig?.cs_login_url) {
    window.location.href = authStore.authConfig.cs_login_url
  }
}
</script>

<style scoped>
.fill-height {
  min-height: 100vh;
}
</style>
