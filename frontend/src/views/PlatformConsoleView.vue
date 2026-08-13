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
import {
  getPlatformStats, listTenants, getTenant, updateTenant, deleteTenant, listAudit,
  type PlatformStats, type TenantRow, type TenantDetail, type AuditEntry,
} from '@/services/platform'
import { getPlans, type Plan } from '@/services/usage'
import { extractApiError } from '@/utils/apiError'

const loading = ref(true)
const error = ref('')
const stats = ref<PlatformStats | null>(null)
const tenants = ref<TenantRow[]>([])
const totalTenants = ref(0)
const plans = ref<Plan[]>([])
const search = ref('')

const selected = ref<TenantDetail | null>(null)
const detailLoading = ref(false)
const busy = ref(false)

const audit = ref<AuditEntry[]>([])
const showAudit = ref(false)

// Deleting a tenant destroys every conversation it owns, so the domain has to
// be typed. The server enforces this too — this is the humane half, not the
// security half.
const deleteTarget = ref<TenantDetail | null>(null)
const deleteConfirm = ref('')

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [s, t, p] = await Promise.all([
      getPlatformStats(),
      listTenants({ q: search.value || undefined, limit: 100 }),
      getPlans(),
    ])
    stats.value = s
    tenants.value = t.tenants
    totalTenants.value = t.total
    plans.value = p
  } catch (e) {
    error.value = extractApiError(e, 'Could not load the console')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const openTenant = async (row: TenantRow) => {
  detailLoading.value = true
  selected.value = null
  try {
    selected.value = await getTenant(row.id)
  } catch (e) {
    error.value = extractApiError(e, 'Could not load tenant')
  } finally {
    detailLoading.value = false
  }
}

const closeTenant = () => { selected.value = null }

const setActive = async (active: boolean) => {
  if (!selected.value) return
  busy.value = true
  try {
    await updateTenant(selected.value.id, { is_active: active })
    selected.value = await getTenant(selected.value.id)
    await load()
  } catch (e) {
    error.value = extractApiError(e, 'Could not update tenant')
  } finally {
    busy.value = false
  }
}

const changePlan = async (code: string) => {
  if (!selected.value || code === selected.value.plan_code) return
  busy.value = true
  try {
    await updateTenant(selected.value.id, { plan_code: code })
    selected.value = await getTenant(selected.value.id)
    await load()
  } catch (e) {
    error.value = extractApiError(e, 'Could not change plan')
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
    selected.value = null
    await load()
  } catch (e) {
    error.value = extractApiError(e, 'Could not delete tenant')
  } finally {
    busy.value = false
  }
}

const openAudit = async () => {
  showAudit.value = true
  try {
    audit.value = await listAudit()
  } catch (e) {
    error.value = extractApiError(e, 'Could not load the audit trail')
  }
}

const num = (n: number) => n.toLocaleString()
const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
const dateTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

const planName = (code: string | null) =>
  plans.value.find((p) => p.code === code)?.name ?? code ?? 'None'

const deleteArmed = computed(
  () => deleteTarget.value !== null &&
        deleteConfirm.value.trim().toLowerCase() === deleteTarget.value.domain.toLowerCase(),
)
</script>

<template>
  <DashboardLayout>
    <div class="console">
      <header class="console-head">
        <div>
          <h1>Platform console</h1>
          <p class="sub">Every tenant on this deployment</p>
        </div>
        <div class="head-actions">
          <button class="btn btn-secondary" @click="openAudit">Audit trail</button>
          <button class="btn btn-secondary" @click="load" :disabled="loading">Refresh</button>
        </div>
      </header>

      <div v-if="error" class="alert-error" role="alert">{{ error }}</div>

      <!-- Headline numbers -->
      <section v-if="stats" class="stat-strip">
        <div class="stat">
          <span class="stat-value">{{ num(stats.organizations.total) }}</span>
          <span class="stat-label">Tenants</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ num(stats.organizations.active) }}</span>
          <span class="stat-label">Active</span>
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

      <!-- Tenants -->
      <section class="card card-full">
        <div class="table-head">
          <h2>Tenants <span class="count">{{ totalTenants }}</span></h2>
          <input
            v-model="search"
            class="search"
            type="search"
            placeholder="Search name or domain…"
            @keyup.enter="load"
          />
        </div>

        <div v-if="loading" class="empty">Loading…</div>
        <div v-else-if="!tenants.length" class="empty">No tenants match.</div>

        <div v-else class="table-scroll">
          <table class="tenant-table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Plan</th>
                <th class="num">Seats</th>
                <th class="num">Agents</th>
                <th class="num">Chats</th>
                <th class="num">AI replies</th>
                <th>Joined</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tenants" :key="t.id" :class="{ suspended: !t.is_active }">
                <td>
                  <div class="tenant-name">
                    {{ t.name }}
                    <span v-if="!t.is_active" class="pill danger">Suspended</span>
                  </div>
                  <div class="tenant-domain">{{ t.domain }}</div>
                </td>
                <td><span class="pill">{{ planName(t.plan_code) }}</span></td>
                <td class="num">{{ num(t.seats) }}</td>
                <td class="num">{{ num(t.agents) }}</td>
                <td class="num">{{ num(t.conversations) }}</td>
                <td class="num">{{ num(t.ai_messages) }}</td>
                <td class="muted">{{ date(t.created_at) }}</td>
                <td><button class="btn btn-ghost btn-sm" @click="openTenant(t)">Manage</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <!-- Tenant detail -->
    <div v-if="selected || detailLoading" class="drawer-backdrop" @click.self="closeTenant">
      <aside class="drawer">
        <div v-if="detailLoading" class="empty">Loading…</div>
        <template v-else-if="selected">
          <header class="drawer-head">
            <div>
              <h2>{{ selected.name }}</h2>
              <p class="sub">{{ selected.domain }}</p>
            </div>
            <button class="close" @click="closeTenant" aria-label="Close">×</button>
          </header>

          <div class="drawer-body">
            <div class="field-row">
              <span class="field-label">Status</span>
              <span class="pill" :class="selected.is_active ? 'ok' : 'danger'">
                {{ selected.is_active ? 'Active' : 'Suspended' }}
              </span>
            </div>
            <div class="field-row">
              <span class="field-label">Joined</span>
              <span>{{ date(selected.created_at) }}</span>
            </div>

            <h3>Plan</h3>
            <div class="plan-picker">
              <button
                v-for="p in plans"
                :key="p.code"
                class="plan-chip"
                :class="{ active: p.code === selected.plan_code }"
                :disabled="busy"
                @click="changePlan(p.code)"
              >{{ p.name }}</button>
            </div>

            <h3>Usage this month</h3>
            <ul class="usage-list">
              <li v-for="(m, key) in selected.usage.metrics" :key="key">
                <span class="usage-key">{{ String(key).replace(/_/g, ' ') }}</span>
                <span class="usage-val" :class="{ over: m.exceeded }">
                  {{ num(m.used) }}<span class="of"> / {{ m.limit === null ? '∞' : num(m.limit) }}</span>
                </span>
              </li>
            </ul>

            <h3>People <span class="count">{{ selected.users.length }}</span></h3>
            <ul class="user-list">
              <li v-for="u in selected.users" :key="u.id">
                <div>
                  <div class="user-email">{{ u.email }}</div>
                  <div class="user-meta">
                    {{ u.role || 'no role' }}
                    <template v-if="!u.is_email_verified"> · unverified</template>
                    <template v-if="!u.is_active"> · deactivated</template>
                  </div>
                </div>
              </li>
            </ul>

            <!-- Conversation content is deliberately absent. The console
                 answers support questions about an account, not what that
                 account's customers said. -->
            <p class="privacy-note">
              Conversation content is not accessible from this console.
            </p>
          </div>

          <footer class="drawer-foot">
            <button
              v-if="selected.is_active"
              class="btn btn-secondary" :disabled="busy"
              @click="setActive(false)"
            >Suspend</button>
            <button
              v-else
              class="btn btn-primary" :disabled="busy"
              @click="setActive(true)"
            >Reactivate</button>
            <button
              class="btn btn-danger" :disabled="busy"
              @click="deleteTarget = selected; deleteConfirm = ''"
            >Delete…</button>
          </footer>
        </template>
      </aside>
    </div>

    <!-- Delete confirmation -->
    <div v-if="deleteTarget" class="modal-backdrop">
      <div class="modal">
        <h2>Delete {{ deleteTarget.name }}?</h2>
        <p class="danger-copy">
          This permanently removes every agent, conversation, document and user
          belonging to <strong>{{ deleteTarget.domain }}</strong>. It cannot be undone.
        </p>
        <label class="confirm-label" for="confirmDomain">
          Type <code>{{ deleteTarget.domain }}</code> to confirm
        </label>
        <input id="confirmDomain" v-model="deleteConfirm" class="confirm-input" autocomplete="off" />
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="deleteTarget = null" :disabled="busy">Cancel</button>
          <button class="btn btn-danger" :disabled="!deleteArmed || busy" @click="confirmDelete">
            {{ busy ? 'Deleting…' : 'Delete permanently' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Audit trail -->
    <div v-if="showAudit" class="modal-backdrop" @click.self="showAudit = false">
      <div class="modal wide">
        <header class="modal-head">
          <h2>Operator audit trail</h2>
          <button class="close" @click="showAudit = false" aria-label="Close">×</button>
        </header>
        <p class="sub">Every action taken across the tenant boundary.</p>
        <div v-if="!audit.length" class="empty">Nothing recorded yet.</div>
        <div v-else class="table-scroll audit-scroll">
          <table class="tenant-table">
            <thead>
              <tr><th>When</th><th>Operator</th><th>Action</th><th>Tenant</th><th>IP</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in audit" :key="a.id">
                <td class="muted">{{ dateTime(a.created_at) }}</td>
                <td>{{ a.actor_email }}</td>
                <td><span class="pill" :class="{ danger: a.action.endsWith('delete') }">{{ a.action }}</span></td>
                <td>{{ a.target_organization_domain || '—' }}</td>
                <td class="muted">{{ a.ip_address || '—' }}</td>
              </tr>
            </tbody>
          </table>
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
.head-actions { display: flex; gap: var(--space-sm); }

.alert-error {
  color: var(--error-color);
  background: var(--error-bg);
  border: 1px solid color-mix(in srgb, var(--error-color) 25%, transparent);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  font-size: var(--text-sm);
}

/* Stat strip */
.stat-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
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

.stat-label {
  display: block;
  font-size: var(--text-xs);
  color: var(--muted2);
  margin-top: var(--space-xs);
}

/* Table */
.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
  flex-wrap: wrap;
}

.table-head h2 {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  color: var(--text);
  margin: 0;
}

.count {
  font-size: var(--text-xs);
  color: var(--muted2);
  background: var(--o08);
  border-radius: var(--radius-pill);
  padding: 2px 8px;
  margin-left: var(--space-xs);
  font-family: var(--font-sans);
  font-weight: 500;
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

.search:focus {
  outline: none;
  border-color: var(--accent-ink);
}

/* Wide tables scroll inside their own container so the page never does */
.table-scroll { overflow-x: auto; }

.tenant-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.tenant-table th {
  text-align: left;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted2);
  font-weight: 600;
  padding: 0 var(--space-md) var(--space-sm);
  white-space: nowrap;
}

.tenant-table td {
  padding: var(--space-md);
  border-top: 1px solid var(--o06);
  color: var(--text3);
  vertical-align: middle;
}

.tenant-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.tenant-table tr.suspended { opacity: 0.6; }

.tenant-name {
  color: var(--text);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.tenant-domain { font-size: var(--text-xs); color: var(--muted2); margin-top: 2px; }
.muted { color: var(--muted2); }

.pill {
  display: inline-block;
  font-size: var(--text-xs);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  background: var(--o08);
  color: var(--text3);
  white-space: nowrap;
}

.pill.ok { background: var(--success-bg); color: var(--success-color); }
.pill.danger { background: var(--error-bg); color: var(--error-color); }

.btn-sm { padding: 5px 12px; font-size: var(--text-xs); }
.empty { color: var(--muted2); font-size: var(--text-sm); padding: var(--space-lg) 0; }

/* Drawer */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 9, 0.6);
  backdrop-filter: blur(3px);
  z-index: 900;
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: min(460px, 100%);
  background: var(--surface);
  border-left: 1px solid var(--o10);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: var(--space-lg);
  border-bottom: 1px solid var(--o08);
}

