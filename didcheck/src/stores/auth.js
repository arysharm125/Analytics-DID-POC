/**
 * Authentication store for managing user login state
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

/**
 * Helper function to read jwt_token or access_token from cookie
 * @returns {string|null} The JWT token or null if not found
 */
function getTokenFromCookie() {
  const cookies = document.cookie.split(';')
  // Try jwt_token first, then fall back to access_token
  const jwtCookie = cookies.find(c => c.trim().startsWith('jwt_token='))
  if (jwtCookie) {
    return jwtCookie.split('=')[1]?.trim() || null
  }
  const accessCookie = cookies.find(c => c.trim().startsWith('access_token='))
  if (accessCookie) {
    return accessCookie.split('=')[1]?.trim() || null
  }
  return null
}

/**
 * Helper function to clear jwt_token and access_token cookies
 */
function clearTokenCookie() {
  // Clear both possible cookie names by setting expiration to past date
  // Use conditional domain: .amd.com for production, no domain for localhost
  const isProduction = window.location.hostname.endsWith('.amd.com')
  const domainPart = isProduction ? '; domain=.amd.com' : ''
  document.cookie = `jwt_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/${domainPart}`
  document.cookie = `access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/${domainPart}`
}

export const useAuthStore = defineStore('auth', () => {
  // State
  const accessToken = ref(getTokenFromCookie())
  const user = ref(null)
  const authConfig = ref(null) // {login_mode, cs_login_url}

  // Getters
  const isAuthenticated = computed(() => !!accessToken.value)
  const isMockMode = computed(() => authConfig.value?.login_mode === 'mock')
  const isCSMode = computed(() => authConfig.value?.login_mode === 'cs')

  // Actions
  async function fetchAuthConfig() {
    try {
      const response = await fetch('/api/auth/config')
      if (!response.ok) {
        throw new Error('Failed to fetch auth config')
      }
      authConfig.value = await response.json()
    } catch (error) {
      console.error('Error fetching auth config:', error)
      // Default to mock mode if config fetch fails
      authConfig.value = { login_mode: 'mock', cs_login_url: null }
    }
  }

  async function login(email, password) {
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        credentials: 'include', // Allow cookies to be set by backend
        body: JSON.stringify({ email, password })
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Login failed')
      }

      // Backend sets jwt_token cookie via Set-Cookie header
      // Sync it to our state
      refreshTokenFromCookie()

      // Store user info
      const userInfo = {
        email: email,
        // Additional user info would come from token validation
      }
      user.value = userInfo

      return true
    } catch (error) {
      console.error('Login error:', error)
      throw error
    }
  }

  function logout() {
    clearTokenCookie()
    accessToken.value = null
    user.value = null
  }

  /**
   * Refresh token from cookie
   * Useful after SSO redirect to sync the token from cookie to state
   */
  function refreshTokenFromCookie() {
    const token = getTokenFromCookie()
    accessToken.value = token
    if (!token) {
      user.value = null
    }
  }

  function redirectToLogin() {
    if (isMockMode.value) {
      // Redirect to mock login page
      window.location.href = '/login'
    } else if (isCSMode.value && authConfig.value?.cs_login_url) {
      // Redirect to CS login instructions page
      window.location.href = '/cs-login'
    } else {
      // Fallback to mock login
      window.location.href = '/login'
    }
  }

  return {
    // State
    accessToken,
    user,
    authConfig,
    // Getters
    isAuthenticated,
    isMockMode,
    isCSMode,
    // Actions
    fetchAuthConfig,
    login,
    logout,
    refreshTokenFromCookie,
    redirectToLogin
  }
})
