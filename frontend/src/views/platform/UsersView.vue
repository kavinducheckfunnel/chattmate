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

Cross-tenant user search: the "a customer says they cannot sign in" screen.

Searches across workspaces on purpose. Support usually arrives with an email
address and nothing else, and asking which workspace it belongs to is the
question the operator opened this page to answer.
-->

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import {
  listPlatformUsers, listTenants, listTenantRoles, createPlatformUser,
  updatePlatformUserRole, updateTenantUser, deletePlatformUser, getOperators,
  type PlatformUser, type TenantRow, type TenantRole, type Operator,
} from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, date, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const busy = ref(false)
const rowBusy = ref<string | null>(null)

const users = ref<PlatformUser[]>([])
const total = ref(0)
const tenants = ref<TenantRow[]>([])

const search = ref('')
const orgFilter = ref('')
const statusFilter = ref('all')

const PAGE_SIZE = 25
const page = ref(1)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await listPlatformUsers({
      q: search.value.trim() || undefined,
      organization_id: orgFilter.value || undefined,
      is_active: statusFilter.value === 'all' ? undefined : statusFilter.value === 'active',
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    })
    users.value = result.users
    total.value = result.total
  } catch (e) {
    error.value = extractApiError(e, 'Could not load users')
  } finally {
    loading.value = false
  }
}

// Who else can reach this console. Read-only here on purpose: granting and
// revoking stay in scripts/grant_platform_admin.py, which needs shell access —
// so an operator whose session is stolen cannot quietly add a second account
// for later.
const operators = ref<Operator[]>([])

onMounted(async () => {
  await load()
  try {
    // A high limit rather than pagination: this feeds a dropdown, and a
    // half-populated workspace picker is worse than a long one.
    tenants.value = (await listTenants({ limit: 200 })).tenants
  } catch {
    tenants.value = []
  }
  try {
    operators.value = await getOperators()
  } catch {
    operators.value = []
  }
})

let timer: ReturnType<typeof setTimeout> | undefined
watch(search, () => {
  clearTimeout(timer)
  timer = setTimeout(() => { page.value = 1; load() }, 300)
})
watch([orgFilter, statusFilter], () => { page.value = 1; load() })
watch(page, load)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const hasFilters = computed(() => !!search.value || !!orgFilter.value || statusFilter.value !== 'all')
const clearFilters = () => {
  search.value = ''
  orgFilter.value = ''
  statusFilter.value = 'all'
  page.value = 1
}

// Roles are per-workspace, so the picker has to be fetched for whichever
// workspace a given row belongs to. Cached because a list of 25 users from
// three workspaces would otherwise refetch the same three role sets.
const roleCache = ref<Record<string, TenantRole[]>>({})
const rolesFor = async (organizationId: string): Promise<TenantRole[]> => {
  if (roleCache.value[organizationId]) return roleCache.value[organizationId]
  try {
    const list = await listTenantRoles(organizationId)
    roleCache.value[organizationId] = list
    return list
  } catch {
    return []
  }
}

const roleMenu = ref<string | null>(null)
const roleOptions = ref<TenantRole[]>([])

const openRoleMenu = async (u: PlatformUser) => {
  if (!u.organization_id) return
  if (roleMenu.value === u.id) { roleMenu.value = null; return }
  roleOptions.value = await rolesFor(u.organization_id)
  roleMenu.value = u.id
}

const setRole = async (u: PlatformUser, roleId: string) => {
  roleMenu.value = null
  rowBusy.value = u.id
  try {
    await updatePlatformUserRole(u.id, roleId)
    toast.success(`${u.email} role updated`)
    toast.info('Their existing sessions were signed out so the new permissions take effect.')
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not change the role'))
  } finally {
    rowBusy.value = null
  }
}

