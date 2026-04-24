import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import IdentifierCheck from '@/views/IdentifierCheck.vue'
import VCValidationView from '@/views/VCValidationView.vue'
import LoginView from '@/views/LoginView.vue'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { public: true }
  },
  {
    path: '/',
    name: 'home',
    component: HomeView
  },
  {
    path: '/validate-vc/:validationId',
    name: 'validate-vc',
    component: VCValidationView,
    props: true
  },
  {
    path: '/did/:identifier',
    name: 'identifier-check',
    component: IdentifierCheck,
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

// Navigation guard for authentication
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // Refresh token from cookie on every navigation
  // This ensures we pick up the token after SSO redirect
  authStore.refreshTokenFromCookie()

  // Fetch auth config on first load if not already fetched
  if (!authStore.authConfig) {
    await authStore.fetchAuthConfig()
  }

  // Allow access to public routes (login page)
  if (to.meta.public) {
    next()
    return
  }

  // Check if user is authenticated
  if (!authStore.isAuthenticated) {
    authStore.redirectToLogin()
    return
  }

  next()
})

export default router
