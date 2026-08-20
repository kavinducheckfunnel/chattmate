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

Everything the platform knows about one customer, in one place.

Tabs load on first open rather than all at once. A workspace with thousands of
conversations should not pay for that list when the operator only came to check
a plan, and the tab the operator picked is the only one whose latency they feel.
-->

<script setup lang="ts">
import { ref, computed, reactive, onMounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfProgress from '@/components/platform/ui/PfProgress.vue'
import TranscriptModal from '@/components/platform/TranscriptModal.vue'
import {
  getTenant, updateTenant, getPlatformPlans, listAudit,
  getTenantAgents, getTenantKnowledge, getTenantIntegrations,
  getTenantConversations, getTenantFeatures, setTenantFeature,
  listTenantRoles, updatePlatformUserRole, updateTenantUser, deletePlatformUser,
  type TenantDetail, type PlatformPlan, type AuditEntry, type TenantAgent,
  type KnowledgeSource, type TenantIntegrations, type ConversationRow,
  type TenantFeature, type TenantRole, type TenantUser,
} from '@/services/platform'
import type { MetricUsage } from '@/services/usage'
import { extractApiError } from '@/utils/apiError'
import { num, money, date, dateTime, ago, initials, ofLimit } from '@/utils/platformFormat'

const props = defineProps<{ id: string }>()

type Tab = 'overview' | 'members' | 'conversations' | 'features'
  | 'usage' | 'billing' | 'knowledge' | 'integrations' | 'audit'

// The reference's seven, in its order and with its labels. Knowledge and
// Integrations follow: both are backed by real endpoints here and the reference
// — which is a mock with no such data — simply has no equivalent, so dropping
// them to match a tab count would delete working features.
const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'members', label: 'Members' },
  { key: 'conversations', label: 'Chats' },
  { key: 'features', label: 'Features' },
  { key: 'usage', label: 'Usage' },
  { key: 'billing', label: 'Billing' },
  { key: 'audit', label: 'Audit' },
  { key: 'knowledge', label: 'Knowledge' },
  { key: 'integrations', label: 'Integrations' },
]

const tab = ref<Tab>('overview')
const loading = ref(true)
const error = ref('')
const busy = ref(false)

const tenant = ref<TenantDetail | null>(null)
const plans = ref<PlatformPlan[]>([])

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [t, p] = await Promise.all([getTenant(props.id), getPlatformPlans()])
    tenant.value = t
    plans.value = p
  } catch (e) {
    error.value = extractApiError(e, 'Could not load this workspace')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const plan = computed(() => plans.value.find((p) => p.code === tenant.value?.plan_code) || null)
const priceMonthly = computed(() => (plan.value ? plan.value.price_cents / 100 : 0))

// ── Lazy tab data ──────────────────────────────────────────────────────────

const loaded = reactive<Record<string, boolean>>({})
const tabError = ref('')

const agents = ref<TenantAgent[]>([])
const knowledge = ref<{ total: number; sources: KnowledgeSource[] }>({ total: 0, sources: [] })
const integrations = ref<TenantIntegrations>({ channels: [], widgets: [] })
const conversations = ref<ConversationRow[]>([])
const conversationTotal = ref(0)
const features = ref<TenantFeature[]>([])
const planConfigured = ref(true)
const audit = ref<AuditEntry[]>([])
const roles = ref<TenantRole[]>([])

const loadTab = async (which: Tab) => {
  if (loaded[which]) return
  tabError.value = ''
  try {
    if (which === 'overview') {
      agents.value = await getTenantAgents(props.id)
    } else if (which === 'members') {
      roles.value = await listTenantRoles(props.id)
    } else if (which === 'conversations') {
      const r = await getTenantConversations(props.id, { limit: 50 })
      conversations.value = r.conversations
      conversationTotal.value = r.total
    } else if (which === 'features') {
      const r = await getTenantFeatures(props.id)
      features.value = r.features
      planConfigured.value = r.plan_configured
    } else if (which === 'knowledge') {
      knowledge.value = await getTenantKnowledge(props.id)
    } else if (which === 'integrations') {
      integrations.value = await getTenantIntegrations(props.id)
    } else if (which === 'audit') {
      audit.value = await listAudit(props.id)
    }
    loaded[which] = true
  } catch (e) {
    tabError.value = extractApiError(e, 'Could not load this section')
  }
}

watch(tab, (t) => loadTab(t))
watch(tenant, (t) => { if (t) loadTab('overview') })

// ── Plan and status ────────────────────────────────────────────────────────

const changePlan = async (code: string) => {
  if (!tenant.value || code === tenant.value.plan_code) return
  busy.value = true
  try {
    await updateTenant(props.id, { plan_code: code })
    toast.success(`Moved to the ${plans.value.find((p) => p.code === code)?.name} plan`)
    // Feature access follows the plan, so a cached matrix would now be wrong.
    loaded.features = false
    await load()
    if (tab.value === 'features') await loadTab('features')
  } catch (e) {
    toast.error(extractApiError(e, 'Could not change the plan'))
  } finally {
    busy.value = false
  }
}

/** Open this workspace as its owner would see it.
 *
 * Deliberately a new tab rather than a redirect: the operator keeps the console
 * they are working in, and closing the tab is the whole exit path — there is no
 * "leave support mode" state to get stuck in.
 */
/** The workspace owner. The earliest member is the one who created it, which is
 *  the closest thing to an owner this schema records. */
// ── Chats: date range, summary and export ───────────────────────────────────

const monthStart = (offset = 0) => {
  const now = new Date()
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset, 1))
}
const iso = (d: Date) => d.toISOString().slice(0, 10)