.drawer-head h2 {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  color: var(--text);
  margin: 0 0 2px;
}

.close {
  background: none;
  border: 1px solid var(--o12);
  border-radius: var(--radius-md);
  width: 30px;
  height: 30px;
  color: var(--muted2);
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
}

.close:hover { background: var(--o06); color: var(--text); }

.drawer-body {
  padding: var(--space-lg);
  overflow-y: auto;
  flex: 1;
}

.drawer-body h3 {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted2);
  margin: var(--space-xl) 0 var(--space-md);
}

.field-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-sm) 0;
  font-size: var(--text-sm);
  color: var(--text3);
}

.field-label { color: var(--muted2); }

.plan-picker { display: flex; flex-wrap: wrap; gap: var(--space-sm); }

.plan-chip {
  padding: 7px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--o12);
  background: transparent;
  color: var(--text3);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: 0.18s;
}

.plan-chip:hover:not(:disabled) { border-color: var(--accent-border); color: var(--text); }
.plan-chip.active { background: var(--accent-solid); border-color: var(--accent-solid); color: #0B0C10; font-weight: 600; }
.plan-chip:disabled { opacity: 0.5; cursor: not-allowed; }

.usage-list, .user-list { list-style: none; margin: 0; padding: 0; }

.usage-list li {
  display: flex;
  justify-content: space-between;
  padding: var(--space-sm) 0;
  border-bottom: 1px solid var(--o06);
  font-size: var(--text-sm);
}

.usage-key { color: var(--muted); text-transform: capitalize; }
.usage-val { color: var(--text); font-variant-numeric: tabular-nums; }
.usage-val.over { color: var(--error-color); font-weight: 600; }
.usage-val .of { color: var(--muted2); }

.user-list li { padding: var(--space-sm) 0; border-bottom: 1px solid var(--o06); }
.user-email { font-size: var(--text-sm); color: var(--text2); }
.user-meta { font-size: var(--text-xs); color: var(--muted2); margin-top: 2px; }

.privacy-note {
  margin-top: var(--space-xl);
  padding: var(--space-md);
  background: var(--o04);
  border: 1px solid var(--o08);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  color: var(--muted2);
}

.drawer-foot {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-lg);
  border-top: 1px solid var(--o08);
}

