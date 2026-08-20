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

The plan catalog: prices, usage ceilings, and which capabilities each tier
includes.

Everything here applies the moment it is saved. Quotas and feature gates read
these tables live rather than copying them onto a tenant at signup, so lowering
a limit can put an existing customer instantly over quota and turning a feature
off can take it away mid-session. The UI says how many workspaces each change
touches rather than letting that be discovered afterwards.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfApplyChangesDialog from '@/components/platform/PfApplyChangesDialog.vue'
import {
  getPlatformPlans, updatePlan, getFeatureMatrix, setPlanFeatures, savePlanLimits,
  type PlatformPlan, type FeatureMatrix, type FeatureDef,
  type ApplyPolicy, type PlanLimitsPayload,
} from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, money } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const busy = ref(false)

const plans = ref<PlatformPlan[]>([])
const matrix = ref<FeatureMatrix | null>(null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [p, m] = await Promise.all([getPlatformPlans(), getFeatureMatrix()])
    plans.value = p
    matrix.value = m
  } catch (e) {
    error.value = extractApiError(e, 'Could not load the plan catalog')
  } finally {
    loading.value = false
  }
}
onMounted(load)

// Two vocabularies meet here. `metric` is what the API nests under `limits`
// and what the quota service enforces; `column` is the database field the PATCH
// endpoint accepts. Carrying both is what stops the two drifting — reading
// `plan.max_agents` off a response that nests it under `limits.agents` is why
// this table showed "Unlimited" for every plan.
const LIMIT_FIELDS = [
  { key: 'max_conversations_per_month', metric: 'conversations', label: 'Conversations / month' },
  { key: 'max_ai_messages_per_month', metric: 'ai_messages', label: 'AI replies / month' },
  { key: 'max_agents', metric: 'agents', label: 'AI agents' },
  { key: 'max_seats', metric: 'seats', label: 'Team members' },
  { key: 'max_knowledge_docs', metric: 'knowledge_docs', label: 'Knowledge sources' },
  { key: 'max_storage_mb', metric: 'storage_mb', label: 'Storage (MB)' },
] as const

// The operator-facing table, ordered as the pricing page reads rather than as
// the schema happens to be laid out.
type TermRow =
  | { kind: 'price'; label: string }
  | { kind: 'limit'; metric: string; label: string; unit?: string }
  | { kind: 'policy'; column: string; label: string; money?: boolean; unit?: string }

const TERM_ROWS: TermRow[] = [
  { kind: 'price', label: 'Plan price' },
  { kind: 'limit', metric: 'agents', label: 'AI agents' },
  { kind: 'limit', metric: 'knowledge_docs', label: 'Knowledge sources' },
  { kind: 'policy', column: 'max_subpages_per_source', label: 'Sub-pages per source' },
  { kind: 'limit', metric: 'ai_messages', label: 'Messages per month' },
  { kind: 'limit', metric: 'image_requests', label: 'Image requests per month' },
  { kind: 'policy', column: 'overage_price_cents_per_message', label: 'Additional messages', money: true },
  { kind: 'policy', column: 'data_retention_days', label: 'Data retention', unit: 'days' },
  { kind: 'limit', metric: 'conversations', label: 'Conversations per month' },
  { kind: 'limit', metric: 'seats', label: 'Team members' },
  { kind: 'limit', metric: 'storage_mb', label: 'Storage (MB)' },
]

const rowId = (row: TermRow) =>
  row.kind === 'price' ? 'price' : row.kind === 'limit' ? `limit:${row.metric}` : `policy:${row.column}`

/** Raw stored value for a row, in the units the API uses. */
const rawValue = (plan: PlatformPlan, row: TermRow): number | null => {
  if (row.kind === 'price') return plan.price_cents
  if (row.kind === 'limit') return plan.limits?.[row.metric as keyof typeof plan.limits] ?? null
  return (plan.policies ?? {})[row.column] ?? null
}

