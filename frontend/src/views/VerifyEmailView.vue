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
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/services/api'
import { extractApiError } from '@/utils/apiError'

const route = useRoute()

type State = 'verifying' | 'verified' | 'failed'
const state = ref<State>('verifying')
const message = ref('')
const verifiedEmail = ref('')

// Resend, offered only on failure — an expired link is the common way to land
// here and it is the only thing the user can do about it from this page.
const resendEmail = ref('')
const resendState = ref<'idle' | 'sending' | 'sent'>('idle')

onMounted(async () => {
    const token = route.query.token
    if (typeof token !== 'string' || !token) {
        state.value = 'failed'
        message.value = 'This link is missing its verification code. Use the full link from your email.'
        return
    }

    try {
        const { data } = await api.post('/auth/verify-email', { token })
        verifiedEmail.value = data?.email || ''
        state.value = 'verified'
    } catch (e) {
        message.value = extractApiError(e, 'We could not verify this link.')
        state.value = 'failed'
    }
})

const resend = async () => {
    if (!resendEmail.value) return
    resendState.value = 'sending'
    try {
        await api.post('/auth/resend-verification', { email: resendEmail.value })
    } catch {
        // Deliberately indistinguishable from success: the endpoint does not
        // disclose whether an address has an account, and neither does this.
    }
    resendState.value = 'sent'
}
</script>

<template>
    <div class="auth-page">
        <div class="form-panel">
            <div class="auth-logo">
                <div class="logo-mark">
                    <div class="dot"></div>
                    <div class="dot"></div>
                    <div class="dot"></div>
                </div>
                <span class="logo-word">Growmiq mini</span>
            </div>

            <template v-if="state === 'verifying'">
                <div class="status-mark spinner" aria-hidden="true"></div>
                <h1 class="auth-title">Verifying your email</h1>
                <p class="auth-sub">One moment.</p>
            </template>

            <template v-else-if="state === 'verified'">
                <div class="status-mark ok" aria-hidden="true">✓</div>
                <h1 class="auth-title">You're verified</h1>
                <p class="auth-sub">
                    <template v-if="verifiedEmail">
                        <strong>{{ verifiedEmail }}</strong> is confirmed. Sign in to open your workspace.
                    </template>
                    <template v-else>
                        Your email is confirmed. Sign in to open your workspace.
                    </template>
                </p>
                <div class="auth-form">
                    <router-link to="/login" class="auth-submit as-link">Go to sign in</router-link>
                </div>
            </template>

            <template v-else>
                <div class="status-mark bad" aria-hidden="true">!</div>
                <h1 class="auth-title">Link didn't work</h1>
                <p class="auth-sub">{{ message }}</p>

                <div class="auth-form">
                    <template v-if="resendState !== 'sent'">
                        <div class="field">
                            <label for="resendEmail">Send a new link to</label>
                            <input id="resendEmail" v-model="resendEmail" type="email"
                                   placeholder="you@company.com" autocomplete="email"
                                   @keyup.enter="resend" />
                        </div>
                        <button type="button" class="auth-submit"
                                :disabled="!resendEmail || resendState === 'sending'"
                                @click="resend">
                            {{ resendState === 'sending' ? 'Sending…' : 'Send new link' }}
                        </button>
                    </template>
                    <p v-else class="sent-note">
                        If that address still needs verifying, a new link is on its way.
                    </p>

                    <p class="signup-prompt">
                        <router-link to="/login" class="signup-link">Back to sign in</router-link>
                    </p>
                </div>
            </template>
        </div>

        <div class="brand-panel">
            <div class="aurora-blob blob-lime"></div>
            <div class="aurora-blob blob-purple"></div>
            <div class="aurora-blob blob-teal"></div>

            <div class="brand-copy">
                <div class="orb">
                    <div class="orb-glow"></div>
                    <div class="orb-gradient"></div>
                    <div class="orb-core"></div>
                    <div class="orb-ring"></div>
                </div>
                <h2>Almost <em>there.</em></h2>
                <p class="brand-lede">Verifying your address keeps your workspace — and your customers' conversations — yours alone.</p>
            </div>
        </div>
    </div>
</template>

<style scoped>
/* Same shell as sign-in and sign-up: this page is part of that flow, and a
   customer arriving here from their inbox should recognise where they are. */
.auth-page {
    min-height: 100vh;
    display: grid;
    grid-template-columns: 1.02fr .98fr;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-sans);
}

.form-panel {
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 60px 56px;
    background: var(--bg);
    min-height: 100vh;
    min-height: 100dvh;
}

.auth-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 44px;
}

.logo-mark {
    width: 32px;
    height: 32px;
    background: var(--accent-solid);
    border-radius: 10px 10px 10px 2px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 3.5px;
    flex-shrink: 0;
}

.dot {
    width: 4.5px;
    height: 4.5px;
    background: var(--on-accent);
    border-radius: 50%;
}

.logo-word {
    font-family: var(--font-display);
    font-weight: 700;
    font-size: 18px;
    letter-spacing: -0.01em;
    color: var(--text);
}

/* Outcome badge — carries the result before the heading is read */
.status-mark {
    width: 46px;
    height: 46px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    font-weight: 700;
    margin-bottom: 20px;
}

.status-mark.ok {
    background: color-mix(in srgb, var(--accent-solid) 16%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-solid) 35%, transparent);
    color: var(--accent-ink);
}

.status-mark.bad {
    background: color-mix(in srgb, var(--c-coral) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--c-coral) 30%, transparent);
    color: var(--c-coral);
}