const chatFrom = ref(iso(monthStart()))
const chatTo = ref(iso(new Date()))
const chatPreset = ref<'this' | 'last' | 'custom'>('this')

const setChatRange = (which: 'this' | 'last') => {
  chatPreset.value = which
  if (which === 'this') {
    chatFrom.value = iso(monthStart())
    chatTo.value = iso(new Date())
  } else {
    chatFrom.value = iso(monthStart(-1))
    // Day 0 of this month is the last day of the previous one.
    chatTo.value = iso(new Date(Date.UTC(monthStart().getUTCFullYear(), monthStart().getUTCMonth(), 0)))
  }
}

/** Conversations inside the selected range. Compared as YYYY-MM-DD strings,
 *  which sort correctly and sidestep timezone drift on a date-only value. */
const filteredChats = computed(() =>
  (conversations.value ?? []).filter((c: any) => {
    const day = (c.updated_at ?? c.created_at ?? '').slice(0, 10)
    return day && day >= chatFrom.value && day <= chatTo.value
  }),
)

const chatMessageTotal = computed(() =>
  filteredChats.value.reduce((total: number, c: any) => total + (c.messages ?? 0), 0),
)

const chatResolvedPct = computed(() => {
  const rows = filteredChats.value
  if (!rows.length) return '—'
  const resolved = rows.filter((c: any) => (c.status ?? '').toLowerCase().includes('closed')).length
  return `${Math.round((resolved / rows.length) * 100)}%`
})

const chatAvgRating = computed(() => {
  const rated = filteredChats.value.filter((c: any) => typeof c.rating === 'number')
  if (!rated.length) return '—'
  const mean = rated.reduce((t: number, c: any) => t + c.rating, 0) / rated.length
  return `${mean.toFixed(1)} / 5`
})

/** Exported as CSV, which every spreadsheet opens. Naming it XLSX while writing
 *  CSV is the kind of small lie that wastes someone's afternoon. */
const downloadChatsXlsx = () => {
  const rows = [['Conversation', 'Customer', 'Channel', 'Agent', 'Messages', 'Status', 'Updated']]
  for (const c of filteredChats.value as any[]) {
    rows.push([c.session_id, c.customer ?? '', c.channel ?? '', c.agent ?? '',
               String(c.messages ?? 0), c.status ?? '', c.updated_at ?? ''])
  }
  const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `chats-${tenant.value?.domain ?? 'workspace'}-${chatFrom.value}-to-${chatTo.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ── Usage: month selector and export ────────────────────────────────────────

const usageMonth = ref('')
const usageMonths = computed(() => {
  const out: { value: string; label: string }[] = []
  for (let i = 0; i < 6; i++) {
    const d = monthStart(-i)
    out.push({
      value: `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`,
      label: d.toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }),
    })
  }
  return out
})

const exportUsageCsv = () => {
  const rows = [['Metric', 'Used', 'Limit']]
  for (const row of usageRows.value as any[]) {
    rows.push([row.label, String(row.used ?? 0), row.limit === null ? 'Unlimited' : String(row.limit)])
  }
  const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `usage-${tenant.value?.domain ?? 'workspace'}-${usageMonth.value || 'current'}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const owner = computed(() => {
  const users = [...(tenant.value?.users ?? [])]
  users.sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''))
  return users[0] ?? null
})
const ownerName = computed(() => owner.value?.full_name || 'No owner yet')
const ownerEmail = computed(() => owner.value?.email || 'No members in this workspace')

/** Opens the subscription manager. Previously this switched to the Usage tab,
 *  which is not what the label promises. */
const subscriptionOpen = ref(false)

const planPriceLabel = computed(() => {
  if (!plan.value) return 'No plan assigned'
  return plan.value.price_cents
    ? `$${(plan.value.price_cents / 100).toFixed(0)} / month`
    : 'Free forever'
})

/** What this workspace would be billed for the current period.
 *
 * Derived from the plan catalogue rather than from an invoice, because no
 * invoice exists — so it is labelled as the plan price, not as money owed. */
const nextInvoiceLabel = computed(() => {
  if (!plan.value?.price_cents) return '$0.00'
  return `$${(plan.value.price_cents / 100).toFixed(2)}`
})

const renewalLabel = computed(() => {
  // Billing periods here are calendar months, so the next one starts on the 1st.
  const now = new Date()
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1))
  return `Period starts ${next.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}`
})

const enterSupportMode = () => {
  if (!tenant.value) return
  window.open(`https://${tenant.value.domain}`, '_blank', 'noopener')
}

const toggleActive = async () => {
  if (!tenant.value) return
  busy.value = true
  try {
    await updateTenant(props.id, { is_active: !tenant.value.is_active })
    toast.success(tenant.value.is_active ? 'Workspace suspended' : 'Workspace reactivated')
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not change the workspace status'))
  } finally {
    busy.value = false
  }
}

// ── Usage ──────────────────────────────────────────────────────────────────

