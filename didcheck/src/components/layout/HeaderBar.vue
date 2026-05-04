<template>
  <div>
    <v-app-bar
      id="headerbar-container"
      color="black"
      style="height: 64px"
      fixed
      app
      :elevation="4"
      v-if="isDesktop"
    >
      <v-row no-gutters style="width: 100%; position: relative; align-items: center;">
        <!-- Logo - Left aligned, vertically centered -->
        <v-col cols="2" class="d-flex align-center">
          <div class="ml-3">
            <img
              id="header-logo-img"
              :src="logo"
              style="width: 80px; cursor: pointer; vertical-align: middle;"
              alt="AMD Logo"
              @click="homeBtnClick"
            />
          </div>
        </v-col>

        <!-- Title - Absolutely centered -->
        <v-col cols="8" class="d-flex justify-center align-center">
          <div id="header-heading-txt" :style="headerStyles" style="color: white;">
            {{ applicationTitle }}
          </div>
        </v-col>

        <!-- Help button - Right aligned -->
        <v-col cols="2" style="display: flex; justify-content: end; align-items: center">
          <v-btn
            icon
            @click="openSupport"
            style="text-transform: capitalize; margin-right: 1rem"
          >
            <v-icon style="color: white; font-size: 24px" class="mb-1">
              mdi-help-circle
            </v-icon>
            <v-tooltip activator="parent" location="bottom">Help</v-tooltip>
          </v-btn>
        </v-col>
      </v-row>
    </v-app-bar>

    <!-- Mobile Header -->
    <v-app-bar
      id="headerbar-mobile-container"
      v-else
      color="black"
      style="height: 64px; display: flex; align-items: center; justify-content: space-between"
      :elevation="4"
    >
      <template v-slot:prepend>
        <v-img
          id="mobile-header-logo-img"
          alt="AMD"
          :width="90"
          height="150"
          :src="logo"
          style="margin-left: 1vh"
        ></v-img>
      </template>

      <v-app-bar-title
        id="header-mobile-heading-txt"
        class="appBarTitle"
        style="text-align: left; font-weight: bold"
      >
        {{ applicationTitle }}
      </v-app-bar-title>
      <v-spacer></v-spacer>
      <v-menu>
        <template v-slot:activator="{ props: activatorProps }">
          <v-btn
            id="btn-header-menu"
            prepend-icon="mdi-format-align-justify"
            size="small"
            v-bind="activatorProps"
          ></v-btn>
        </template>
        <v-list id="header-list-items" class="menu-item-list" theme="dark">
          <span
            v-for="(item, index) in menuItems"
            :key="index"
            :id="`header-list-items-${index}`"
            :value="index"
            style="min-height: 32px"
          >
            <v-list-item>
              <v-list-item-title
                @click="item?.action ? item?.action() : navigate(item?.path)"
                style="font-size: small; cursor: pointer"
              >
                <v-icon style="font-size: 18px">{{ item?.icon }}</v-icon>
                {{ item?.title }}
              </v-list-item-title>
            </v-list-item>
          </span>
        </v-list>
      </v-menu>
    </v-app-bar>
  </div>
</template>

<script>
import { defineComponent } from "vue";
import { useRoute, useRouter } from "vue-router";
import logo from "@/assets/amd-logo.svg";

export default defineComponent({
  name: "HeaderBar",
  data() {
    return {
      logo: logo,
      isDesktop: true,
    };
  },
  setup() {
    const route = useRoute();
    const router = useRouter();

    function isActive(path) {
      return route.path === path;
    }

    return {
      isActive,
      route,
      router,
    };
  },
  mounted() {
    this.checkScreenSize();
    window.addEventListener("resize", this.checkScreenSize);
  },
  beforeUnmount() {
    window.removeEventListener("resize", this.checkScreenSize);
  },
  computed: {
    applicationTitle() {
      return "DID Check";
    },
    headerStyles() {
      return {
        fontSize: "1.2rem",
        fontWeight: "bold",
        textAlign: "center",
      };
    },
    navItems() {
      // Add navigation items here as needed
      return [
        // Example: { title: 'Home', path: '/' },
        // Example: { title: 'About', path: '/about' },
      ];
    },
    menuItems() {
      return [
        { title: "Home", path: "/", icon: "mdi-home" },
        { title: "Help", icon: "mdi-help-circle", action: this.openSupport },
      ];
    },
    isMobile() {
      return window.innerWidth < 752;
    },
  },
  methods: {
    checkScreenSize() {
      this.isDesktop = window.innerWidth >= 752;
    },
    navigate(path) {
      if (path) {
        this.router.push(path);
      }
    },
    homeBtnClick() {
      this.router.push("/");
    },
    openSupport() {
      // Open help/support - can be customized
      window.open("https://www.amd.com/en/support", "_blank");
    },
  },
});
</script>

<style scoped>
.des-toolbar v-toolbar {
  background-color: #000000;
}

.desk-toolbar-items {
  background-color: #000000;
  color: white;
}

.inline-list {
  display: flex;
  background-color: #000000;
}

.inline-list v-list-item {
  margin-right: 8px;
  background-color: #000000;
}

.inline-list .v-list-item__overlay {
  display: none !important;
}

.flex-grow-1 {
  flex-grow: 1;
}

.menu-item-list .v-list {
  background-color: #000000;
}

.v-btn {
  text-decoration: none;
  color: white;
  font-size: 14px !important;
  height: 25px !important;
}

@media (min-width: 752px) and (max-width: 1023px) {
  .headingTitle {
    margin-top: 1rem;
  }

  #header-logo-img {
    margin-top: 1rem;
  }
}
</style>
