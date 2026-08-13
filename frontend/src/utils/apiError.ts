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

/**
 * Pull the human-readable message out of a failed API call.
 *
 * Axios sets `error.message` to "Request failed with status code 409" and puts
 * the useful part — FastAPI's `detail` — on `error.response.data`. Showing
 * `e.message` therefore replaces a precise, actionable message ("An account with
 * this email already exists. Try signing in instead.") with a status code the
 * user can do nothing with. That is exactly what signup did, so a duplicate
 * email and a closed-signup gate looked like the same unexplained failure.
 *
 * `detail` comes in two shapes and both are handled:
 *   - a plain string, from an explicit HTTPException
 *   - an array of `{loc, msg}`, from FastAPI's request validation (422)
 */

interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
}

interface ApiErrorShape {
  response?: {
    status?: number
    data?: {
      detail?: string | ValidationItem[] | { error?: string; details?: string }
    }
  }
  message?: string
}

export function extractApiError(error: unknown, fallback = 'Something went wrong'): string {
  const err = error as ApiErrorShape
  const detail = err?.response?.data?.detail

  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }

  // FastAPI validation errors: surface the first field message, named, so the
  // user knows which input to correct rather than being told "422".
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0]
    if (first?.msg) {
      // loc is like ["body", "admin_email"] — the last entry is the field.
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined
      return field ? `${String(field).replace(/_/g, ' ')}: ${first.msg}` : first.msg
    }
  }

  // Some endpoints nest a structured error under detail (see useAISetup).
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const nested = detail as { error?: string; details?: string }
    if (nested.details) return nested.details
    if (nested.error) return nested.error
  }

  // Nothing reached the server at all — a bare axios message here is genuinely
  // all we know, but say something the user can act on.
  if (err?.message === 'Network Error') {
    return 'Could not reach the server. Check your connection and try again.'
  }

  return fallback
}