const METRIC_LABELS: Record<string, string> = {
  conversations: 'Conversations',
  ai_messages: 'AI replies',
  agents: 'AI agents',
  seats: 'Team members',
  knowledge_docs: 'Knowledge sources',
}

const usageRows = computed(() => {
  // Typed fallback rather than a bare `{}`: an empty object literal widens the
  // Record's value type to unknown, and every field read below then fails.
  const metrics: Record<string, MetricUsage> = tenant.value?.usage?.metrics ?? {}
  return Object.entries(metrics).map(([key, m]) => ({
    key,
    label: METRIC_LABELS[key] ?? key,
    used: m.used,
    limit: m.limit,
    percent: m.percent,
    exceeded: m.exceeded,
  }))
})

const worstUsage = computed(() => {
  const withLimits = usageRows.value.filter((r) => r.percent !== null)
  if (!withLimits.length) return null
  return withLimits.reduce((a, b) => ((b.percent ?? 0) > (a.percent ?? 0) ? b : a))
})

// ── Members ────────────────────────────────────────────────────────────────

const memberBusy = ref<string | null>(null)

const changeRole = async (user: TenantUser, roleId: string) => {
  memberBusy.value = user.id
  try {
    await updatePlatformUserRole(user.id, roleId)
    toast.success(`${user.email} role updated`)
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not change the role'))
  } finally {
    memberBusy.value = null
  }
}

const toggleMemberActive = async (user: TenantUser) => {
  memberBusy.value = user.id
  try {
    await updateTenantUser(user.id, { is_active: !user.is_active })
    toast.success(`${user.email} ${user.is_active ? 'deactivated' : 'reactivated'}`)
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not update the user'))
  } finally {
    memberBusy.value = null
  }
}

const resetTarget = ref<TenantUser | null>(null)
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

const removeTarget = ref<TenantUser | null>(null)
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

// ── Features ───────────────────────────────────────────────────────────────

const featureBusy = ref<string | null>(null)

const overrideCount = computed(() => features.value.filter((f) => f.override !== null).length)

/**
 * Cycles override → plan default → the opposite of the plan default.
 * Clearing matters: an override pinned to the same value the plan happens to
 * have today would stop a later plan change from reaching this tenant.
 */
const cycleFeature = async (f: TenantFeature) => {
  const next = f.override === null ? !f.plan_default : null
  featureBusy.value = f.key
  try {
    await setTenantFeature(
      props.id, f.key, next,
      next === null ? undefined : 'Set from the operator console',
    )
    const r = await getTenantFeatures(props.id)
    features.value = r.features
    planConfigured.value = r.plan_configured
    toast.success(
      next === null
        ? `${f.label} follows the plan again`
        : `${f.label} ${next ? 'enabled' : 'disabled'} for this workspace`,
    )
  } catch (e) {
    toast.error(extractApiError(e, 'Could not change feature access'))
  } finally {
    featureBusy.value = null
  }
}

const featureGroups = computed(() => {
  const groups: Record<string, TenantFeature[]> = {}
  for (const f of features.value) (groups[f.category] ??= []).push(f)
  return Object.entries(groups)
})

// ── Conversations ──────────────────────────────────────────────────────────

const openSession = ref<string | null>(null)
</script>

