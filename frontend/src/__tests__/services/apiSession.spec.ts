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

The 401 handling that decides whether someone stays signed in.

Two failures used to end a session that was perfectly valid: a burst of
simultaneous 401s each ran its own refresh and raced the resulting Set-Cookie
headers, and any refresh that failed for a reason unrelated to auth — a dropped
connection, a 502 while the backend restarted mid-deploy — was treated as proof
the session had expired.
*/

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'

const post = vi.fn()
const push = vi.fn()
const clearCurrentUser = vi.fn()
const isAuthenticated = vi.fn(() => true)

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios')
  return {
    ...actual,
    default: { ...actual.default, post: (...args: unknown[]) => post(...args) },
    AxiosError: actual.AxiosError,
    AxiosHeaders: actual.AxiosHeaders,
  }
})
vi.mock('@/router', () => ({
  default: { push, currentRoute: { value: { path: '/platform/plans' } } },
}))
vi.mock('@/services/user', () => ({
  userService: { isAuthenticated: () => isAuthenticated(), clearCurrentUser },
}))
vi.mock('@/config/api', () => ({ getApiUrl: () => 'https://example.test/api/v1' }))
vi.mock('@/composables/useEnterpriseFeatures', () => ({
  useEnterpriseFeatures: () => ({
    hasEnterpriseModule: false,
    loadModule: vi.fn(),
    moduleImports: {},
  }),
}))

/** The rejection handler axios would invoke for a failed response. */
type Handler = (error: AxiosError) => Promise<unknown>

const loadInterceptor = async (): Promise<Handler> => {
  vi.resetModules()
  const module = await import('@/services/api')
  const api = module.default
  // The response interceptor registered by the module under test.
  const handlers = (api.interceptors.response as unknown as {
    handlers: { rejected: Handler }[]
  }).handlers
  return handlers[handlers.length - 1].rejected
}

const unauthorized = (url: string): AxiosError => {
  const error = new AxiosError('Unauthorized')
  error.config = { url, headers: new AxiosHeaders() } as never
  error.response = { status: 401, data: {}, statusText: '', headers: {}, config: error.config } as never
  return error
}

const failedRefresh = (status?: number): AxiosError => {
  const error = new AxiosError(status ? `HTTP ${status}` : 'Network Error')
  if (status) {
    error.response = { status, data: {}, statusText: '', headers: {}, config: {} } as never
  }
  return error
}

describe('api session handling', () => {
  beforeEach(() => {
    post.mockReset()
    push.mockReset()
    clearCurrentUser.mockReset()
    isAuthenticated.mockReturnValue(true)
  })

  it('refreshes once for a burst of simultaneous 401s', async () => {
    const onRejected = await loadInterceptor()
    let resolveRefresh: (value: unknown) => void = () => {}
    post.mockImplementation(() => new Promise((resolve) => { resolveRefresh = resolve }))

    // Three requests fail together, as they do on any page that loads in parallel.
    const attempts = [
      onRejected(unauthorized('/platform/plans')).catch(() => 'retried'),
      onRejected(unauthorized('/platform/features')).catch(() => 'retried'),
      onRejected(unauthorized('/platform/ai-config')).catch(() => 'retried'),
    ]
    await Promise.resolve()
    resolveRefresh({ data: {} })
    await Promise.allSettled(attempts)

    // One refresh, not three racing Set-Cookie responses for the same cookie.
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe('/users/refresh')
    expect(push).not.toHaveBeenCalled()
  })

  it('keeps the session when the refresh fails for a non-auth reason', async () => {
    const onRejected = await loadInterceptor()
    // A 502 while the backend restarts says nothing about the session.
    post.mockRejectedValue(failedRefresh(502))

    await expect(onRejected(unauthorized('/platform/plans'))).rejects.toBeTruthy()

    expect(push).not.toHaveBeenCalled()
    expect(clearCurrentUser).not.toHaveBeenCalled()
  })

  it('keeps the session when the refresh fails with no response at all', async () => {
    const onRejected = await loadInterceptor()
    post.mockRejectedValue(failedRefresh())

    await expect(onRejected(unauthorized('/platform/plans'))).rejects.toBeTruthy()

    expect(push).not.toHaveBeenCalled()
    expect(clearCurrentUser).not.toHaveBeenCalled()
  })

  it('signs out only when the server rejects the refresh token', async () => {
    const onRejected = await loadInterceptor()
    post.mockRejectedValue(failedRefresh(401))

    await expect(onRejected(unauthorized('/platform/plans'))).rejects.toBeTruthy()

    expect(clearCurrentUser).toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith('/login')
  })

  it('goes straight to login when nobody is signed in', async () => {
    const onRejected = await loadInterceptor()
    isAuthenticated.mockReturnValue(false)

    await expect(onRejected(unauthorized('/platform/plans'))).rejects.toBeTruthy()

    // No point asking for a refresh on behalf of nobody.
    expect(post).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith('/login')
  })
})
