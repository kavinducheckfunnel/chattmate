<!--
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
-->

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { userService } from '@/services/user'
import api from '@/services/api'

const route = useRoute()

const dismissed = ref(false)
const resendState = ref<'idle' | 'sending' | 'sent'>('idle')

/**
 * Shown only to a signed-in user whose address is unverified, and only on
 * authenticated screens.
 *
 * This is the soft half of REQUIRE_EMAIL_VERIFICATION=false: the account works,
 * but the prompt persists. With the flag on the backend blocks sign-in outright
 * and nobody unverified ever gets far enough to see this.
 *
 * `is_email_verified === false` is the test, not a falsy check. A session
 * predating the feature has the field absent, and treating undefined as
 * unverified would put this banner in front of every existing customer.
 */
const shouldShow = computed(() => {
    if (dismissed.value) return false
    if (!route.meta?.requiresAuth) return false
    if (!userService.isAuthenticated()) return false
    return userService.getCurrentUser()?.is_email_verified === false
})

const email = computed(() => userService.getCurrentUser()?.email ?? '')

const resend = async () => {
    if (!email.value) return
    resendState.value = 'sending'
    try {
        await api.post('/auth/resend-verification', { email: email.value })
    } catch {
        // Same non-committal response as everywhere else in this flow.
    }
    resendState.value = 'sent'
}
</script>

<template>
    <div v-if="shouldShow" class="verify-banner" role="status">
        <span class="verify-dot" aria-hidden="true"></span>
        <p class="verify-text">
            <template v-if="resendState === 'sent'">
                Verification link sent to <strong>{{ email }}</strong>. Check your inbox.
            </template>
            <template v-else>
                Confirm <strong>{{ email }}</strong> to secure your workspace.
            </template>
        </p>
        <button v-if="resendState !== 'sent'" type="button" class="verify-action"
                :disabled="resendState === 'sending'" @click="resend">
            {{ resendState === 'sending' ? 'Sending…' : 'Resend email' }}
        </button>
        <button type="button" class="verify-close" aria-label="Dismiss" @click="dismissed = true">×</button>
    </div>
</template>

<style scoped>
.verify-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    background: color-mix(in srgb, var(--accent-solid) 12%, var(--bg));
    border-bottom: 1px solid color-mix(in srgb, var(--accent-solid) 28%, transparent);
    font-family: var(--font-sans);
    font-size: 13.5px;
    color: var(--text);
}

.verify-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent-solid);
    flex-shrink: 0;
    animation: cm-pulse 2.6s ease-in-out infinite;
}

.verify-text {
    margin: 0;
    flex: 1;
    min-width: 0;
}

.verify-text strong { font-weight: 600; }

.verify-action {
    background: none;
    border: 1px solid var(--o12);
    border-radius: 8px;
    padding: 6px 12px;
    font: inherit;
    font-weight: 600;
    color: var(--text);
    cursor: pointer;
    white-space: nowrap;
    transition: background-color 0.18s;
}

.verify-action:hover:not(:disabled) { background: var(--o06); }
.verify-action:disabled { opacity: 0.55; cursor: not-allowed; }

.verify-close {
    background: none;
    border: none;
    color: var(--muted2);
    font-size: 20px;
    line-height: 1;
    padding: 0 2px;
    cursor: pointer;
}

.verify-close:hover { color: var(--text); }

@media (max-width: 600px) {
    .verify-banner { flex-wrap: wrap; }
    .verify-text { flex-basis: 100%; }
}
</style>
