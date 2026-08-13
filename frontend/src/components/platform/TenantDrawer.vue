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
import { ref, watch } from 'vue'
import {
  getTenant, updateTenant, updateTenantUser,
  getTenantAgents, getTenantKnowledge, getTenantIntegrations, getTenantConversations,
  type TenantDetail, type TenantAgent, type KnowledgeSource,
  type TenantIntegrations, type ConversationRow,
} from '@/services/platform'
import type { Plan } from '@/services/usage'
import { extractApiError } from '@/utils/apiError'
import TranscriptModal from './TranscriptModal.vue'

const props = defineProps<{ tenantId: string; plans: Plan[] }>()
const emit = defineEmits<{ close: []; changed: [] }>()

type Tab = 'overview' | 'agents' | 'knowledge' | 'conversations' | 'integrations' | 'people'
const tab = ref<Tab>('overview')

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'agents', label: 'Agents' },
  { key: 'knowledge', label: 'Knowledge' },
  { key: 'conversations', label: 'Conversations' },
  { key: 'integrations', label: 'Integrations' },
  { key: 'people', label: 'People' },
]

const detail = ref<TenantDetail | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')

const agents = ref<TenantAgent[]>([])
const knowledge = ref<{ total: number; sources: KnowledgeSource[] } | null>(null)
const integrations = ref<TenantIntegrations | null>(null)
const conversations = ref<ConversationRow[]>([])
const conversationTotal = ref(0)
const openSession = ref<string | null>(null)

// Loaded once per drawer open, per tab. Re-fetching on every tab click would
// make switching back and forth feel broken on a slow connection.
const loaded = ref<Set<Tab>>(new Set())

const resetPasswordFor = ref<string | null>(null)
const newPassword = ref('')

const loadDetail = async () => {
  loading.value = true
  try {
    detail.value = await getTenant(props.tenantId)
  } catch (e) {
    error.value = extractApiError(e, 'Could not load tenant')
  } finally {
    loading.value = false
  }
}

const loadTab = async (t: Tab) => {
  if (loaded.value.has(t) || t === 'overview' || t === 'people') return
  try {
    if (t === 'agents') agents.value = await getTenantAgents(props.tenantId)
    if (t === 'knowledge') knowledge.value = await getTenantKnowledge(props.tenantId)
    if (t === 'integrations') integrations.value = await getTenantIntegrations(props.tenantId)
    if (t === 'conversations') {
      const r = await getTenantConversations(props.tenantId, { limit: 50 })
      conversations.value = r.conversations
      conversationTotal.value = r.total
    }
    loaded.value.add(t)
  } catch (e) {
    error.value = extractApiError(e, `Could not load ${t}`)
  }
}

watch(() => props.tenantId, () => {
  loaded.value = new Set()
  tab.value = 'overview'
  loadDetail()
}, { immediate: true })

watch(tab, (t) => loadTab(t))

const setActive = async (active: boolean) => {
  busy.value = true
  try {
    await updateTenant(props.tenantId, { is_active: active })
    await loadDetail()
    emit('changed')
  } catch (e) {
    error.value = extractApiError(e, 'Could not update tenant')
  } finally {
    busy.value = false
  }
}

const changePlan = async (code: string) => {
  if (code === detail.value?.plan_code) return
  busy.value = true
  try {
    await updateTenant(props.tenantId, { plan_code: code })
    await loadDetail()
    emit('changed')
  } catch (e) {
    error.value = extractApiError(e, 'Could not change plan')
  } finally {
    busy.value = false
  }
}

const toggleUser = async (userId: string, active: boolean) => {
  busy.value = true
  try {
    await updateTenantUser(userId, { is_active: active })
    await loadDetail()
  } catch (e) {
    error.value = extractApiError(e, 'Could not update user')
  } finally {
    busy.value = false
  }
}

const submitPassword = async () => {
  if (!resetPasswordFor.value || !newPassword.value) return
  busy.value = true
  try {
    await updateTenantUser(resetPasswordFor.value, { new_password: newPassword.value })
    resetPasswordFor.value = null
    newPassword.value = ''
  } catch (e) {
    error.value = extractApiError(e, 'Could not reset password')
  } finally {
    busy.value = false
  }
}

const num = (n: number) => n.toLocaleString()
const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
const dateTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