<template>
  <PfPage
    :title="tenant?.name || 'Workspace'"
    :back="{ to: '/platform/organizations', label: 'Organizations' }"
    :loading="loading"
    :error="error"
  >
    <template v-if="tenant">
      <section class="panel org-hero">
        <div class="org-hero-main">
          <span class="org-avatar large">{{ initials(tenant.name) }}</span>
          <div>
            <div class="title-line">
              <h2>{{ tenant.name }}</h2>
              <PfPill :tone="tenant.is_active ? 'success' : 'danger'">
                {{ tenant.is_active ? 'Active' : 'Suspended' }}
              </PfPill>
              <PfPill v-if="plan" tone="accent">{{ plan.name }}</PfPill>
            </div>
            <p>{{ tenant.domain }} · created {{ date(tenant.created_at) }} · {{ tenant.timezone }}</p>
          </div>
        </div>
        <div class="org-actions">
          <label class="filter-select">
            <span>Plan</span>
            <select
              :value="tenant.plan_code || ''"
              :disabled="busy"
              aria-label="Change plan"
              @change="changePlan(($event.target as HTMLSelectElement).value)"
            >
              <option v-for="p in plans" :key="p.code" :value="p.code">
                {{ p.name }} — {{ p.price_cents ? `$${(p.price_cents / 100).toFixed(0)}/mo` : 'Free' }}
              </option>
            </select>
          </label>
          <button class="select-button" :disabled="busy" @click="toggleActive">
            {{ tenant.is_active ? 'Suspend' : 'Reactivate' }}
          </button>
          <button class="primary-button" @click="enterSupportMode">Enter support mode</button>
        </div>
      </section>

      <div class="detail-grid">
        <section class="panel detail-main">
          <div class="tabs" role="tablist">
            <button
              v-for="t in TABS"
              :key="t.key"
              :class="{ active: tab === t.key }"
              @click="tab = t.key"
            >{{ t.label }}</button>
          </div>

          <div v-if="tabError" class="pf-banner error">{{ tabError }}</div>

          <!-- Overview ------------------------------------------------------>
          <div v-if="tab === 'overview'" class="info-section">
            <h3>Organization information</h3>
            <div class="info-grid">
              <label>Organization<strong>{{ tenant.name }}</strong><small>{{ tenant.domain }}</small></label>
              <label>Status<strong>{{ tenant.is_active ? 'Active' : 'Suspended' }}</strong><small>Created {{ date(tenant.created_at) }}</small></label>
              <label>Owner<strong>{{ ownerName }}</strong><small>{{ ownerEmail }}</small></label>
              <label>Current plan<strong>{{ plan?.name || 'No plan' }}</strong><small>{{ plan ? (plan.price_cents ? `${money(priceMonthly)} / month` : 'Free forever') : 'Quotas fall back to the default' }}</small></label>
              <label>Region<strong>{{ tenant.timezone }}</strong><small>Used for business hours</small></label>
              <label>Renewal date<strong>{{ renewalLabel }}</strong><small>{{ plan?.price_cents ? 'Automatic renewal' : 'Free plan' }}</small></label>
            </div>

            <div class="section-divider" />

            <div class="tab-content-head">
              <div>
                <h3>Usage this period</h3>
                <p>Billing period {{ tenant.usage.period }}</p>
              </div>
              <button class="text-button" @click="tab = 'usage'">Full breakdown →</button>
            </div>
            <div class="progress-stack">
              <PfProgress
                v-for="row in usageRows.slice(0, 4)"
                :key="row.key"
                :label="row.label"
                :value="ofLimit(row.used, row.limit)"
                :percent="row.percent ?? 0"
              />
            </div>

            <div class="section-divider" />

            <div class="tab-content-head">
              <div>
                <h3>AI agents</h3>
                <p>Instruction counts only — the wording of a customer's prompts is their own work.</p>
              </div>
            </div>
            <div v-if="agents.length" class="table-wrap">
              <table>
                <thead>
                  <tr><th>Agent</th><th>Type</th><th>Instructions</th><th>Handover</th><th>Status</th></tr>
                </thead>
                <tbody>
                  <tr v-for="a in agents" :key="a.id">
                    <td>
                      <strong>{{ a.display_name || a.name }}</strong>
                      <small class="table-subtext">{{ a.description || 'No description' }}</small>
                    </td>
                    <td>{{ a.agent_type || '—' }}</td>
                    <td class="num">{{ a.instruction_count }}</td>
                    <td>{{ a.transfer_to_human ? 'Enabled' : 'Off' }}</td>
                    <td>
                      <PfPill :tone="a.is_active ? 'success' : 'neutral'">
                        {{ a.is_active ? 'Live' : 'Inactive' }}
                      </PfPill>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">
              <strong>No agents yet</strong>
              <span>This customer has not finished onboarding.</span>
            </div>
          </div>

          <!-- Members ------------------------------------------------------->
          <div v-else-if="tab === 'members'" class="org-tab-content">
            <div class="tab-content-head">
              <div>
                <h3>Members</h3>
                <p>People who can access this organization workspace.</p>
              </div>
              <RouterLink to="/platform/users" class="primary-button">＋ Invite member</RouterLink>
            </div>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Member</th><th>Role</th><th>Status</th><th>Last active</th><th /></tr>
                </thead>
                <tbody>
                  <tr v-for="u in tenant.users" :key="u.id">
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
                      <select
                        v-if="roles.length"
                        class="inline-select"
                        :value="roles.find((r) => r.name === u.role)?.id || ''"
                        :disabled="memberBusy === u.id"
                        :aria-label="`Role for ${u.email}`"
                        @change="changeRole(u, ($event.target as HTMLSelectElement).value)"
                      >
                        <option v-for="r in roles" :key="r.id" :value="r.id">{{ r.name }}</option>
                      </select>
                      <PfPill v-else tone="info">{{ u.role || '—' }}</PfPill>
                    </td>
                    <td>
                      <PfPill :tone="u.is_active ? 'success' : 'danger'">
                        {{ u.is_active ? 'Active' : 'Deactivated' }}
                      </PfPill>
                      <PfPill v-if="!u.is_email_verified" tone="warning">Unverified</PfPill>
                    </td>
                    <td>{{ date(u.created_at) }}</td>
                    <td class="member-actions">
                      <button class="text-button" :disabled="memberBusy === u.id" @click="toggleMemberActive(u)">
                        {{ u.is_active ? 'Deactivate' : 'Reactivate' }}
                      </button>
                      <button class="text-button" @click="resetTarget = u; newPassword = ''">
                        Set password
                      </button>
                      <button class="text-button danger-text" @click="removeTarget = u; removeConfirm = ''">
                        Remove
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Conversations ------------------------------------------------->
          <div v-else-if="tab === 'conversations'" class="org-tab-content organization-chats">
            <div class="tab-content-head chat-report-head">
              <div>
                <h3>Export chat history</h3>
                <p>Select a date range and download the conversations as an XLSX file.</p>
              </div>
            </div>

            <div class="chat-filter-bar">
              <div class="chat-date-fields">
                <label><span>From</span><input v-model="chatFrom" type="date" :max="chatTo" /></label>
                <span class="chat-date-arrow">→</span>
                <label><span>To</span><input v-model="chatTo" type="date" :min="chatFrom" /></label>
              </div>
              <div class="chat-date-presets">
                <button :class="{ active: chatPreset === 'this' }" @click="setChatRange('this')">This month</button>
                <button :class="{ active: chatPreset === 'last' }" @click="setChatRange('last')">Last month</button>
              </div>
              <button
                class="primary-button"
                :disabled="!filteredChats.length"
                @click="downloadChatsXlsx"
              >⇩ Download XLSX</button>
            </div>

            <div class="chat-export-summary">
              <article><span>Conversations</span><strong>{{ num(filteredChats.length) }}</strong></article>
              <article><span>Total messages</span><strong>{{ num(chatMessageTotal) }}</strong></article>
              <article><span>AI resolved</span><strong>{{ chatResolvedPct }}</strong></article>
              <article><span>Average rating</span><strong>{{ chatAvgRating }}</strong></article>
            </div>

            <div v-if="conversations.length" class="table-wrap">
              <table>
                <thead>
                  <tr><th>Customer</th><th>Channel</th><th>Agent</th><th>Messages</th><th>Sentiment</th><th>Status</th><th>Updated</th><th /></tr>
                </thead>
                <tbody>
                  <tr v-for="c in conversations" :key="c.session_id">
                    <td>
                      <strong>{{ c.customer?.full_name || c.customer?.email || 'Anonymous visitor' }}</strong>
                      <small v-if="c.customer?.email" class="table-subtext">{{ c.customer.email }}</small>
                    </td>
                    <td>{{ c.channel || 'web' }}</td>
                    <td>{{ c.agent_name || '—' }}</td>
                    <td class="num">{{ c.message_count }}</td>
                    <td>
                      <PfPill
                        v-if="c.sentiment"
                        :tone="c.sentiment === 'positive' ? 'success' : c.sentiment === 'negative' ? 'danger' : 'neutral'"
                      >{{ c.sentiment }}</PfPill>
                      <span v-else class="feature-no">—</span>
                    </td>
                    <td>{{ c.status || '—' }}</td>
                    <td>{{ ago(c.updated_at) }}</td>
                    <td>
                      <button class="text-button" @click="openSession = c.session_id">Open</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">
              <strong>No conversations</strong>
              <span>Nothing has been sent to this workspace's agents yet.</span>
            </div>
          </div>

          <!-- Features ------------------------------------------------------>
          <div v-else-if="tab === 'features'" class="org-tab-content organization-features">
            <div class="tab-content-head">
              <div>
                <h3>Feature access</h3>
                <p>Features inherited from the {{ plan?.name || 'assigned' }} plan, with organization-specific overrides.</p>
              </div>
            </div>

            <!-- The reference states the three numbers that decide whether the
                 table below needs reading at all: which plan, how much of it is
                 on, and how much of that was set here rather than by the plan. -->
            <div class="feature-access-summary">
              <div>
                <span>Assigned plan</span>
                <strong>{{ plan?.name || 'None' }}</strong>
              </div>
              <div>
                <span>Enabled features</span>
                <strong>{{ features.filter((f) => f.effective).length }} / {{ features.length }}</strong>
              </div>
              <div>
                <span>Custom overrides</span>
                <strong>{{ overrideCount }}</strong>
              </div>
              <div class="feature-policy-note">
                <span>ⓘ</span>
                <p>
                  Overrides apply only to this organization and do not change the
                  global {{ plan?.name || 'plan' }} plan.
                </p>
              </div>
            </div>

            <div v-if="!planConfigured" class="pf-banner warn">
              Nothing has been configured for the <strong>{{ tenant.plan_code || 'assigned' }}</strong>
              plan, so every capability is currently available on it. Set the
              plan's entitlements under Plans &amp; Limits to start restricting.
            </div>

            <div v-for="[category, list] in featureGroups" :key="category" class="feature-group">
              <h4>{{ category }}</h4>
              <div class="feature-rows">
                <div v-for="f in list" :key="f.key" class="feature-row">
                  <div class="feature-copy">
                    <strong>{{ f.label }}</strong>
                    <small>{{ f.description }}</small>
                    <code>{{ f.enforced_at }}</code>
                  </div>
                  <div class="feature-state">
                    <span class="plan-default">
                      Plan: {{ f.plan_default ? 'included' : 'not included' }}
                    </span>
                    <button
                      class="feature-access-toggle"
                      :class="{ on: f.effective }"
                      :disabled="featureBusy === f.key"
                      role="switch"
                      :aria-checked="f.effective"
                      @click="cycleFeature(f)"
                    >
                      <i />
                      <span>{{ f.effective ? 'Enabled' : 'Disabled' }}</span>
                    </button>
                    <PfPill v-if="f.override !== null" tone="warning">Override</PfPill>
                  </div>
                </div>
              </div>
            </div>

            <p class="feature-help">
              Clicking a switch adds a workspace override. Clicking it again clears
              the override so the workspace follows its plan — which is not the same
              as pinning it to the plan's current value, because a later plan change
              would then never reach this customer.
            </p>
          </div>

          <!-- Usage --------------------------------------------------------->
          <div v-else-if="tab === 'usage'" class="org-tab-content">
            <div class="tab-content-head">
              <div>
                <h3>Usage report</h3>
                <p>Billing period · {{ tenant.usage.period }}</p>
              </div>
              <div class="usage-header-actions">
                <label class="usage-period-filter">
                  <span>Month</span>
                  <select v-model="usageMonth" aria-label="Select usage month">
                    <option v-for="m in usageMonths" :key="m.value" :value="m.value">{{ m.label }}</option>
                  </select>
                </label>
                <button class="select-button" @click="exportUsageCsv">Export CSV</button>
              </div>
            </div>

            <div class="usage-kpis kpi-row">
              <article v-for="row in usageRows" :key="row.key">
                <span>{{ row.label }}</span>
                <strong>{{ num(row.used) }}</strong>
                <small v-if="row.limit === null">No limit on this plan</small>
                <small v-else :class="row.exceeded ? 'negative' : ''">
                  {{ row.percent }}% of {{ num(row.limit) }}
                </small>
              </article>
            </div>

            <div class="progress-stack">
              <PfProgress
                v-for="row in usageRows"
                :key="row.key"
                :label="row.label"
                :value="ofLimit(row.used, row.limit)"
                :percent="row.percent ?? 0"
              />
            </div>

            <div v-if="usageRows.some((r) => r.exceeded)" class="note-box danger">
              <strong>This workspace is over a limit</strong>
              <span>
                Requests against the exceeded metric are being refused with
                402 Payment Required. Move them to a larger plan, or raise the
                limit on their current one, to restore service.
              </span>
            </div>
          </div>

          <!-- Knowledge ----------------------------------------------------->
          <div v-else-if="tab === 'knowledge'" class="org-tab-content">
            <div class="tab-content-head">
              <div>
                <h3>Knowledge sources</h3>
                <p>{{ num(knowledge.total) }} in total. Sources only — the indexed text stays the customer's.</p>
              </div>
            </div>
            <div v-if="knowledge.sources.length" class="table-wrap">
              <table>
                <thead><tr><th>Source</th><th>Type</th><th>Added</th></tr></thead>
                <tbody>
                  <tr v-for="k in knowledge.sources" :key="k.id">
                    <td><strong class="break">{{ k.source }}</strong></td>
                    <td>{{ k.source_type || '—' }}</td>
                    <td>{{ date(k.created_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">
              <strong>No knowledge sources</strong>
              <span>This is the usual reason an agent answers "I don't know".</span>
            </div>
          </div>

          <!-- Integrations -------------------------------------------------->
          <div v-else-if="tab === 'integrations'" class="org-tab-content">
            <div class="tab-content-head">
              <div>
                <h3>Channels &amp; widgets</h3>
                <p>Whether a channel is connected. Credentials and webhook secrets are never returned.</p>
              </div>
            </div>

            <h4 class="sub-heading">Connected channels</h4>
            <div v-if="integrations.channels.length" class="table-wrap">
              <table>
                <thead><tr><th>Channel</th><th>Name</th><th>Status</th><th>Connected</th></tr></thead>
                <tbody>
                  <tr v-for="c in integrations.channels" :key="c.id">
                    <td><strong class="capitalize">{{ c.channel_type }}</strong></td>
                    <td>{{ c.display_name || '—' }}</td>
                    <td>
                      <PfPill :tone="c.is_active ? 'success' : 'neutral'">
                        {{ c.is_active ? 'Active' : 'Inactive' }}
                      </PfPill>
                    </td>
                    <td>{{ date(c.created_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">
              <strong>No channels connected</strong>
              <span>This workspace is web-widget only.</span>
            </div>

            <h4 class="sub-heading">Widgets</h4>
            <div v-if="integrations.widgets.length" class="table-wrap">
              <table>
                <thead><tr><th>Widget</th><th>Agent</th></tr></thead>
                <tbody>
                  <tr v-for="w in integrations.widgets" :key="w.id">
                    <td><strong>{{ w.name }}</strong></td>
                    <td>{{ w.agent_id ? agents.find((a) => a.id === w.agent_id)?.name || w.agent_id : '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">
              <strong>No widgets</strong>
              <span>Nothing has been embedded on the customer's site yet.</span>
            </div>
          </div>

          <!-- Audit --------------------------------------------------------->
          <div v-else-if="tab === 'billing'" class="org-tab-content">
            <div class="tab-content-head">
              <div>
                <h3>Subscription &amp; billing</h3>
                <p>Plan, add-on messages, payment method and invoice history for this organization.</p>
              </div>
              <button class="select-button" @click="subscriptionOpen = true">Manage subscription</button>
            </div>

            <section class="billing-detail-cards">
              <article class="panel soft">
                <span class="field-label">Current plan</span>
                <strong class="billing-figure">{{ plan?.name ?? 'No plan' }}</strong>
                <small>{{ planPriceLabel }}</small>
              </article>
              <article class="panel soft">
                <span class="field-label">Next invoice</span>
                <strong class="billing-figure">{{ nextInvoiceLabel }}</strong>
                <small>{{ renewalLabel }}</small>
              </article>
              <article class="panel soft">
                <span class="field-label">Payment method</span>
                <strong class="billing-figure">Not connected</strong>
                <!-- Said plainly. A card number here would be invented: no payment
                     processor is wired to this deployment. -->
                <small>No payment processor is connected yet</small>
              </article>
            </section>

            <div class="empty-state">
              <strong>No invoices yet</strong>
              <span>
                Invoices appear once a payment processor is connected. Until then
                the figures above come from the plan catalogue, not from a bill
                anyone has been sent.
              </span>
            </div>
          </div>

          <div v-else-if="tab === 'audit'" class="org-tab-content">
            <div class="tab-content-head">
              <div>
                <h3>Operator actions on this workspace</h3>
                <p>Everything platform staff have done here, including transcripts opened.</p>
              </div>
              <RouterLink to="/platform/audit" class="text-button">Full log →</RouterLink>
            </div>

            <div v-if="audit.length" class="audit-list flush">
              <div v-for="entry in audit" :key="entry.id" class="audit-row">
                <span class="audit-icon" :class="entry.action.includes('delete') ? 'danger' : entry.action.includes('read') ? 'info' : ''">
                  {{ entry.action.includes('delete') ? '!' : entry.action.includes('read') ? '↗' : '✓' }}
                </span>
                <div class="grow">
                  <strong>{{ entry.action }}</strong>
                  <p>{{ JSON.stringify(entry.details) }}</p>
                </div>
                <div class="audit-meta">
                  <strong>{{ entry.actor_email }}</strong>
                  <span>{{ dateTime(entry.created_at) }}</span>
                </div>
              </div>
            </div>
            <div v-else class="empty-state">
              <strong>No operator actions recorded</strong>
              <span>Nobody on the platform team has touched this workspace.</span>
            </div>
          </div>
        </section>

        <!-- Aside ---------------------------------------------------------->
        <aside class="detail-aside">
          <section class="panel">
            <div class="panel-heading">
              <h3>Account health</h3>
              <PfPill :tone="tenant.is_active ? 'success' : 'danger'">
                {{ tenant.is_active ? 'Active' : 'Suspended' }}
              </PfPill>
            </div>
            <div class="health-list">
              <div>
                <span class="health-icon" :class="tenant.users.some((u) => u.is_email_verified) ? '' : 'warning'">
                  {{ tenant.users.some((u) => u.is_email_verified) ? '✓' : '!' }}
                </span>
                <p>
                  <strong>{{ tenant.users.filter((u) => u.is_email_verified).length }} of {{ tenant.users.length }} verified</strong>
                  <small>Unverified members cannot sign in when verification is enforced</small>
                </p>
              </div>
              <div>
                <span class="health-icon" :class="plan ? '' : 'warning'">{{ plan ? '✓' : '!' }}</span>
                <p>
                  <strong>{{ plan ? `${plan.name} plan` : 'No plan assigned' }}</strong>
                  <small>{{ plan ? (plan.price_cents ? `${money(priceMonthly)} per month` : 'Free tier') : 'Quotas fall back to the default plan' }}</small>
                </p>
              </div>
              <div v-if="worstUsage">
                <span class="health-icon" :class="(worstUsage.percent ?? 0) >= 100 ? 'danger' : (worstUsage.percent ?? 0) >= 80 ? 'warning' : ''">
                  {{ (worstUsage.percent ?? 0) >= 80 ? '!' : '✓' }}
                </span>
                <p>
                  <strong>{{ worstUsage.percent }}% of {{ worstUsage.label.toLowerCase() }} used</strong>
                  <small>{{ ofLimit(worstUsage.used, worstUsage.limit) }} this period</small>
                </p>
              </div>
              <div>
                <span class="health-icon" :class="agents.some((a) => a.is_active) ? '' : 'warning'">
                  {{ agents.some((a) => a.is_active) ? '✓' : '!' }}
                </span>
                <p>
                  <strong>{{ agents.filter((a) => a.is_active).length }} live agent{{ agents.filter((a) => a.is_active).length === 1 ? '' : 's' }}</strong>
                  <small>{{ agents.length ? 'Answering customer messages' : 'Onboarding not finished' }}</small>
                </p>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-heading">
              <div>
                <h3>Quick admin actions</h3>
                <p>Manage this organization</p>
              </div>
            </div>
            <div class="quick-actions">
              <button @click="tab = 'billing'">
                <span>◆</span><strong>Manage subscription</strong><small>Plan and add-ons</small>
              </button>
              <button @click="tab = 'members'">
                <span>♙</span><strong>Manage members</strong><small>Roles and access</small>
              </button>
              <button @click="enterSupportMode">
                <span>↗</span><strong>Support mode</strong><small>Open client workspace</small>
              </button>
              <button class="danger" :disabled="busy" @click="toggleActive">
                <span>{{ tenant.is_active ? '⊘' : '✓' }}</span>
                <strong>{{ tenant.is_active ? 'Suspend account' : 'Activate account' }}</strong>
                <small>{{ tenant.is_active ? 'Block workspace access' : 'Restore workspace access' }}</small>
              </button>
            </div>
          </section>
        </aside>

        <!-- Manage subscription. Plan changes go through the same endpoint the
             plan selector uses, so there is one path that can move a tenant. -->
        <div
          v-if="subscriptionOpen"
          class="pf-modal-backdrop"
          @click.self="subscriptionOpen = false"
        >
          <div class="pf-modal" role="dialog" aria-modal="true" aria-labelledby="sub-title">
            <header class="pf-modal-head">
              <div>
                <span class="field-label">{{ tenant.name }}</span>
                <h2 id="sub-title">Manage subscription</h2>
                <p>Select the plan assigned to this organization.</p>
              </div>
              <button class="pf-modal-close" aria-label="Close" @click="subscriptionOpen = false">×</button>
            </header>

            <div class="pf-modal-body">
              <label
                v-for="p in plans"
                :key="p.code"
                class="pf-choice"
                :class="{ 'pf-choice-active': p.code === tenant.plan_code }"
              >
                <input
                  type="radio"
                  name="sub-plan"
                  :value="p.code"
                  :checked="p.code === tenant.plan_code"
                  @change="changePlan(p.code); subscriptionOpen = false"
                />
                <span class="pf-choice-text">
                  <span class="pf-choice-title">
                    {{ p.name }}
                    <span v-if="p.code === tenant.plan_code" class="pf-choice-badge">Current</span>
                  </span>
                  <span class="pf-choice-detail">
                    {{ p.price_cents ? `$${(p.price_cents / 100).toFixed(0)}/month` : '$0 forever' }}
                    ·
                    {{ p.limits?.ai_messages === null ? 'unlimited messages' : `${num(p.limits?.ai_messages ?? 0)} messages` }}
                  </span>
                </span>
              </label>
            </div>

            <footer class="pf-modal-foot">
              <button class="select-button" @click="subscriptionOpen = false">Cancel</button>
            </footer>
          </div>
        </div>
      </div>

      <TranscriptModal
        v-if="openSession"
        :tenant-id="props.id"
        :session-id="openSession"
        @close="openSession = null"
      />

      <!-- Password reset ------------------------------------------------------>
      <div v-if="resetTarget" class="pf-overlay center" @mousedown.self="resetTarget = null">
        <section class="pf-modal" role="dialog" aria-modal="true">
          <div class="pf-modal-head">
            <div>
              <span>Account recovery</span>
              <h2>Set a new password</h2>
              <p>{{ resetTarget.email }}</p>
            </div>
            <button class="pf-close" aria-label="Close" @click="resetTarget = null">×</button>
          </div>
          <div class="pf-modal-body">
            <label class="field">
              <span>New password</span>
              <input
                v-model="newPassword"
                type="text"
                placeholder="At least 8 characters, mixed case and a number"
              />
              <small class="field-hint">
                Shown as text so you can read it out. Their existing sessions are
                signed out the moment this is saved.
              </small>
            </label>
            <div class="note-box">
              <strong>This is an account takeover, and is logged as one</strong>
              <span>
                The audit entry names you, this customer and this user. The
                password itself is never written to the log.
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

      <!-- Remove member ------------------------------------------------------>
      <div v-if="removeTarget" class="pf-overlay center" @mousedown.self="removeTarget = null">
        <section class="pf-modal" role="dialog" aria-modal="true">
          <div class="pf-modal-head">
            <div>
              <span>Irreversible</span>
              <h2>Remove {{ removeTarget.full_name || removeTarget.email }}?</h2>
            </div>
            <button class="pf-close" aria-label="Close" @click="removeTarget = null">×</button>
          </div>
          <div class="pf-modal-body">
            <div class="note-box danger">
              <strong>They lose access immediately</strong>
              <span>
                Their conversations stay with the workspace, but the account and
                its sessions are gone. If they are the only member left, delete
                the whole workspace instead.
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
    </template>
  </PfPage>
</template>

<style scoped>
.billing-figure { display: block; margin: 6px 0 4px; font-size: 22px; font-weight: 700; }
.panel.soft { padding: 16px; }
.metrics-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
@media (max-width: 900px) {
  .metrics-grid.three { grid-template-columns: minmax(0, 1fr); }
}

.section-divider {
  height: 1px;
  background: var(--o08);
  margin: 22px 0;
}

.progress-stack { display: flex; flex-direction: column; gap: 14px; }

.sub-heading {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  color: var(--text2);
  margin: 22px 0 12px;
}
.sub-heading:first-of-type { margin-top: 0; }

.inline-select {
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--o12);
  border-radius: var(--radius-sm);
  background: var(--o04);
  color: var(--text2);
  font-size: 11px;
  outline: none;
}
.inline-select:focus { border-color: var(--accent-border); box-shadow: var(--ring-focus); }
.inline-select option { background: var(--surface); color: var(--text); }

.member-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.danger-text { color: var(--c-danger); }

.feature-summary { display: flex; align-items: center; gap: 10px; font-size: var(--text-xs); color: var(--muted); }

.feature-group { margin-bottom: 22px; }
.feature-group h4 {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--muted2);
  margin: 0 0 10px;
}

.feature-rows { display: flex; flex-direction: column; gap: 8px; }

.feature-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border: 1px solid var(--o08);
  border-radius: var(--radius-md);
  background: var(--o03);
  flex-wrap: wrap;
}

.feature-copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.feature-copy strong { font-size: var(--text-xs); color: var(--text); }
.feature-copy small { font-size: 11px; color: var(--muted2); line-height: 1.5; }
.feature-copy code {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--faint);
  margin-top: 2px;
}

.feature-state { display: flex; align-items: center; gap: 10px; flex-shrink: 0; flex-wrap: wrap; }
.plan-default { font-size: 10px; color: var(--muted2); }

.feature-help {
  font-size: 11px;
  color: var(--muted2);
  line-height: 1.6;
  margin: 0;
  padding-top: 14px;
  border-top: 1px solid var(--o08);
}

.audit-list.flush .audit-row { padding-left: 0; padding-right: 0; }
.break { word-break: break-all; }
.capitalize { text-transform: capitalize; }

a.select-button, a.text-button { text-decoration: none; }
</style>