/** How a stored value reads when nobody is editing. */
const displayValue = (plan: PlatformPlan, row: TermRow): string => {
  const value = rawValue(plan, row)
  if (row.kind === 'price') return value ? money(value / 100) : '$0'
  if (value === null || value === undefined) {
    // Blank means different things per row, and saying "Unlimited" for a price
    // the operator has chosen not to offer would be plainly wrong.
    if (row.kind === 'policy' && row.money) return 'Not available'
    return row.kind === 'policy' ? '—' : 'Unlimited'
  }
  if (row.kind === 'policy' && row.money) return `${money(value / 100)} each`
  return row.unit ? `${num(value)} ${row.unit}` : num(value)
}

/** Which top-bar the card gets.
 *
 * The reference keys this off the plan code (free / base / pro) and its CSS
 * paints grey, lime and dark accordingly. Codes here may not be those three, so
 * a known code uses its own tone and anything else falls back to position —
 * which keeps a fourth tier like Scale from rendering with no accent at all.
 */
const cardTone = (plan: PlatformPlan, index: number) =>
  ['free', 'base', 'pro'].includes(plan.code)
    ? plan.code
    : PLAN_ACCENTS[index % PLAN_ACCENTS.length]

/** The six lines a plan card sells itself with.
 *
 * Phrased as offers rather than as a metric name beside a number: "1 knowledge
 * source · 10 sub-pages" is what a customer is buying; "1 knowledge_docs" is
 * what the database calls it.
 */
const planHighlights = (plan: PlatformPlan): string[] => {
  const limits = plan.limits ?? ({} as Record<string, number | null>)
  const policies = plan.policies ?? {}
  const plural = (n: number | null | undefined, one: string, many = `${one}s`) =>
    n === 1 ? `1 ${one}` : `${num(n ?? 0)} ${many}`

  const agents = limits.agents
  const sources = limits.knowledge_docs
  const subpages = policies.max_subpages_per_source
  const messages = limits.ai_messages
  const images = limits.image_requests
  const retention = policies.data_retention_days

  return [
    agents === null ? 'Unlimited AI agents' : plural(agents, 'AI agent'),
    messages === null ? 'Unlimited messages / month' : `${num(messages ?? 0)} messages / month`,
    sources === null
      ? 'Unlimited knowledge sources'
      : `${plural(sources, 'knowledge source')}${subpages ? ` · ${num(subpages)} sub-pages` : ''}`,
    images === null
      ? 'Unlimited image requests / month'
      : images
        ? `${num(images)} image requests / month`
        : 'No image analysis',
    retention ? `${num(retention)}-day data retention` : 'Unlimited data retention',
    plan.price_cents ? 'All integrations' : 'WhatsApp integration',
  ]
}

const PLAN_ACCENTS = ['', 'accent', 'purple', 'teal']
const accentFor = (i: number) => PLAN_ACCENTS[i % PLAN_ACCENTS.length]

// ── Limits editing ─────────────────────────────────────────────────────────

const editingLimits = ref<string | null>(null)
// Strings, not numbers: an empty field must be distinguishable from 0, because
// blank means "unlimited" and 0 means "none allowed" — genuinely different
// statements, and a numeric input collapses them.
const draft = ref<Record<string, string | number>>({})

const startEdit = (plan: PlatformPlan) => {
  draft.value = {
    name: plan.name,
    description: plan.description ?? '',
    price: (plan.price_cents / 100).toString(),
  }
  for (const f of LIMIT_FIELDS) {
    const value = plan.limits?.[f.metric as keyof typeof plan.limits]
    draft.value[f.key] = value === null || value === undefined ? '' : String(value)
  }
  editingLimits.value = plan.code
}

const cancelEdit = () => { editingLimits.value = null; draft.value = {} }

const drawerApplyOpen = ref(false)
const drawerApplyError = ref('')