/** URLs and file paths are long; show enough of each end to identify it. */
const shorten = (s: string, max = 58) =>
  s.length <= max ? s : `${s.slice(0, max - 16)}…${s.slice(-14)}`
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <aside class="drawer">
      <div v-if="loading" class="state">Loading…</div>

      <template v-else-if="detail">
        <header class="head">
          <div>
            <h2>{{ detail.name }}</h2>
            <p class="sub">
              {{ detail.domain }}
              <span class="pill" :class="detail.is_active ? 'ok' : 'danger'">
                {{ detail.is_active ? 'Active' : 'Suspended' }}
              </span>
            </p>
          </div>
          <button class="close" @click="emit('close')" aria-label="Close">×</button>
        </header>

        <nav class="tabs">
          <button
            v-for="t in TABS" :key="t.key"
            class="tab" :class="{ active: tab === t.key }"
            @click="tab = t.key"
          >{{ t.label }}</button>
        </nav>

        <div v-if="error" class="alert">{{ error }}</div>

        <div class="body">
          <!-- Overview -->
          <template v-if="tab === 'overview'">
            <div class="row"><span class="k">Joined</span><span>{{ date(detail.created_at) }}</span></div>
            <div class="row"><span class="k">Timezone</span><span>{{ detail.timezone }}</span></div>

            <h3>Plan</h3>
            <div class="chips">
              <button
                v-for="p in plans" :key="p.code"
                class="chip" :class="{ active: p.code === detail.plan_code }"
                :disabled="busy" @click="changePlan(p.code)"
              >{{ p.name }}</button>
            </div>

            <h3>Usage this month</h3>
            <ul class="stack">
              <li v-for="(m, key) in detail.usage.metrics" :key="key" class="row">
                <span class="k">{{ String(key).replace(/_/g, ' ') }}</span>
                <span :class="{ over: m.exceeded }">
                  {{ num(m.used) }}<span class="muted"> / {{ m.limit === null ? '∞' : num(m.limit) }}</span>
                </span>
              </li>
            </ul>
          </template>

          <!-- Agents -->
          <template v-else-if="tab === 'agents'">
            <div v-if="!agents.length" class="state">No agents configured.</div>
            <ul v-else class="stack">
              <li v-for="a in agents" :key="a.id" class="card-row">
                <div class="card-row-main">
                  <div class="title">
                    {{ a.display_name || a.name }}
                    <span class="pill" :class="a.is_active ? 'ok' : ''">
                      {{ a.is_active ? 'Live' : 'Draft' }}
                    </span>
                  </div>
                  <div class="meta">
                    {{ a.agent_type || 'agent' }} ·
                    {{ a.instruction_count }} instruction{{ a.instruction_count === 1 ? '' : 's' }}
                    <template v-if="a.use_workflow"> · workflow</template>
                    <template v-if="a.transfer_to_human"> · human handoff</template>
                  </div>
                </div>
              </li>
            </ul>
          </template>

          <!-- Knowledge -->
          <template v-else-if="tab === 'knowledge'">
            <div v-if="!knowledge || !knowledge.sources.length" class="state">
              No knowledge sources. This is the usual reason an agent answers
              "I don't know".
            </div>
            <template v-else>
              <p class="count-note">{{ num(knowledge.total) }} source(s)</p>
              <ul class="stack">
                <li v-for="k in knowledge.sources" :key="k.id" class="card-row">
                  <div class="card-row-main">
                    <div class="title mono">{{ shorten(k.source) }}</div>
                    <div class="meta">{{ k.source_type }} · added {{ date(k.created_at) }}</div>
                  </div>
                </li>
              </ul>
            </template>
          </template>

          <!-- Conversations -->
          <template v-else-if="tab === 'conversations'">
            <div v-if="!conversations.length" class="state">No conversations yet.</div>
            <template v-else>
              <p class="count-note">
                {{ num(conversationTotal) }} total · opening one is recorded in the audit log
              </p>
              <ul class="stack">
                <li
                  v-for="c in conversations" :key="c.session_id"
                  class="card-row clickable" @click="openSession = c.session_id"
                >
                  <div class="card-row-main">
                    <div class="title">{{ c.customer?.email || 'Anonymous visitor' }}</div>
                    <div class="meta">
                      {{ c.channel }} · {{ c.message_count }} messages
                      <template v-if="c.agent_name"> · {{ c.agent_name }}</template>
                      · {{ dateTime(c.updated_at) }}
                    </div>
                  </div>
                  <span class="pill" :class="c.status === 'OPEN' ? 'ok' : ''">{{ c.status }}</span>
                </li>
              </ul>
            </template>
          </template>

          <!-- Integrations -->
          <template v-else-if="tab === 'integrations'">
            <h3>Channels</h3>
            <div v-if="!integrations?.channels.length" class="state">No channels connected.</div>
            <ul v-else class="stack">
              <li v-for="c in integrations.channels" :key="c.id" class="card-row">
                <div class="card-row-main">
                  <div class="title">{{ c.display_name || c.channel_type }}</div>
                  <div class="meta">{{ c.channel_type }}</div>
                </div>
                <span class="pill" :class="c.is_active ? 'ok' : ''">
                  {{ c.is_active ? 'Active' : 'Inactive' }}
                </span>
              </li>
            </ul>

            <h3>Widgets</h3>
            <div v-if="!integrations?.widgets.length" class="state">No widgets.</div>
            <ul v-else class="stack">
              <li v-for="w in integrations.widgets" :key="w.id" class="card-row">
                <div class="card-row-main">
                  <div class="title">{{ w.name }}</div>
                  <div class="meta mono">{{ w.id }}</div>
                </div>
              </li>
            </ul>
            <p class="privacy-note">
              Channel credentials and webhook secrets are never exposed here.
            </p>
          </template>

          <!-- People -->
          <template v-else-if="tab === 'people'">
            <ul class="stack">
              <li v-for="u in detail.users" :key="u.id" class="card-row">
                <div class="card-row-main">
                  <div class="title">{{ u.full_name || u.email }}</div>
                  <div class="meta">
                    {{ u.email }} · {{ u.role || 'no role' }}
                    <template v-if="!u.is_email_verified"> · unverified</template>
                  </div>
                </div>
                <div class="row-actions">
                  <button class="btn btn-ghost btn-sm" :disabled="busy"
                          @click="resetPasswordFor = u.id; newPassword = ''">
                    Reset password
                  </button>
                  <button class="btn btn-ghost btn-sm" :disabled="busy"
                          @click="toggleUser(u.id, !u.is_active)">
                    {{ u.is_active ? 'Deactivate' : 'Activate' }}
                  </button>
                </div>
              </li>
            </ul>
          </template>
        </div>

        <footer class="foot">
          <button v-if="detail.is_active" class="btn btn-secondary" :disabled="busy"
                  @click="setActive(false)">Suspend tenant</button>
          <button v-else class="btn btn-primary" :disabled="busy"
                  @click="setActive(true)">Reactivate</button>
        </footer>
      </template>
    </aside>

    <!-- Password reset -->
    <div v-if="resetPasswordFor" class="modal-backdrop" @click.self="resetPasswordFor = null">
      <div class="modal">
        <h2>Set a new password</h2>
        <p class="modal-copy">
          This signs the user out everywhere. Send them the new password over a
          channel you trust, and ask them to change it.
        </p>
        <input v-model="newPassword" type="text" class="pw-input"
               placeholder="New password" autocomplete="off" />
        <p class="hint">At least 8 characters, with 3 of: uppercase, lowercase, number, symbol.</p>
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="resetPasswordFor = null" :disabled="busy">Cancel</button>
          <button class="btn btn-primary" :disabled="!newPassword || busy" @click="submitPassword">
            {{ busy ? 'Saving…' : 'Set password' }}
          </button>
        </div>
      </div>
    </div>

    <TranscriptModal
      v-if="openSession"
      :tenant-id="tenantId"
      :session-id="openSession"
      @close="openSession = null"
    />
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 9, 0.6);
  backdrop-filter: blur(3px);
  z-index: 900;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: min(560px, 100%);
  background: var(--surface);
  border-left: 1px solid var(--o10);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-lg);
  border-bottom: 1px solid var(--o08);
}

