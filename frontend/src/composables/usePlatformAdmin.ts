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

import { ref } from 'vue'
import { isPlatformAdmin } from '@/services/platform'
import { userService } from '@/services/user'

/**
 * Whether the current session can reach the platform console.
 *
 * Module-level so the probe runs once per page load rather than once per
 * component that asks. Starts false: the console link must never flash into
 * view for an ordinary user while the answer is still in flight.
 *
 * This is a UI convenience only. It decides whether to draw a link — it is not
 * a security control, and it must not be mistaken for one. Every /platform
 * endpoint independently re-reads users.is_platform_admin from the database on
 * every request, so a user who edits this value in memory gains nothing but a
 * link that 404s.
 */
const isOperator = ref(false)
let probe: Promise<boolean> | null = null

export function usePlatformAdmin() {
  const check = async (): Promise<boolean> => {
    if (!userService.isAuthenticated()) {
      isOperator.value = false
      return false
    }
    // Shared promise: several components mounting at once ask one question.
    if (!probe) {
      probe = isPlatformAdmin().then((ok) => {
        isOperator.value = ok
        return ok
      })
    }
    return probe
  }

  /** Forget the cached answer — call on logout so the next session re-probes. */
  const reset = () => {
    isOperator.value = false
    probe = null
  }

  return { isOperator, check, reset }
}