/** Tenants on the plan open in the drawer — what the dialog warns about. */
const drawerAffected = computed(() => {
  const code = editingLimits.value
  return code ? plans.value.find((p) => p.code === code)?.tenant_count ?? 0 : 0
})

const saveLimits = async (plan: PlatformPlan, policy: ApplyPolicy) => {
  busy.value = true
  drawerApplyError.value = ''
  try {
    // Naming is a label change and applies to everyone regardless — there is no
    // sense in which a customer keeps an old plan *name*. Prices and ceilings
    // are the part the apply policy governs, so they go through the endpoint
    // that understands it.
    await updatePlan(plan.code, {
      name: String(draft.value.name ?? '').trim(),
      description: String(draft.value.description ?? '').trim() || null,
    })

    const limits: Record<string, number | null> = {}
    for (const f of LIMIT_FIELDS) {
      // Explicit null tells the server "unlimited"; omitting the key would
      // instead mean "leave unchanged", which is not what a cleared field says.
      limits[f.metric] = toFieldNumber(draft.value[f.key])
    }
    const result = await savePlanLimits({
      apply_policy: policy,
      plans: {
        [plan.code]: {
          price_cents: Math.round((toFieldNumber(draft.value.price) ?? 0) * 100),
          limits,
        },
      },
    })

    toast.success(result.message)
    drawerApplyOpen.value = false
    cancelEdit()
    await load()
  } catch (e) {
    drawerApplyError.value = extractApiError(e, 'Could not save the plan')
  } finally {
    busy.value = false
  }
}

const limitText = (plan: PlatformPlan, metric: string) => {
  const value = plan.limits?.[metric as keyof typeof plan.limits]
  return value === null || value === undefined ? 'Unlimited' : num(value)
}

// ── Plan terms table editing ───────────────────────────────────────────────

const editingTerms = ref(false)
// Keyed `${planCode}|${rowId}`. Strings again, because a cleared field ("no
// ceiling") and a zero ("none allowed") are different answers that a number
// input would flatten into the same one.
const termDraft = ref<Record<string, string | number>>({})
const applyOpen = ref(false)
const applyError = ref('')

/** Editing units, which are not always storage units — money is shown in whole
 *  currency so the operator types 0.01 rather than 1. */
const editValue = (plan: PlatformPlan, row: TermRow): string => {
  const value = rawValue(plan, row)
  if (value === null || value === undefined) return ''
  if (row.kind === 'price' || (row.kind === 'policy' && row.money)) return (value / 100).toString()
  return String(value)
}

const startTermEdit = () => {
  const next: Record<string, string> = {}
  for (const plan of plans.value) {
    for (const row of TERM_ROWS) next[`${plan.code}|${rowId(row)}`] = editValue(plan, row)
  }
  termDraft.value = next
  editingTerms.value = true
}

const cancelTermEdit = () => {
  editingTerms.value = false
  termDraft.value = {}
  applyError.value = ''
}

/**
 * A field's value as a number, or null for "no ceiling".
 *
 * Accepts string *or* number because it receives both: these drafts start as
 * strings, but Vue applies the `.number` modifier automatically to
 * `<input type="number">`, so the moment anyone types the entry becomes a
 * number. Calling .trim() on it threw inside a computed, which took the whole
 * view down — the page went black on the first keystroke in a price field.
 *
 * Empty is checked before Number(), because Number('') is 0 and blank means
 * unlimited, not none.
 */
const toFieldNumber = (raw: string | number | null | undefined): number | null => {
  if (raw === null || raw === undefined) return null
  const text = String(raw).trim()
  if (text === '') return null
  const value = Number(text)
  return Number.isNaN(value) ? null : value
}

/** Back to storage units, with an empty field meaning null rather than 0. */
const parseTerm = (raw: string | number | null | undefined, row: TermRow): number | null => {
  const value = toFieldNumber(raw)
  if (value === null) return null
  return row.kind === 'price' || (row.kind === 'policy' && row.money)
    ? Math.round(value * 100)
    : Math.round(value)
}