.drawer-foot .btn { flex: 1; }

/* Modals */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 9, 0.72);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-md);
}

.modal {
  background: var(--surface);
  border: 1px solid var(--o10);
  border-radius: var(--radius-card-lg);
  padding: var(--space-xl);
  width: 100%;
  max-width: 440px;
  max-height: 88vh;
  overflow-y: auto;
}

.modal.wide { max-width: 860px; }

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}

.modal h2 {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  color: var(--text);
  margin: 0 0 var(--space-md);
}

.modal-head h2 { margin-bottom: 0; }

.danger-copy {
  color: var(--muted);
  font-size: var(--text-sm);
  line-height: 1.6;
  margin: 0 0 var(--space-lg);
}

.danger-copy strong { color: var(--text); }

.confirm-label {
  display: block;
  font-size: var(--text-sm);
  color: var(--text3);
  margin-bottom: var(--space-sm);
}

.confirm-label code {
  background: var(--o08);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  color: var(--accent-ink);
  font-family: var(--font-mono);
}

.confirm-input {
  width: 100%;
  padding: 12px 14px;
  background: var(--o04);
  border: 1px solid var(--o12);
  border-radius: var(--radius-input);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.confirm-input:focus { outline: none; border-color: var(--error-color); }

.modal-actions {
  display: flex;
  gap: var(--space-sm);
  margin-top: var(--space-lg);
}

.modal-actions .btn { flex: 1; }

.audit-scroll { max-height: 60vh; overflow-y: auto; margin-top: var(--space-md); }

@media (max-width: 640px) {
  .drawer { width: 100%; }
  .console { padding: var(--space-md); }
}
</style>
