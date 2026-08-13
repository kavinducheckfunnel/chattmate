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
import { ref, computed, onMounted } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import TenantDrawer from '@/components/platform/TenantDrawer.vue'
import {
  getPlatformStats, listTenants, deleteTenant, listAudit,
  getPlatformPlans, updatePlan, getOperators,
  type PlatformStats, type TenantRow, type AuditEntry,
  type PlatformPlan, type Operator,
} from '@/services/platform'
import { extractApiError } from '@/utils/apiError'

type Tab = 'tenants' | 'plans' | 'operators' | 'audit'
const tab = ref<Tab>('tenants')
const TABS: { key: Tab; label: string }[] = [
  { key: 'tenants', label: 'Tenants' },
  { key: 'plans', label: 'Plans' },
  { key: 'operators', label: 'Operators' },
  { key: 'audit', label: 'Audit' },
]

const loading = ref(true)
const error = ref('')
const busy = ref(false)

const stats = ref<PlatformStats | null>(null)
const tenants = ref<TenantRow[]>([])
const totalTenants = ref(0)
const search = ref('')

const plans = ref<PlatformPlan[]>([])
const operators = ref<Operator[]>([])
const audit = ref<AuditEntry[]>([])

const selectedTenantId = ref<string | null>(null)
const deleteTarget = ref<TenantRow | null>(null)
const deleteConfirm = ref('')

// Draft edits for one plan at a time. Kept out of `plans` so an abandoned edit
// does not leave the table showing numbers that were never saved.
const editingPlan = ref<string | null>(null)
const planDraft = ref<Record<string, number | null>>({})

const LIMIT_FIELDS: { key: string; label: string }[] = [
  { key: 'max_conversations_per_month', label: 'Conversations / month' },
  { key: 'max_ai_messages_per_month', label: 'AI replies / month' },
  { key: 'max_agents', label: 'Agents' },
  { key: 'max_seats', label: 'Team members' },
  { key: 'max_knowledge_docs', label: 'Knowledge sources' },
]