const termsChanged = computed(() => {
  if (!editingTerms.value) return false
  return plans.value.some((plan) =>
    TERM_ROWS.some(
      (row) => parseTerm(termDraft.value[`${plan.code}|${rowId(row)}`] ?? '', row) !== rawValue(plan, row),
    ),
  )
})

/** Organizations sitting on the plans being edited — what the dialog warns about. */
const termsAffected = computed(() =>
  plans.value.reduce((total, plan) => total + (plan.tenant_count ?? 0), 0),
)

const buildTermsPayload = (policy: ApplyPolicy): PlanLimitsPayload => {
  const payload: PlanLimitsPayload = { apply_policy: policy, plans: {} }
  for (const plan of plans.value) {
    const limits: Record<string, number | null> = {}
    const policies: Record<string, number | null> = {}
    let price: number | null = null

    for (const row of TERM_ROWS) {
      const parsed = parseTerm(termDraft.value[`${plan.code}|${rowId(row)}`] ?? '', row)
      if (row.kind === 'price') price = parsed ?? 0
      else if (row.kind === 'limit') limits[row.metric] = parsed
      else policies[row.column] = parsed
    }
    payload.plans[plan.code] = { price_cents: price, limits, policies }
  }
  return payload
}

const confirmTermSave = async (policy: ApplyPolicy) => {
  busy.value = true
  applyError.value = ''
  try {
    const result = await savePlanLimits(buildTermsPayload(policy))
    toast.success(result.message)
    applyOpen.value = false
    cancelTermEdit()
    await load()
  } catch (e) {
    applyError.value = extractApiError(e, 'Could not save the plan limits')
  } finally {
    busy.value = false
  }
}

// ── Feature matrix editing ─────────────────────────────────────────────────

// The whole matrix is edited at once, as the reference does. Editing one plan at
// a time meant an operator moving a capability up a tier had to save twice and
// answer the apply question twice, for what is one decision.
const editingFeatures = ref(false)
// Keyed `${planCode}|${featureKey}` — one flat map rather than nested objects,
// so a cell reads and writes in one place and change detection is a comparison
// against the same key.
const featureDraft = ref<Record<string, boolean>>({})
const featureApplyOpen = ref(false)
const featureApplyError = ref('')

const startFeatureEdit = () => {
  const next: Record<string, boolean> = {}
  for (const plan of matrix.value?.plans ?? []) {
    for (const f of matrix.value?.features ?? []) {
      next[`${plan.code}|${f.key}`] = !!plan.features[f.key]
    }
  }
  featureDraft.value = next
  editingFeatures.value = true
}

const cancelFeatureEdit = () => {
  editingFeatures.value = false
  featureDraft.value = {}
  featureApplyError.value = ''
}

/** Plans whose feature set differs from what is stored. Only these are sent, so
 *  an untouched plan is never rewritten and its audit trail stays quiet. */
const changedPlans = computed(() =>
  (matrix.value?.plans ?? []).filter((plan) =>
    (matrix.value?.features ?? []).some(
      (f) => !!plan.features[f.key] !== !!featureDraft.value[`${plan.code}|${f.key}`],
    ),
  ),
)

const featuresChanged = computed(() => changedPlans.value.length > 0)

/** Workspaces on the plans actually being changed — what the dialog warns about. */
const featuresAffected = computed(() =>
  changedPlans.value.reduce(
    (total, plan) => total + (plans.value.find((p) => p.code === plan.code)?.tenant_count ?? 0),
    0,
  ),
)

