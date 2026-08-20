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
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import {
  listTenants, createTenant, deleteTenant, updateTenant, getPlatformPlans,
  type TenantRow, type PlatformPlan,
} from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, date, initials } from '@/utils/platformFormat'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const error = ref('')
const busy = ref(false)

const tenants = ref<TenantRow[]>([])
const total = ref(0)
const plans = ref<PlatformPlan[]>([])

// Seeded from the query string so the topbar's global search lands here with
// its term already applied.
const search = ref((route.query.q as string) || '')
const planFilter = ref('all')
const statusFilter = ref('all')

const PAGE_SIZE = 25
const page = ref(1)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    // The server filters by text and paginates; plan and status are applied
    // below over the returned page. That split is deliberate — the two
    // dropdowns are cheap to apply client-side and the alternative is a
    // round trip on every dropdown change.
    const result = await listTenants({
      q: search.value.trim() || undefined,
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    })
    tenants.value = result.tenants
    total.value = result.total
  } catch (e) {
    error.value = extractApiError(e, 'Could not load organizations')
  } finally {
    loading.value = false
  }
}

const loadPlans = async () => {
  try {
    plans.value = await getPlatformPlans()
  } catch {
    plans.value = []
  }
}

onMounted(() => { load(); loadPlans() })

// Debounced so typing does not fire a request per keystroke.
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page.value = 1; load() }, 300)
})
watch(page, load)

const visible = computed(() =>
  tenants.value.filter((t) => {
    const planOk = planFilter.value === 'all' || (t.plan_code || 'none') === planFilter.value
    const statusOk =
      statusFilter.value === 'all' ||
      (statusFilter.value === 'active' ? t.is_active : !t.is_active)
    return planOk && statusOk
  }),
)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const hasFilters = computed(
  () => !!search.value || planFilter.value !== 'all' || statusFilter.value !== 'all',
)
const clearFilters = () => {
  search.value = ''
  planFilter.value = 'all'
  statusFilter.value = 'all'
  page.value = 1
}

/** "used / allowed", as the reference reads it.
 *
 * A workspace on an unlimited plan has no denominator, so it shows the count on
 * its own — "3,842 / ∞" would imply a ceiling that does not exist. */
const messagesCell = (t: TenantRow) =>
  t.message_limit === null || t.message_limit === undefined
    ? num(t.ai_messages)
    : `${num(t.ai_messages)} / ${num(t.message_limit)}`

const planName = (code: string | null) =>
  plans.value.find((p) => p.code === code)?.name || code || 'No plan'

const openMenu = ref<string | null>(null)
const open = (t: TenantRow) => router.push(`/platform/organizations/${t.id}`)

// ── Create ─────────────────────────────────────────────────────────────────

const showCreate = ref(false)
const draft = ref({
  name: '', domain: '', admin_name: '', admin_email: '', admin_password: '',
  plan_code: '',
})
const createError = ref('')

const openCreate = () => {
  draft.value = {
    name: '', domain: '', admin_name: '', admin_email: '', admin_password: '',
    plan_code: plans.value.find((p) => p.is_default)?.code || plans.value[0]?.code || '',
  }
  createError.value = ''
  showCreate.value = true
}

const canCreate = computed(() =>
  !!draft.value.name.trim() && !!draft.value.domain.trim() &&
  !!draft.value.admin_name.trim() && !!draft.value.admin_email.trim() &&
  draft.value.admin_password.length >= 8,
)

const submitCreate = async () => {
  if (!canCreate.value) return
  busy.value = true
  createError.value = ''
  try {
    const result = await createTenant({
      name: draft.value.name.trim(),
      domain: draft.value.domain.trim(),
      admin_name: draft.value.admin_name.trim(),
      admin_email: draft.value.admin_email.trim(),
      admin_password: draft.value.admin_password,
      plan_code: draft.value.plan_code || undefined,
    })
    showCreate.value = false
    toast.success(result.message)
    // The password is never shown again — it exists only in this form, and the
    // operator has to pass it on now.
    toast.info(`Give ${draft.value.admin_email} their password — it is not stored anywhere readable.`)
    page.value = 1
    await load()
  } catch (e) {
    createError.value = extractApiError(e, 'Could not create the workspace')
  } finally {
    busy.value = false
  }
}

const suggestDomain = () => {
  if (draft.value.domain || !draft.value.name.trim()) return
  draft.value.domain = `${draft.value.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '')}.com`
}

// ── Suspend / delete ───────────────────────────────────────────────────────

