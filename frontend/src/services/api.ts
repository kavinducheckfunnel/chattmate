/*
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

import axios, { AxiosError } from 'axios'
import router from '@/router'
import { getApiUrl } from '@/config/api'
import { userService } from '@/services/user'
import { useEnterpriseFeatures } from '@/composables/useEnterpriseFeatures'

const { hasEnterpriseModule, loadModule, moduleImports } = useEnterpriseFeatures()

// Lazy load Shopify dependencies only if enterprise module is available
let getSessionToken: any = null
let initShopifyApp: any = null

if (hasEnterpriseModule) {
  // Load Shopify dependencies asynchronously
  ;(async () => {
    try {
      // Load Shopify App Bridge utilities via wrapper module
      const appBridgeUtilitiesModule = await loadModule(moduleImports.shopifyAppBridgeUtilities)
      if (appBridgeUtilitiesModule?.getSessionToken) {
        getSessionToken = appBridgeUtilitiesModule.getSessionToken
      }

      // Load Shopify app bridge plugin
      const shopifyAppBridgeModule = await loadModule(moduleImports.shopifyAppBridge)
      if (shopifyAppBridgeModule?.initShopifyApp) {
        initShopifyApp = shopifyAppBridgeModule.initShopifyApp
      }
    } catch (error) {
      console.warn('Failed to load Shopify dependencies:', error)
    }
  })()
}

const api = axios.create({
  baseURL: getApiUrl(),
  withCredentials: true, // Important for cookies
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor to add session token for Shopify embedded app
api.interceptors.request.use(
  async (config) => {
    // Check if we're in embedded Shopify context
    const urlParams = new URLSearchParams(window.location.search)
    const hasShopParam = urlParams.has('shop') || urlParams.has('host')

    // Check if this is a Shopify-related endpoint
    const isShopifyEndpoint =
      config.url?.includes('/shopify/') ||
      config.url?.endsWith('/shopify') ||
      (config.url?.includes('/agent/') && hasShopParam) ||
      (config.url?.includes('/chats/') && hasShopParam)

    if (
      hasShopParam &&
      isShopifyEndpoint &&
      hasEnterpriseModule &&
      initShopifyApp &&
      getSessionToken
    ) {
      try {
        const app = initShopifyApp()
        if (app) {
          const token = await getSessionToken(app)
          if (token) {
            config.headers.Authorization = `Bearer ${token}`
            console.log('✅ Added Shopify session token to request:', config.url)
          }
        }
      } catch (error) {
        console.error('❌ Failed to add session token:', error)
      }
    }

    return config
  },
  (error) => Promise.reject(error),
)

// One in-flight refresh, shared by every request that gets a 401.
//
// A page load fires several requests at once, so an expired access token
// produces a burst of simultaneous 401s. Each used to run its own refresh; the
// browser then raced several Set-Cookie responses for the same cookie, and any
// single one that lost the race signed the user out from under the others.
let refreshInFlight: Promise<void> | null = null

const refreshSession = (): Promise<void> => {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post('/users/refresh', {}, { withCredentials: true, baseURL: getApiUrl() })
      .then(() => undefined)
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

/**
 * Whether a failed refresh means the session is genuinely gone.
 *
 * Only the server rejecting the refresh token says that. A network drop, a
 * timeout, a 502 while the backend restarts mid-deploy — those say nothing
 * about the session, and treating them as expiry is what logged people out at
 * random. In those cases the request just fails and the session survives.
 */
const isSessionExpired = (error: unknown): boolean => {
  const status = (error as AxiosError)?.response?.status
  return status === 401 || status === 403
}

const endSession = () => {
  document.cookie = 'user_info=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
  try {
    userService.clearCurrentUser()
  } catch {}
  if (router.currentRoute.value.path !== '/login') {
    router.push('/login')
  }
}

// Response interceptor
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config

    // If error is 401 and we haven't tried to refresh token yet
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      // If there's no authenticated user, do not attempt refresh. Go to login directly.
      if (!userService.isAuthenticated()) {
        endSession()
        return Promise.reject(error)
      }

      originalRequest._retry = true

      try {
        await refreshSession()
        // Retry original request
        return api(originalRequest)
      } catch (refreshError) {
        if (isSessionExpired(refreshError)) {
          endSession()
        }
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  },
)

export default api
// Add type for extended axios config
declare module 'axios' {
  export interface AxiosRequestConfig {
    _retry?: boolean
  }
}