.status-mark.spinner {
    border: 3px solid var(--o12);
    border-top-color: var(--accent-solid);
    border-radius: 50%;
    width: 40px;
    height: 40px;
    animation: cm-spin 1s linear infinite;
}

.auth-title {
    font-family: var(--font-display);
    font-size: 40px;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
    margin-bottom: 10px;
    line-height: 1.1;
}

.auth-sub {
    color: var(--muted);
    font-size: 15px;
    margin-bottom: 32px;
    max-width: 400px;
    line-height: 1.55;
}

.auth-sub strong { color: var(--text); font-weight: 600; }

.auth-form {
    display: flex;
    flex-direction: column;
    gap: 18px;
    max-width: 400px;
}

.field {
    display: flex;
    flex-direction: column;
    gap: 9px;
}

.field label {
    font-size: 13.5px;
    font-weight: 500;
    color: var(--text3);
}

.field input {
    width: 100%;
    padding: 14px 16px;
    background: var(--o04);
    border: 1px solid var(--o12);
    border-radius: 12px;
    color: var(--text);
    font-family: var(--font-sans);
    font-size: 15px;
    transition: border-color 0.18s, box-shadow 0.18s;
}

.field input::placeholder { color: var(--faint); }

.field input:focus {
    outline: none;
    border-color: var(--accent-ink);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-ink) 15%, transparent);
}

.auth-submit {
    width: 100%;
    padding: 15px;
    background: var(--accent-solid);
    color: var(--on-accent-solid);
    border: none;
    border-radius: 12px;
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 15px;
    cursor: pointer;
    transition: opacity 0.18s;
}

.auth-submit:hover:not(:disabled) { opacity: 0.88; }
.auth-submit:disabled { opacity: 0.45; cursor: not-allowed; }

.auth-submit.as-link {
    display: block;
    text-align: center;
    text-decoration: none;
}

.sent-note {
    color: var(--text3);
    font-size: 14px;
    line-height: 1.55;
    background: var(--o04);
    border: 1px solid var(--o10);
    border-radius: 12px;
    padding: 14px 16px;
    margin: 0;
}

.signup-prompt {
    text-align: center;
    font-size: 14px;
    color: var(--muted2);
    margin: 0;
}

.signup-link {
    color: var(--accent-ink);
    text-decoration: none;
    font-weight: 500;
}
.signup-link:hover { text-decoration: underline; }

/* ── Brand panel ── */
.brand-panel {
    position: relative;
    background: linear-gradient(160deg, var(--bg-elevated), var(--bg-deep));
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 56px 6vw;
    min-height: 100vh;
    border-left: 1px solid var(--o06);
}

.aurora-blob {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    animation: cm-aurora 14s ease-in-out infinite;
}

.blob-lime {
    width: 420px;
    height: 420px;
    background: radial-gradient(circle, color-mix(in srgb, var(--accent-solid) 32%, transparent), color-mix(in srgb, var(--accent-solid) 6%, transparent));
    top: -80px;
    right: -60px;
    animation-duration: 16s;
}

.blob-purple {
    width: 360px;
    height: 360px;
    background: radial-gradient(circle, color-mix(in srgb, var(--c-purple) 28%, transparent), color-mix(in srgb, var(--c-purple) 4%, transparent));
    top: 20%;
    left: -80px;
    animation-duration: 20s;
    animation-delay: -5s;
}

.blob-teal {
    width: 300px;
    height: 300px;
    background: radial-gradient(circle, color-mix(in srgb, var(--c-teal) 22%, transparent), color-mix(in srgb, var(--c-teal) 3%, transparent));
    bottom: 15%;
    right: 10%;
    animation-duration: 18s;
    animation-delay: -9s;
}

.brand-copy {
    position: relative;
    z-index: 1;
    max-width: 460px;
}

.orb {
    position: relative;
    width: 120px;
    height: 120px;
    margin-bottom: 38px;
    animation: cm-float 7s ease-in-out infinite;
}

.orb-glow {
    position: absolute;
    inset: -36px;
    border-radius: 50%;
    background: radial-gradient(circle, color-mix(in srgb, var(--accent-solid) 20%, transparent), transparent 70%);
    filter: blur(10px);
}

.orb-gradient {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: conic-gradient(from 0deg, var(--accent-solid), var(--c-purple), var(--c-teal), var(--c-coral), var(--accent-solid));
    filter: blur(6px);
    animation: cm-spin 6s linear infinite;
}

.orb-core {
    position: absolute;
    inset: 24px;
    border-radius: 50%;
    background: radial-gradient(circle at 40% 35%, color-mix(in srgb, var(--text) 92%, transparent), color-mix(in srgb, var(--text) 12%, transparent) 55%, transparent 72%);
    animation: cm-pulse 2.6s ease-in-out infinite;
}

.orb-ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    box-shadow: inset 0 0 26px color-mix(in srgb, var(--bg-deep) 55%, transparent);
}

.brand-copy h2 {
    font-family: var(--font-display);
    font-size: 42px;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
    line-height: 1.06;
    margin: 0 0 18px;
}

.brand-copy h2 em {
    font-style: normal;
    color: var(--accent-ink);
}

.brand-lede {
    font-size: 17px;
    line-height: 1.6;
    color: var(--muted);
    margin: 0;
}

@media (max-width: 1024px) {
    .auth-page { grid-template-columns: 1fr; }
    .brand-panel { display: none; }
}

@media (max-width: 600px) {
    .form-panel { padding: 40px 28px; }
    .auth-title { font-size: 30px; }
}
</style>