.head h2 {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  color: var(--text);
  margin: 0 0 4px;
}

.sub {
  color: var(--muted2);
  font-size: var(--text-xs);
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.close {
  background: none;
  border: 1px solid var(--o12);
  border-radius: var(--radius-md);
  width: 30px; height: 30px;
  color: var(--muted2);
  font-size: 18px; cursor: pointer; flex-shrink: 0;
}
.close:hover { background: var(--o06); color: var(--text); }

.tabs {
  display: flex;
  gap: 2px;
  padding: 0 var(--space-lg);
  border-bottom: 1px solid var(--o08);
  overflow-x: auto;
}

.tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: var(--space-md) var(--space-sm);
  color: var(--muted2);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  cursor: pointer;
  white-space: nowrap;
}

.tab:hover { color: var(--text3); }
.tab.active { color: var(--text); border-bottom-color: var(--accent-solid); font-weight: 600; }

.alert {
  margin: var(--space-md) var(--space-lg) 0;
  padding: var(--space-sm) var(--space-md);
  background: var(--error-bg);
  border: 1px solid color-mix(in srgb, var(--error-color) 25%, transparent);
  border-radius: var(--radius-md);
  color: var(--error-color);
  font-size: var(--text-xs);
}

.body { padding: var(--space-lg); overflow-y: auto; flex: 1; }