const toggleActive = async (t: TenantRow) => {
  openMenu.value = null
  busy.value = true
  try {
    await updateTenant(t.id, { is_active: !t.is_active })
    toast.success(`${t.domain} ${t.is_active ? 'suspended' : 'reactivated'}`)
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not change the workspace status'))
  } finally {
    busy.value = false
  }
}

const deleteTarget = ref<TenantRow | null>(null)
const deleteConfirm = ref('')

const askDelete = (t: TenantRow) => {
  openMenu.value = null
  deleteTarget.value = t
  deleteConfirm.value = ''
}

const confirmDelete = async () => {
  if (!deleteTarget.value) return
  busy.value = true
  try {
    await deleteTenant(deleteTarget.value.id, deleteConfirm.value.trim().toLowerCase())
    toast.success(`${deleteTarget.value.domain} deleted`)
    deleteTarget.value = null
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not delete the workspace'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <PfPage
    title="Organizations"
    description="Every client workspace, its plan, and its account status."
    :loading="loading"
    :error="error"
  >
    <section class="panel table-panel" @click="openMenu = null">
      <div class="table-toolbar">
        <label class="search-box">
          <span>⌕</span>
          <input v-model="search" placeholder="Search organizations…" />
        </label>
        <div class="toolbar-actions">
          <label class="filter-select">
            <span>Plan</span>
            <select v-model="planFilter" aria-label="Filter by plan">
              <option value="all">All plans</option>
              <option v-for="p in plans" :key="p.code" :value="p.code">{{ p.name }}</option>
              <option value="none">No plan</option>
            </select>
          </label>
          <label class="filter-select">
            <span>Status</span>
            <select v-model="statusFilter" aria-label="Filter by status">
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
            </select>
          </label>
          <button v-if="hasFilters" class="clear-filter-button" @click="clearFilters">
            Clear filters
          </button>
          <button class="primary-button" :disabled="busy" @click="openCreate">
            ＋ Add organization
          </button>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Organization</th>
              <th>Email</th>
              <th>Plan</th>
              <th>Status</th>
              <th>Messages</th>
              <th>Joined</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in visible" :key="t.id" class="clickable" @click="open(t)">
              <td>
                <div class="org-cell">
                  <span class="org-avatar">{{ initials(t.name) }}</span>
                  <span>
                    <strong>{{ t.name }}</strong>
                    <small>{{ t.domain }}</small>
                  </span>
                </div>
              </td>
              <td>
                <a
                  v-if="t.owner_email"
                  class="organization-email"
                  :href="`mailto:${t.owner_email}`"
                  @click.stop
                >{{ t.owner_email }}</a>
                <span v-else class="muted-cell">—</span>
              </td>
              <td><strong class="plan-cell">{{ planName(t.plan_code) }}</strong></td>
              <td>
                <PfPill :tone="t.is_active ? 'success' : 'danger'">
                  {{ t.is_active ? 'Active' : 'Suspended' }}
                </PfPill>
              </td>
              <!-- used / allowance, as the reference reads it. An unlimited plan
                   has no denominator, so it shows the count alone rather than a
                   fraction over nothing. -->
              <td class="num">{{ messagesCell(t) }}</td>
              <td>{{ date(t.created_at) }}</td>
              <td class="row-actions-cell">
                <button
                  class="icon-button"
                  :aria-label="`Manage ${t.name}`"
                  @click.stop="openMenu = openMenu === t.id ? null : t.id"
                >•••</button>
                <div v-if="openMenu === t.id" class="row-action-menu" @click.stop>
                  <button @click="open(t)">↗ View details</button>
                  <button @click="toggleActive(t)">
                    {{ t.is_active ? '⊘ Suspend workspace' : '✓ Reactivate workspace' }}
                  </button>
                  <button class="danger" @click="askDelete(t)">⌫ Remove organization</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="!visible.length" class="empty-table-state">
          <strong>No organizations found</strong>
          <span v-if="hasFilters">Try clearing the search or filters.</span>
          <span v-else>Add your first customer workspace to get started.</span>
        </div>
      </div>

      <div class="pagination">
        <span>
          Showing {{ visible.length }} of {{ num(total) }} organizations{{
            planFilter !== 'all' || statusFilter !== 'all' ? ' · filters applied' : ''
          }}
        </span>
        <div v-if="pageCount > 1">
          <button :disabled="page === 1" @click="page--">‹</button>
          <button
            v-for="n in pageCount"
            :key="n"
            :class="{ active: n === page }"
            @click="page = n"
          >{{ n }}</button>
          <button :disabled="page === pageCount" @click="page++">›</button>
        </div>
      </div>
    </section>

    <!-- Create ------------------------------------------------------------->
    <div
      v-if="showCreate"
      class="pf-overlay right"
      @mousedown.self="showCreate = false"
    >
      <aside class="pf-drawer" role="dialog" aria-modal="true" aria-labelledby="create-org-title">
        <div class="pf-drawer-head">
          <div>
            <span>New client workspace</span>
            <h2 id="create-org-title">Add organization</h2>
          </div>
          <button class="pf-close" aria-label="Close" @click="showCreate = false">×</button>
        </div>

        <div class="pf-drawer-body">
          <div v-if="createError" class="pf-banner error">{{ createError }}</div>

          <section>
            <h3>Organization</h3>
            <div class="form-grid">
              <label>
                <span>Workspace name</span>
                <input
                  v-model="draft.name"
                  placeholder="Acme Corporation"
                  autofocus
                  @blur="suggestDomain"
                />
              </label>
              <label>
                <span>Domain</span>
                <input v-model="draft.domain" placeholder="acme.com" />
              </label>
              <label class="full">
                <span>Plan</span>
                <select v-model="draft.plan_code">
                  <option v-for="p in plans" :key="p.code" :value="p.code">
                    {{ p.name }} — {{ p.price_cents ? `$${(p.price_cents / 100).toFixed(0)}/mo` : 'Free' }}
                  </option>
                </select>
              </label>
            </div>
          </section>

          <section>
            <h3>Owner account</h3>
            <div class="form-grid">
              <label>
                <span>Full name</span>
                <input v-model="draft.admin_name" placeholder="Jane Doe" />
              </label>
              <label>
                <span>Email</span>
                <input v-model="draft.admin_email" type="email" placeholder="jane@acme.com" />
              </label>
              <label class="full">
                <span>Temporary password</span>
                <input
                  v-model="draft.admin_password"
                  type="text"
                  placeholder="At least 8 characters, mixed case and a number"
                />
                <small class="field-hint">
                  Shown as plain text so you can copy it. It is stored only as a
                  hash — nobody, including you, can read it back afterwards.
                </small>
              </label>
            </div>

            <div class="note-box accent">
              <strong>The owner can sign in immediately</strong>
              <span>
                No verification email is sent: you typed the address, so there is
                nothing to prove. They should change this password on first login.
              </span>
            </div>
          </section>
        </div>

        <div class="pf-drawer-footer">
          <button class="select-button" @click="showCreate = false">Cancel</button>
          <button class="primary-button" :disabled="!canCreate || busy" @click="submitCreate">
            {{ busy ? 'Creating…' : 'Create workspace' }}
          </button>
        </div>
      </aside>
    </div>

    <!-- Delete ------------------------------------------------------------->
    <div
      v-if="deleteTarget"
      class="pf-overlay center"
      @mousedown.self="deleteTarget = null"
    >
      <section class="pf-modal" role="dialog" aria-modal="true" aria-labelledby="delete-org-title">
        <div class="pf-modal-head">
          <div>
            <span>Irreversible</span>
            <h2 id="delete-org-title">Delete {{ deleteTarget.name }}?</h2>
            <p>{{ deleteTarget.domain }}</p>
          </div>
          <button class="pf-close" aria-label="Close" @click="deleteTarget = null">×</button>
        </div>

        <div class="pf-modal-body">
          <div class="note-box danger">
            <strong>This deletes everything the workspace owns</strong>
            <span>
              {{ num(deleteTarget.seats) }} team {{ deleteTarget.seats === 1 ? 'member' : 'members' }},
              {{ num(deleteTarget.agents) }} AI {{ deleteTarget.agents === 1 ? 'agent' : 'agents' }},
              every conversation and transcript, all knowledge sources and every
              connected channel. There is no undo and no backup taken first.
            </span>
          </div>

          <label class="field">
            <span>Type <strong>{{ deleteTarget.domain }}</strong> to confirm</span>
            <input v-model="deleteConfirm" :placeholder="deleteTarget.domain" />
          </label>
        </div>

        <div class="pf-modal-footer">
          <button class="select-button" @click="deleteTarget = null">Cancel</button>
          <button
            class="danger-button"
            :disabled="busy || deleteConfirm.trim().toLowerCase() !== deleteTarget.domain.toLowerCase()"
            @click="confirmDelete"
          >
            {{ busy ? 'Deleting…' : 'Delete workspace' }}
          </button>
        </div>
      </section>
    </div>
  </PfPage>
</template>

<style scoped>
/* A workspace with no members yet has no address to show; an em dash says that
   without pretending the column is empty by accident. */
.muted-cell { color: var(--muted); }

.plan-cell { text-transform: capitalize; }
.field span strong { color: var(--text); font-family: var(--font-mono); font-size: 11px; }
</style>