const toggleActive = async (u: PlatformUser) => {
  rowBusy.value = u.id
  try {
    await updateTenantUser(u.id, { is_active: !u.is_active })
    toast.success(`${u.email} ${u.is_active ? 'deactivated' : 'reactivated'}`)
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not update the user'))
  } finally {
    rowBusy.value = null
  }
}

// ── Password reset ─────────────────────────────────────────────────────────

const resetTarget = ref<PlatformUser | null>(null)
const newPassword = ref('')

const submitReset = async () => {
  if (!resetTarget.value) return
  busy.value = true
  try {
    await updateTenantUser(resetTarget.value.id, { new_password: newPassword.value })
    toast.success(`Password set for ${resetTarget.value.email}`)
    toast.info('All their existing sessions were signed out.')
    resetTarget.value = null
    newPassword.value = ''
  } catch (e) {
    toast.error(extractApiError(e, 'Could not set the password'))
  } finally {
    busy.value = false
  }
}

// ── Create ─────────────────────────────────────────────────────────────────

const showCreate = ref(false)
const createError = ref('')
const draft = ref({ organization_id: '', full_name: '', email: '', password: '', role_id: '' })
const draftRoles = ref<TenantRole[]>([])

const openCreate = () => {
  draft.value = { organization_id: '', full_name: '', email: '', password: '', role_id: '' }
  draftRoles.value = []
  createError.value = ''
  showCreate.value = true
}

watch(() => draft.value.organization_id, async (id) => {
  draft.value.role_id = ''
  draftRoles.value = id ? await rolesFor(id) : []
  // Preselect the workspace's default role so the common case is one less choice.
  const fallback = draftRoles.value.find((r) => r.is_default) || draftRoles.value[0]
  if (fallback) draft.value.role_id = fallback.id
})

const canCreate = computed(() =>
  !!draft.value.organization_id && !!draft.value.full_name.trim() &&
  !!draft.value.email.trim() && draft.value.password.length >= 8,
)

const submitCreate = async () => {
  if (!canCreate.value) return
  busy.value = true
  createError.value = ''
  try {
    await createPlatformUser({
      organization_id: draft.value.organization_id,
      full_name: draft.value.full_name.trim(),
      email: draft.value.email.trim(),
      password: draft.value.password,
      role_id: draft.value.role_id || undefined,
    })
    toast.success('User created')
    toast.info(`Give ${draft.value.email} their password — it is not stored anywhere readable.`)
    showCreate.value = false
    page.value = 1
    await load()
  } catch (e) {
    createError.value = extractApiError(e, 'Could not create the user')
  } finally {
    busy.value = false
  }
}

// ── Remove ─────────────────────────────────────────────────────────────────

const removeTarget = ref<PlatformUser | null>(null)
const removeConfirm = ref('')