const confirmFeatureMatrixSave = async () => {
  busy.value = true
  featureApplyError.value = ''
  try {
    for (const plan of changedPlans.value) {
      const payload: Record<string, boolean> = {}
      for (const f of matrix.value?.features ?? []) {
        payload[f.key] = !!featureDraft.value[`${plan.code}|${f.key}`]
      }
      await setPlanFeatures(plan.code, payload)
    }
    const n = changedPlans.value.length
    toast.success(`Features saved for ${n} plan${n === 1 ? '' : 's'}.`)
    featureApplyOpen.value = false
    cancelFeatureEdit()
    await load()
  } catch (e) {
    featureApplyError.value = extractApiError(e, 'Could not save the feature set')
  } finally {
    busy.value = false
  }
}

const featureGroups = computed(() => {
  const groups: Record<string, FeatureDef[]> = {}
  for (const f of matrix.value?.features ?? []) (groups[f.category] ??= []).push(f)
  return Object.entries(groups)
})

const unconfigured = computed(
  () => (matrix.value?.plans ?? []).filter((p) => !p.configured).map((p) => p.name),
)
</script>

<template>
  <PfPage
    title="Plans &amp; limits"
    description="What each subscription tier costs, allows, and includes."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="select-button" @click="load">Refresh</button>
    </template>

    <template v-if="matrix">
      <div v-if="unconfigured.length" class="pf-banner warn">
        <span>
          <strong>{{ unconfigured.join(', ') }}</strong>
          {{ unconfigured.length === 1 ? 'has' : 'have' }} no feature set configured,
          so every capability is currently available on
          {{ unconfigured.length === 1 ? 'it' : 'them' }}. Save a feature set below
          to start restricting — an unconfigured plan is treated as unrestricted
          rather than empty, so a fresh deployment never locks customers out of
          everything at once.
        </span>
      </div>

      <!-- Plan cards --------------------------------------------------------->
      <section class="plan-grid">
        <article
          v-for="(plan, i) in plans"
          :key="plan.code"
          class="plan-card"
          :class="cardTone(plan, i)"
        >
          <div class="plan-top">
            <div>
              <span class="plan-kicker">{{ plan.name }}</span>
              <h2>
                {{ plan.price_cents ? money(plan.price_cents / 100).replace('.00', '') : '$0' }}
                <small>{{ plan.price_cents ? '/agent/month' : ' forever' }}</small>
              </h2>
              <p>{{ plan.description || 'No description' }}</p>
            </div>
            <PfPill v-if="plan.is_default" tone="accent">Default</PfPill>
            <PfPill v-else-if="!plan.is_active" tone="neutral">Retired</PfPill>
            <button v-else class="icon-button" :aria-label="`Actions for ${plan.name}`">•••</button>
          </div>

          <div class="plan-users">
            {{ num(plan.tenant_count) }}
            {{ plan.tenant_count === 1 ? 'organization' : 'organizations' }}
          </div>

          <!-- Written the way the reference words them — "1 AI agent",
               "1 knowledge source · 10 sub-pages" — rather than a bare number
               beside a column name, which reads as a spec sheet, not an offer. -->
          <ul>
            <li v-for="line in planHighlights(plan)" :key="line">
              <span>✓</span>{{ line }}
            </li>
          </ul>

          <button class="wide-button" @click="startEdit(plan)">Edit plan limits</button>
        </article>
      </section>

      <!-- Plan limits -------------------------------------------------------->
      <section class="panel table-panel">
        <div class="table-toolbar">
          <div>
            <h2 class="section-title">Plan limits</h2>
            <p class="section-sub">
              Usage allowances and retention rules enforced by the platform.
              Blank means unlimited; zero means none allowed — a genuinely
              different statement, and both are enforced as written.
            </p>
          </div>
          <div class="toolbar-actions">
            <template v-if="editingTerms">
              <button class="select-button" :disabled="busy" @click="cancelTermEdit">Cancel</button>
              <button
                class="primary-button"
                :disabled="busy || !termsChanged"
                @click="applyOpen = true"
              >
                Save changes
              </button>
            </template>
            <button v-else class="select-button" @click="startTermEdit">✎ Edit limits</button>
          </div>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Limit</th>
                <th v-for="p in plans" :key="p.code">{{ p.name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in TERM_ROWS" :key="rowId(row)">
                <td><strong>{{ row.label }}</strong></td>
                <td v-for="p in plans" :key="p.code" class="num">
                  <input
                    v-if="editingTerms"
                    v-model="termDraft[`${p.code}|${rowId(row)}`]"
                    class="term-input"
                    type="number"
                    min="0"
                    :step="row.kind === 'price' || (row.kind === 'policy' && row.money) ? '0.01' : '1'"
                    placeholder="—"
                    :aria-label="`${row.label} for ${p.name}`"
                  />
                  <template v-else>{{ displayValue(p, row) }}</template>
                </td>
              </tr>
              <tr>
                <td><strong>Workspaces on this plan</strong></td>
                <td v-for="p in plans" :key="p.code" class="num">{{ num(p.tenant_count) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="editingTerms" class="section-sub edit-hint">
          Leave a field empty for unlimited. "Additional messages" empty means
          overage is not offered and the tenant is blocked at their limit.
        </p>
      </section>

      <PfApplyChangesDialog
        :open="applyOpen"
        :affected="termsAffected"
        change-type="Prices and usage limits"
        :saving="busy"
        :error="applyError"
        @cancel="applyOpen = false"
        @confirm="confirmTermSave"
      />

      <!-- Feature matrix ----------------------------------------------------->
      <section class="panel table-panel">
        <div class="table-toolbar">
          <div>
            <h2 class="section-title">Complete feature availability</h2>
            <p class="section-sub">
              Every customer-facing capability included in each plan. Each switch
              is enforced by real code — the path is named under each capability,
              so nothing in this table is decorative.
            </p>
          </div>
          <div class="toolbar-actions">
            <template v-if="editingFeatures">
              <button class="select-button" :disabled="busy" @click="cancelFeatureEdit">Cancel</button>
              <button
                class="primary-button"
                :disabled="busy || !featuresChanged"
                @click="featureApplyOpen = true"
              >Save features</button>
            </template>
            <button v-else class="select-button" @click="startFeatureEdit()">✎ Edit features</button>
          </div>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Feature</th>
                <th v-for="p in matrix.plans" :key="p.code">
                  {{ p.name }}
                  <span v-if="!p.configured" class="th-note">unconfigured</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <template v-for="[category, list] in featureGroups" :key="category">
                <tr class="group-row">
                  <td :colspan="matrix.plans.length + 1"><span class="feature-category">{{ category }}</span></td>
                </tr>
                <tr v-for="f in list" :key="f.key">
                  <td>
                    <strong>{{ f.label }}</strong>
                    <small class="table-subtext">{{ f.description }}</small>
                    <code class="enforced">{{ f.enforced_at }}</code>
                  </td>
                  <td
                    v-for="p in matrix.plans"
                    :key="p.code"
                    :class="{ 'editing-cell': editingFeatures }"
                  >
                    <button
                      v-if="editingFeatures"
                      class="feature-access-toggle"
                      :class="{ on: featureDraft[`${p.code}|${f.key}`] }"
                      role="switch"
                      :aria-checked="!!featureDraft[`${p.code}|${f.key}`]"
                      :aria-label="`${f.label} on ${p.name}`"
                      @click="featureDraft[`${p.code}|${f.key}`] = !featureDraft[`${p.code}|${f.key}`]"
                    >
                      <i />
                      <span>{{ featureDraft[`${p.code}|${f.key}`] ? 'Included' : 'No' }}</span>
                    </button>
                    <span v-else-if="!p.configured" class="feature-yes muted">✓ (unset)</span>
                    <span v-else-if="p.features[f.key]" class="feature-yes">✓ Included</span>
                    <span v-else class="feature-no">—</span>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <!-- Edit plan drawer ----------------------------------------------------->
    <div v-if="editingLimits" class="pf-overlay right" @mousedown.self="cancelEdit">
      <aside class="pf-drawer" role="dialog" aria-modal="true" aria-labelledby="edit-plan-title">
        <div class="pf-drawer-head">
          <div>
            <span>Plan catalog</span>
            <h2 id="edit-plan-title">Edit {{ editingLimits }}</h2>
          </div>
          <button class="pf-close" aria-label="Close" @click="cancelEdit">×</button>
        </div>

        <div class="pf-drawer-body">
          <section>
            <h3>Presentation</h3>
            <div class="form-grid">
              <label class="full">
                <span>Display name</span>
                <input v-model="draft.name" />
              </label>
              <label class="full">
                <span>Description</span>
                <input v-model="draft.description" placeholder="Shown on the pricing table" />
              </label>
              <label>
                <span>Price per month (USD)</span>
                <input v-model="draft.price" type="number" min="0" step="1" />
              </label>
            </div>
          </section>

          <section>
            <h3>Usage limits</h3>
            <div class="form-grid">
              <label v-for="f in LIMIT_FIELDS" :key="f.key">
                <span>{{ f.label }}</span>
                <input v-model="draft[f.key]" type="number" min="0" placeholder="Unlimited" />
              </label>
            </div>
            <div class="note-box">
              <strong>Leave a field blank for unlimited</strong>
              <span>
                Zero is not the same as blank: a plan with zero agents is a plan
                that cannot create agents, which is a real choice and is enforced
                as one.
              </span>
            </div>
          </section>

          <div
            v-if="plans.find((p) => p.code === editingLimits)?.tenant_count"
            class="note-box danger"
          >
            <strong>
              {{ num(plans.find((p) => p.code === editingLimits)?.tenant_count ?? 0) }}
              workspace(s) are on this plan
            </strong>
            <span>
              Quotas are read live, so lowering a limit below what a customer is
              already using puts them over quota immediately. Their requests
              against that metric start returning 402 Payment Required.
            </span>
          </div>
        </div>

        <div class="pf-drawer-footer">
          <button class="select-button" @click="cancelEdit">Cancel</button>
          <button
            class="primary-button"
            :disabled="busy"
            @click="drawerApplyOpen = true"
          >{{ busy ? 'Saving…' : 'Save plan' }}</button>
        </div>
      </aside>

      <PfApplyChangesDialog
        :open="drawerApplyOpen"
        :affected="drawerAffected"
        change-type="Plan price and usage limits"
        :saving="busy"
        :error="drawerApplyError"
        @cancel="drawerApplyOpen = false"
        @confirm="(policy) => saveLimits(plans.find((p) => p.code === editingLimits)!, policy)"
      />
    </div>

    <PfApplyChangesDialog
      :open="featureApplyOpen"
      :affected="featuresAffected"
      change-type="Plan feature availability"
      :saving="busy"
      :error="featureApplyError"
      @cancel="featureApplyOpen = false"
      @confirm="confirmFeatureMatrixSave"
    />
  </PfPage>
</template>

<style scoped>
.section-title {
  font-family: var(--font-display);
  font-size: var(--text-base);
  margin: 0;
  color: var(--text);
}

.section-sub {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--muted2);
  max-width: 62ch;
  line-height: 1.5;
}

.editing-label {
  font-size: 11px;
  color: var(--accent-ink);
  font-family: var(--font-mono);
}

.group-row td {
  background: var(--o03);
  padding-top: 14px;
  padding-bottom: 8px;
}

.enforced {
  display: block;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--faint);
  margin-top: 3px;
}

.th-note {
  display: block;
  font-size: 8.5px;
  color: var(--c-warn);
  letter-spacing: 0;
  text-transform: none;
  margin-top: 2px;
}

.feature-yes.muted { color: var(--muted2); }
</style>
