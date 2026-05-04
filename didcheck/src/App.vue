<script setup>
import HeaderBar from "@/components/layout/HeaderBar.vue";
import FooterBar from "@/components/layout/Footer.vue";
</script>

<template>
  <v-app>
    <HeaderBar />

    <v-main>
      <router-view />
    </v-main>

    <FooterBar />
  </v-app>
</template>

<style>
/* Global styles */
html {
  overflow-y: auto;
}
</style>