.body h3 {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted2);
  margin: var(--space-xl) 0 var(--space-md);
}
.body h3:first-child { margin-top: 0; }

.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-sm) 0;
  font-size: var(--text-sm);
  color: var(--text3);
}

.row .k { color: var(--muted2); text-transform: capitalize; }
.row .muted { color: var(--muted2); }
.row .over { color: var(--error-color); font-weight: 600; }

.stack { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }

.card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-md) 0;
  border-bottom: 1px solid var(--o06);
}

.card-row.clickable { cursor: pointer; }
.card-row.clickable:hover { background: var(--o04); }

.card-row-main { min-width: 0; flex: 1; }

.title {
  font-size: var(--text-sm);
  color: var(--text2);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.title.mono { font-family: var(--font-mono); font-size: var(--text-xs); }
.meta { font-size: var(--text-xs); color: var(--muted2); margin-top: 3px; }
.meta.mono { font-family: var(--font-mono); }

.row-actions { display: flex; gap: var(--space-xs); flex-shrink: 0; }
.btn-sm { padding: 4px 10px; font-size: var(--text-xs); }

.chips { display: flex; flex-wrap: wrap; gap: var(--space-sm); }

.chip {
  padding: 7px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--o12);
  background: transparent;
  color: var(--text3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  cursor: pointer;
}

.chip:hover:not(:disabled) { border-color: var(--accent-border); color: var(--text); }
.chip.active { background: var(--accent-solid); border-color: var(--accent-solid); color: #0B0C10; font-weight: 600; }
.chip:disabled { opacity: 0.5; cursor: not-allowed; }

.pill {
  display: inline-block;
  font-size: var(--text-xs);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  background: var(--o08);
  color: var(--muted2);
  white-space: nowrap;
}
.pill.ok { background: var(--success-bg); color: var(--success-color); }
.pill.danger { background: var(--error-bg); color: var(--error-color); }

.state { color: var(--muted2); font-size: var(--text-sm); padding: var(--space-xl) 0; text-align: center; }
.count-note { font-size: var(--text-xs); color: var(--muted2); margin: 0 0 var(--space-md); }

.privacy-note {
  margin-top: var(--space-lg);
  padding: var(--space-md);
  background: var(--o04);
  border: 1px solid var(--o08);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  color: var(--muted2);
}

.foot { padding: var(--space-lg); border-top: 1px solid var(--o08); }
.foot .btn { width: 100%; }

/* Password modal */
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(5, 6, 9, 0.72);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1100; padding: var(--space-md);
}

.modal {
  background: var(--surface);
  border: 1px solid var(--o10);
  border-radius: var(--radius-card-lg);
  padding: var(--space-xl);
  width: 100%; max-width: 420px;
}

.modal h2 {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  color: var(--text);
  margin: 0 0 var(--space-sm);
}

.modal-copy { color: var(--muted); font-size: var(--text-sm); line-height: 1.55; margin: 0 0 var(--space-lg); }

.pw-input {
  width: 100%;
  padding: 12px 14px;
  background: var(--o04);
  border: 1px solid var(--o12);
  border-radius: var(--radius-input);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.pw-input:focus { outline: none; border-color: var(--accent-ink); }
.hint { font-size: var(--text-xs); color: var(--muted2); margin: var(--space-sm) 0 0; }
.modal-actions { display: flex; gap: var(--space-sm); margin-top: var(--space-lg); }
.modal-actions .btn { flex: 1; }

@media (max-width: 640px) {
  .drawer { width: 100%; }
}
</style>