const loadTenants = async () => {
  const t = await listTenants({ q: search.value || undefined, limit: 100 })
  tenants.value = t.tenants
  totalTenants.value = t.total
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [s] = await Promise.all([getPlatformStats(), loadTenants()])
    stats.value = s
  } catch (e) {
    error.value = extractApiError(e, 'Could not load the console')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const switchTab = async (t: Tab) => {
  tab.value = t
  try {
    if (t === 'plans' && !plans.value.length) plans.value = await getPlatformPlans()
    if (t === 'operators' && !operators.value.length) operators.value = await getOperators()
    if (t === 'audit') audit.value = await listAudit()
  } catch (e) {
    error.value = extractApiError(e, `Could not load ${t}`)
  }
}

const startEditPlan = (p: PlatformPlan) => {
  editingPlan.value = p.code
  // The API reports limits under short metric keys ("conversations") while the
  // editable columns use the long ones ("max_conversations_per_month"). Mapped
  // by hand rather than derived by string surgery: a rename on either side
  // should break the build here, not silently produce an undefined the editor
  // then saves as "unlimited".
  planDraft.value = {
    price_cents: p.price_cents,
    max_conversations_per_month: p.limits.conversations,
    max_ai_messages_per_month: p.limits.ai_messages,
    max_agents: p.limits.agents,
    max_seats: p.limits.seats,
    max_knowledge_docs: p.limits.knowledge_docs,
  }
}

const savePlan = async () => {
  if (!editingPlan.value) return
  busy.value = true
  try {
    // Empty string from a number input means "unlimited", which must be sent
    // as an explicit null — omitting the key would leave the old limit.
    const payload: Record<string, number | null> = {}
    for (const [k, v] of Object.entries(planDraft.value)) {
      payload[k] = v === null || (v as unknown as string) === '' ? null : Number(v)
    }
    const res = await updatePlan(editingPlan.value, payload)
    plans.value = await getPlatformPlans()
    editingPlan.value = null
    if (res?.tenants_affected) {
      error.value = `Saved. ${res.tenants_affected} tenant(s) are on this plan and are affected immediately.`
    }
  } catch (e) {
    error.value = extractApiError(e, 'Could not save plan')
  } finally {
    busy.value = false
  }
}

const confirmDelete = async () => {
  if (!deleteTarget.value) return
  busy.value = true
  try {
    await deleteTenant(deleteTarget.value.id, deleteConfirm.value.trim().toLowerCase())
    deleteTarget.value = null
    deleteConfirm.value = ''
    selectedTenantId.value = null
    await load()
  } catch (e) {
    error.value = extractApiError(e, 'Could not delete tenant')
  } finally {
    busy.value = false
  }
}

const deleteArmed = computed(
  () => deleteTarget.value !== null &&
        deleteConfirm.value.trim().toLowerCase() === deleteTarget.value.domain.toLowerCase(),
)

const plansForDrawer = computed(() => plans.value.filter((p) => p.is_active))

const num = (n: number) => n.toLocaleString()
const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
const dateTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'
const money = (cents: number, currency: string) =>
  cents === 0 ? 'Free'
    : (cents / 100).toLocaleString(undefined, { style: 'currency', currency, maximumFractionDigits: 0 })

// Ensure the drawer has a plan list even if the Plans tab was never opened.
onMounted(async () => {
  if (!plans.value.length) {
    try { plans.value = await getPlatformPlans() } catch { /* surfaced on the tab */ }
  }
})
</script>

<template>
  <DashboardLayout>
    <div class="console">
      <header class="console-head">
        <div>
          <h1>Platform console</h1>
          <p class="sub">Every tenant on this deployment</p>
        </div>
        <button class="btn btn-secondary" @click="load" :disabled="loading">Refresh</button>
      </header>

      <div v-if="error" class="alert-error" role="alert">
        {{ error }}
        <button class="dismiss" @click="error = ''" aria-label="Dismiss">×</button>
      </div>

      <section v-if="stats" class="stat-strip">
        <div class="stat">
          <span class="stat-value">{{ num(stats.organizations.total) }}</span>
          <span class="stat-label">Tenants</span>
        </div>
        <div class="stat" :class="{ flagged: stats.organizations.suspended > 0 }">
          <span class="stat-value">{{ num(stats.organizations.suspended) }}</span>
          <span class="stat-label">Suspended</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ num(stats.users) }}</span>
          <span class="stat-label">Users</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ num(stats.usage.conversations) }}</span>
          <span class="stat-label">Conversations this month</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ num(stats.usage.ai_messages) }}</span>
          <span class="stat-label">AI replies this month</span>
        </div>
      </section>

      <nav class="tabs">
        <button
          v-for="t in TABS" :key="t.key"
          class="tab" :class="{ active: tab === t.key }"
          @click="switchTab(t.key)"
        >{{ t.label }}</button>
      </nav>

      <!-- Tenants -->
      <section v-if="tab === 'tenants'" class="card card-full">
        <div class="table-head">
          <h2>Tenants <span class="count">{{ totalTenants }}</span></h2>
          <input v-model="search" class="search" type="search"
                 placeholder="Search name or domain…" @keyup.enter="loadTenants" />
        </div>

        <div v-if="loading" class="empty">Loading…</div>
        <div v-else-if="!tenants.length" class="empty">No tenants match.</div>
        <div v-else class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th>Tenant</th><th>Plan</th>
                <th class="num">Seats</th><th class="num">Agents</th>
                <th class="num">Chats</th><th class="num">AI replies</th>
                <th>Joined</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tenants" :key="t.id" :class="{ dim: !t.is_active }">
                <td>
                  <div class="name">
                    {{ t.name }}
                    <span v-if="!t.is_active" class="pill danger">Suspended</span>
                  </div>
                  <div class="meta">{{ t.domain }}</div>
                </td>
                <td><span class="pill">{{ t.plan_code || 'none' }}</span></td>
                <td class="num">{{ num(t.seats) }}</td>
                <td class="num">{{ num(t.agents) }}</td>
                <td class="num">{{ num(t.conversations) }}</td>
                <td class="num">{{ num(t.ai_messages) }}</td>
                <td class="meta">{{ date(t.created_at) }}</td>
                <td class="actions">
                  <button class="btn btn-ghost btn-sm" @click="selectedTenantId = t.id">Manage</button>
                  <button class="btn btn-ghost btn-sm danger"
                          @click="deleteTarget = t; deleteConfirm = ''">Delete</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Plans -->
      <section v-else-if="tab === 'plans'" class="card card-full">
        <h2>Plans</h2>
        <p class="note">
          Limits apply live. Lowering one can put existing tenants over quota
          immediately — the tenant count shows who is affected. Leave a field
          empty for unlimited.
        </p>
        <div class="table-scroll">
          <table class="grid">
            <thead>
              <tr>
                <th>Plan</th><th>Price</th>
                <th v-for="f in LIMIT_FIELDS" :key="f.key" class="num">{{ f.label }}</th>
                <th class="num">Tenants</th><th></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="p in plans" :key="p.code">
                <tr :class="{ dim: !p.is_active }">
                  <td>
                    <div class="name">{{ p.name }}<span v-if="p.is_default" class="pill">default</span></div>
                    <div class="meta mono">{{ p.code }}</div>
                  </td>
                  <td>{{ money(p.price_cents, p.currency) }}</td>
                  <td class="num">{{ p.limits.conversations ?? '∞' }}</td>
                  <td class="num">{{ p.limits.ai_messages ?? '∞' }}</td>
                  <td class="num">{{ p.limits.agents ?? '∞' }}</td>
                  <td class="num">{{ p.limits.seats ?? '∞' }}</td>
                  <td class="num">{{ p.limits.knowledge_docs ?? '∞' }}</td>
                  <td class="num">{{ p.tenant_count }}</td>
                  <td class="actions">
                    <button class="btn btn-ghost btn-sm" @click="startEditPlan(p)">Edit</button>
                  </td>
                </tr>
                <tr v-if="editingPlan === p.code" class="edit-row">
                  <td :colspan="9">
                    <div class="edit-grid">
                      <label>
                        <span>Price (cents)</span>
                        <input v-model.number="planDraft.price_cents" type="number" min="0" />
                      </label>
                      <label v-for="f in LIMIT_FIELDS" :key="f.key">
                        <span>{{ f.label }}</span>
                        <input v-model="planDraft[f.key]" type="number" min="0" placeholder="unlimited" />
                      </label>
                    </div>
                    <div class="edit-actions">
                      <button class="btn btn-secondary btn-sm" @click="editingPlan = null" :disabled="busy">Cancel</button>
                      <button class="btn btn-primary btn-sm" @click="savePlan" :disabled="busy">
                        {{ busy ? 'Saving…' : 'Save' }}
                      </button>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Operators -->
      <section v-else-if="tab === 'operators'" class="card card-full">
        <h2>Platform operators</h2>
        <p class="note">
          Read-only. Granting and revoking require shell access —
          <code>scripts/grant_platform_admin.py</code> — so a stolen console session
          cannot quietly add a second operator.
        </p>
        <ul class="stack">
          <li v-for="o in operators" :key="o.id" class="stack-row">
            <div>
              <div class="name">{{ o.full_name || o.email }}</div>
              <div class="meta">
                {{ o.email }} ·
                <template v-if="o.tenant">also a member of {{ o.tenant }}</template>
                <template v-else>standalone (no tenant)</template>
              </div>
            </div>
            <span class="pill" :class="o.is_active ? 'ok' : 'danger'">
              {{ o.is_active ? 'Active' : 'Disabled' }}
            </span>
          </li>
        </ul>
      </section>

      <!-- Audit -->
      <section v-else-if="tab === 'audit'" class="card card-full">
        <h2>Audit trail</h2>
        <p class="note">Every action taken across the tenant boundary, newest first.</p>
        <div v-if="!audit.length" class="empty">Nothing recorded yet.</div>
        <div v-else class="table-scroll">
          <table class="grid">
            <thead>
              <tr><th>When</th><th>Operator</th><th>Action</th><th>Tenant</th><th>Detail</th><th>IP</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in audit" :key="a.id">
                <td class="meta">{{ dateTime(a.created_at) }}</td>
                <td>{{ a.actor_email }}</td>
                <td>
                  <span class="pill" :class="{
                    danger: a.action.endsWith('delete'),
                    warn: a.action === 'conversation.read',
                  }">{{ a.action }}</span>
                </td>
                <td>{{ a.target_organization_domain || '—' }}</td>
                <td class="meta detail">{{ JSON.stringify(a.details) }}</td>
                <td class="meta">{{ a.ip_address || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <TenantDrawer
      v-if="selectedTenantId"
      :tenant-id="selectedTenantId"
      :plans="plansForDrawer"
      @close="selectedTenantId = null"
      @changed="load"
    />

    <!-- Delete confirmation -->
    <div v-if="deleteTarget" class="modal-backdrop">
      <div class="modal">
        <h2>Delete {{ deleteTarget.name }}?</h2>
        <p class="modal-copy">
          This permanently removes every agent, conversation, document and user
          belonging to <strong>{{ deleteTarget.domain }}</strong>. It cannot be undone.
        </p>
        <label class="confirm-label" for="cd">Type <code>{{ deleteTarget.domain }}</code> to confirm</label>
        <input id="cd" v-model="deleteConfirm" class="confirm-input" autocomplete="off" />
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="deleteTarget = null" :disabled="busy">Cancel</button>
          <button class="btn btn-danger" :disabled="!deleteArmed || busy" @click="confirmDelete">
            {{ busy ? 'Deleting…' : 'Delete permanently' }}
          </button>
        </div>
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.console {
  padding: var(--space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  overflow-y: auto;
  height: 100%;
}

.console-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  flex-wrap: wrap;
}

.console-head h1 {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  color: var(--text);
  margin: 0 0 var(--space-xs);
}

.sub { color: var(--muted); font-size: var(--text-sm); margin: 0; }

.alert-error {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  color: var(--error-color);
  background: var(--error-bg);
  border: 1px solid color-mix(in srgb, var(--error-color) 25%, transparent);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  font-size: var(--text-sm);
}

.dismiss {
  background: none; border: none; color: inherit;
  font-size: 18px; line-height: 1; cursor: pointer; padding: 0;
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-md);
}

.stat {
  background: var(--surface);
  border: 1px solid var(--o08);
  border-radius: var(--radius-lg);
  padding: var(--space-md) var(--space-lg);
}

.stat.flagged { border-color: color-mix(in srgb, var(--error-color) 35%, transparent); }

.stat-value {
  display: block;
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.stat-label { display: block; font-size: var(--text-xs); color: var(--muted2); margin-top: var(--space-xs); }

.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--o08); overflow-x: auto; }