const submitRemove = async () => {
  if (!removeTarget.value) return
  busy.value = true
  try {
    await deletePlatformUser(removeTarget.value.id, removeConfirm.value.trim())
    toast.success(`${removeTarget.value.email} removed`)
    removeTarget.value = null
    removeConfirm.value = ''
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not remove the user'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <PfPage
    title="Users"
    description="Search and manage people across every customer workspace."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="primary-button" @click="openCreate">＋ Add user</button>
    </template>

    <section class="panel table-panel" @click="roleMenu = null">
      <div class="table-toolbar">
        <label class="search-box">
          <span>⌕</span>
          <input v-model="search" placeholder="Search name or email…" />
        </label>
        <div class="toolbar-actions">
          <label class="filter-select">
            <span>Workspace</span>
            <select v-model="orgFilter" aria-label="Filter by workspace">
              <option value="">All workspaces</option>
              <option v-for="t in tenants" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </label>
          <label class="filter-select">
            <span>Status</span>
            <select v-model="statusFilter" aria-label="Filter by status">
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="inactive">Deactivated</option>
            </select>
          </label>
          <button v-if="hasFilters" class="clear-filter-button" @click="clearFilters">
            Clear filters
          </button>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Workspace</th>
              <th>Role</th>
              <th>Status</th>
              <th>Joined</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>
                <div class="org-cell">
                  <span class="user-avatar">{{ initials(u.full_name || u.email) }}</span>
                  <span>
                    <strong>{{ u.full_name || '—' }}</strong>
                    <small>{{ u.email }}</small>
                  </span>
                </div>
              </td>
              <td>
                <RouterLink
                  v-if="u.organization_id"
                  :to="`/platform/organizations/${u.organization_id}`"
                  class="org-link"
                  @click.stop
                >{{ u.organization_name || u.organization_domain }}</RouterLink>
                <span v-else class="feature-no">No workspace</span>
              </td>
              <td class="role-cell">
                <PfPill v-if="u.is_platform_admin" tone="accent">Operator</PfPill>
                <button
                  v-else-if="u.organization_id"
                  class="role-trigger"
                  :disabled="rowBusy === u.id"
                  @click.stop="openRoleMenu(u)"
                >{{ u.role || 'No role' }} ⌄</button>
                <span v-else class="feature-no">—</span>

                <div v-if="roleMenu === u.id" class="row-action-menu role-menu" @click.stop>
                  <button
                    v-for="r in roleOptions"
                    :key="r.id"
                    @click="setRole(u, r.id)"
                  >{{ r.name }}{{ r.name === u.role ? ' ✓' : '' }}</button>
                  <span v-if="!roleOptions.length" class="menu-empty">No roles found</span>
                </div>
              </td>
              <td>
                <PfPill :tone="u.is_active ? 'success' : 'danger'">
                  {{ u.is_active ? 'Active' : 'Deactivated' }}
                </PfPill>
                <PfPill v-if="!u.is_email_verified" tone="warning">Unverified</PfPill>
              </td>
              <td>{{ date(u.created_at) }}</td>
              <td class="row-actions">
                <template v-if="u.is_platform_admin">
                  <span class="operator-note">Managed on the server</span>
                </template>
                <template v-else>
                  <button class="text-button" :disabled="rowBusy === u.id" @click="toggleActive(u)">
                    {{ u.is_active ? 'Deactivate' : 'Reactivate' }}
                  </button>
                  <button class="text-button" @click="resetTarget = u; newPassword = ''">
                    Set password
                  </button>
                  <button class="text-button danger-text" @click="removeTarget = u; removeConfirm = ''">
                    Remove
                  </button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="!users.length" class="empty-table-state">
          <strong>No users found</strong>
          <span v-if="hasFilters">Try clearing the search or filters.</span>
          <span v-else>Users appear here as workspaces are created.</span>
        </div>
      </div>

      <div class="pagination">
        <span>
          Showing {{ users.length ? (page - 1) * PAGE_SIZE + 1 : 0 }}–{{
            Math.min(page * PAGE_SIZE, total)
          }} of {{ num(total) }} users
        </span>
        <div v-if="pageCount > 1">
          <button :disabled="page === 1" @click="page--">‹</button>
          <button v-for="n in pageCount" :key="n" :class="{ active: n === page }" @click="page = n">
            {{ n }}
          </button>
          <button :disabled="page === pageCount" @click="page++">›</button>
        </div>
      </div>
    </section>

    <!-- Operators ----------------------------------------------------------->
    <section v-if="operators.length" class="panel operators-panel">
      <div class="panel-heading">
        <div>
          <h2>Platform operators</h2>
          <p>Accounts that can reach this console and every workspace in it.</p>
        </div>
        <PfPill tone="accent">{{ operators.length }}</PfPill>
      </div>

      <div class="operator-list">
        <div v-for="o in operators" :key="o.id" class="operator-row">
          <span class="user-avatar">{{ initials(o.full_name || o.email) }}</span>
          <span class="grow">
            <strong>{{ o.full_name || o.email }}</strong>
            <small>{{ o.email }}</small>
          </span>
          <PfPill :tone="o.tenant ? 'warning' : 'neutral'">
            {{ o.tenant ? `also in ${o.tenant}` : 'Standalone' }}
          </PfPill>
          <PfPill :tone="o.is_active ? 'success' : 'danger'">
            {{ o.is_active ? 'Active' : 'Disabled' }}
          </PfPill>
          <span class="joined">{{ date(o.created_at) }}</span>
        </div>
      </div>

      <div class="note-box">
        <strong>Granting and revoking happens on the server</strong>
        <span>
          Run <code>scripts/grant_platform_admin.py</code> over SSH. It is
          deliberately not exposed here: if this console could create operators,
          a single stolen session would be enough to mint a permanent second
          account. An operator who also belongs to a workspace is worth
          reviewing — their customer account and their staff account are then
          the same login.
        </span>
      </div>
    </section>

    <!-- Create ------------------------------------------------------------->
    <div v-if="showCreate" class="pf-overlay right" @mousedown.self="showCreate = false">
      <aside class="pf-drawer" role="dialog" aria-modal="true" aria-labelledby="add-user-title">
        <div class="pf-drawer-head">
          <div>
            <span>New workspace member</span>
            <h2 id="add-user-title">Add user</h2>
          </div>
          <button class="pf-close" aria-label="Close" @click="showCreate = false">×</button>
        </div>

        <div class="pf-drawer-body">
          <div v-if="createError" class="pf-banner error">{{ createError }}</div>

          <section>
            <h3>Workspace</h3>
            <div class="form-grid">
              <label class="full">
                <span>Which customer</span>
                <select v-model="draft.organization_id">
                  <option value="" disabled>Choose a workspace…</option>
                  <option v-for="t in tenants" :key="t.id" :value="t.id">
                    {{ t.name }} — {{ t.domain }}
                  </option>
                </select>
              </label>
              <label class="full">
                <span>Role</span>
                <select v-model="draft.role_id" :disabled="!draftRoles.length">
                  <option v-for="r in draftRoles" :key="r.id" :value="r.id">
                    {{ r.name }}{{ r.is_default ? ' (default)' : '' }}
                  </option>
                </select>
                <small v-if="!draft.organization_id" class="field-hint">
                  Roles belong to a workspace, so pick one above first.
                </small>
              </label>
            </div>
          </section>

          <section>
            <h3>Person</h3>
            <div class="form-grid">
              <label>
                <span>Full name</span>
                <input v-model="draft.full_name" placeholder="Jane Doe" />
              </label>
              <label>
                <span>Email</span>
                <input v-model="draft.email" type="email" placeholder="jane@acme.com" />
              </label>
              <label class="full">
                <span>Temporary password</span>
                <input
                  v-model="draft.password"
                  type="text"
                  placeholder="At least 8 characters, mixed case and a number"
                />
                <small class="field-hint">
                  Shown as text so you can copy it. Stored only as a hash — it
                  cannot be read back afterwards.
                </small>
              </label>
            </div>
          </section>
        </div>

        <div class="pf-drawer-footer">
          <button class="select-button" @click="showCreate = false">Cancel</button>
          <button class="primary-button" :disabled="!canCreate || busy" @click="submitCreate">
            {{ busy ? 'Creating…' : 'Add user' }}
          </button>
        </div>
      </aside>
    </div>

    <!-- Password ----------------------------------------------------------->
    <div v-if="resetTarget" class="pf-overlay center" @mousedown.self="resetTarget = null">
      <section class="pf-modal" role="dialog" aria-modal="true">
        <div class="pf-modal-head">
          <div>
            <span>Account recovery</span>
            <h2>Set a new password</h2>
            <p>{{ resetTarget.email }} · {{ resetTarget.organization_domain }}</p>
          </div>
          <button class="pf-close" aria-label="Close" @click="resetTarget = null">×</button>
        </div>
        <div class="pf-modal-body">
          <label class="field">
            <span>New password</span>
            <input v-model="newPassword" type="text" placeholder="At least 8 characters, mixed case and a number" />
            <small class="field-hint">Shown as text so you can read it out.</small>
          </label>
          <div class="note-box">
            <strong>This is an account takeover, and is logged as one</strong>
            <span>
              The audit entry names you, the workspace and this user. The password
              itself is never written to the log, and their existing sessions end
              the moment it is saved.
            </span>
          </div>
        </div>
        <div class="pf-modal-footer">
          <button class="select-button" @click="resetTarget = null">Cancel</button>
          <button class="primary-button" :disabled="busy || newPassword.length < 8" @click="submitReset">
            {{ busy ? 'Saving…' : 'Set password' }}
          </button>
        </div>
      </section>
    </div>

    <!-- Remove ------------------------------------------------------------->
    <div v-if="removeTarget" class="pf-overlay center" @mousedown.self="removeTarget = null">
      <section class="pf-modal" role="dialog" aria-modal="true">
        <div class="pf-modal-head">
          <div>
            <span>Irreversible</span>
            <h2>Remove {{ removeTarget.full_name || removeTarget.email }}?</h2>
            <p>{{ removeTarget.organization_domain }}</p>
          </div>
          <button class="pf-close" aria-label="Close" @click="removeTarget = null">×</button>
        </div>
        <div class="pf-modal-body">
          <div class="note-box danger">
            <strong>They lose access immediately</strong>
            <span>
              Their conversations stay with the workspace, but the account and its
              sessions are gone. The server refuses if they are the workspace's
              last remaining member.
            </span>
          </div>
          <label class="field">
            <span>Type <strong>{{ removeTarget.email }}</strong> to confirm</span>
            <input v-model="removeConfirm" :placeholder="removeTarget.email" />
          </label>
        </div>
        <div class="pf-modal-footer">
          <button class="select-button" @click="removeTarget = null">Cancel</button>
          <button
            class="danger-button"
            :disabled="busy || removeConfirm.trim().toLowerCase() !== removeTarget.email.toLowerCase()"
            @click="submitRemove"
          >{{ busy ? 'Removing…' : 'Remove user' }}</button>
        </div>
      </section>
    </div>
  </PfPage>
</template>

<style scoped>
.role-cell { position: relative; }

.role-trigger {
  border: 1px solid var(--o12);
  background: var(--o04);
  color: var(--text2);
  border-radius: var(--radius-sm);
  padding: 4px 9px;
  font-size: 11px;
  cursor: pointer;
}
.role-trigger:hover:not(:disabled) { border-color: var(--o20); }
.role-trigger:disabled { opacity: .5; cursor: not-allowed; }

.role-menu { right: auto; left: 12px; top: 40px; min-width: 150px; }
.menu-empty { padding: 9px 10px; font-size: 11px; color: var(--muted2); }

.row-actions { display: flex; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }
.danger-text { color: var(--c-danger); }
.operator-note { font-size: 10px; color: var(--muted2); }

.org-link { color: var(--text3); text-decoration: none; }
.org-link:hover { color: var(--accent-ink); text-decoration: underline; }

.field span strong { color: var(--text); font-family: var(--font-mono); font-size: 11px; }

.operators-panel { margin-top: 16px; }

.operator-list { display: flex; flex-direction: column; margin: 14px 0; }

.operator-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 0;
  border-top: 1px solid var(--o06);
}
.operator-row:first-child { border-top: 0; }
.operator-row .grow { display: flex; flex-direction: column; min-width: 0; }
.operator-row strong { font-size: var(--text-xs); }
.operator-row small { font-size: 10px; color: var(--muted2); margin-top: 2px; }

.joined { font-size: 10px; color: var(--muted2); min-width: 88px; text-align: right; }

.operators-panel code {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--o05);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--text3);
}

@media (max-width: 640px) {
  .operator-row { flex-wrap: wrap; }
  .joined { text-align: left; min-width: 0; }
}
</style>