.tab {
  background: none; border: none;
  border-bottom: 2px solid transparent;
  padding: var(--space-md);
  color: var(--muted2);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  cursor: pointer;
  white-space: nowrap;
}

.tab:hover { color: var(--text3); }
.tab.active { color: var(--text); border-bottom-color: var(--accent-solid); font-weight: 600; }

.card h2 {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  color: var(--text);
  margin: 0 0 var(--space-sm);
}

.note {
  font-size: var(--text-xs);
  color: var(--muted2);
  line-height: 1.55;
  margin: 0 0 var(--space-lg);
  max-width: 70ch;
}

.note code {
  font-family: var(--font-mono);
  background: var(--o08);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
}

.table-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-md); margin-bottom: var(--space-lg); flex-wrap: wrap;
}

.count {
  font-size: var(--text-xs); color: var(--muted2);
  background: var(--o08); border-radius: var(--radius-pill);
  padding: 2px 8px; margin-left: var(--space-xs); font-weight: 500;
}

.search {
  padding: 9px 14px;
  background: var(--o04);
  border: 1px solid var(--o12);
  border-radius: var(--radius-input);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  min-width: 220px;
}
.search:focus { outline: none; border-color: var(--accent-ink); }

.table-scroll { overflow-x: auto; }

.grid { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }

.grid th {
  text-align: left;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted2);
  font-weight: 600;
  padding: 0 var(--space-md) var(--space-sm);
  white-space: nowrap;
}

.grid td { padding: var(--space-md); border-top: 1px solid var(--o06); color: var(--text3); vertical-align: middle; }
.grid .num { text-align: right; font-variant-numeric: tabular-nums; }
.grid tr.dim { opacity: 0.55; }

.name { color: var(--text); font-weight: 600; display: flex; align-items: center; gap: var(--space-sm); }
.meta { font-size: var(--text-xs); color: var(--muted2); margin-top: 2px; }
.meta.mono { font-family: var(--font-mono); }
.detail { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.actions { display: flex; gap: var(--space-xs); justify-content: flex-end; }
.btn-sm { padding: 5px 12px; font-size: var(--text-xs); }
.btn-ghost.danger { color: var(--error-color); }

.pill {
  display: inline-block; font-size: var(--text-xs);
  padding: 2px 9px; border-radius: var(--radius-pill);
  background: var(--o08); color: var(--text3); white-space: nowrap;
}
.pill.ok { background: var(--success-bg); color: var(--success-color); }
.pill.danger { background: var(--error-bg); color: var(--error-color); }
.pill.warn { background: var(--warning-bg); color: var(--warning-color); }

.empty { color: var(--muted2); font-size: var(--text-sm); padding: var(--space-lg) 0; }

.stack { list-style: none; margin: 0; padding: 0; }
.stack-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-md); padding: var(--space-md) 0; border-top: 1px solid var(--o06);
}

/* Plan editor */
.edit-row td { background: var(--o04); }

.edit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-md);
}

.edit-grid label { display: flex; flex-direction: column; gap: var(--space-xs); }
.edit-grid span { font-size: var(--text-xs); color: var(--muted2); }

.edit-grid input {
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--o12);
  border-radius: var(--radius-md);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
}
.edit-grid input:focus { outline: none; border-color: var(--accent-ink); }

.edit-actions { display: flex; gap: var(--space-sm); justify-content: flex-end; margin-top: var(--space-md); }

/* Delete modal */
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(5, 6, 9, 0.72);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: var(--space-md);
}

.modal {
  background: var(--surface);
  border: 1px solid var(--o10);
  border-radius: var(--radius-card-lg);
  padding: var(--space-xl);
  width: 100%; max-width: 440px;
}

.modal h2 { font-family: var(--font-display); font-size: var(--text-xl); color: var(--text); margin: 0 0 var(--space-md); }
.modal-copy { color: var(--muted); font-size: var(--text-sm); line-height: 1.6; margin: 0 0 var(--space-lg); }
.modal-copy strong { color: var(--text); }

.confirm-label { display: block; font-size: var(--text-sm); color: var(--text3); margin-bottom: var(--space-sm); }
.confirm-label code {
  background: var(--o08); padding: 1px 6px; border-radius: var(--radius-sm);
  color: var(--accent-ink); font-family: var(--font-mono);
}

.confirm-input {
  width: 100%; padding: 12px 14px;
  background: var(--o04); border: 1px solid var(--o12);
  border-radius: var(--radius-input); color: var(--text);
  font-family: var(--font-mono); font-size: var(--text-sm);
}
.confirm-input:focus { outline: none; border-color: var(--error-color); }

.modal-actions { display: flex; gap: var(--space-sm); margin-top: var(--space-lg); }
.modal-actions .btn { flex: 1; }

@media (max-width: 640px) { .console { padding: var(--space-md); } }
</style>
