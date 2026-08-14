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
import {
  getPlatformPlans, updatePlan, getFeatureMatrix, setPlanFeatures,
  type PlatformPlan, type FeatureMatrix, type FeatureDef,
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

const LIMIT_FIELDS = [
  { key: 'max_conversations_per_month', label: 'Conversations / month' },
  { key: 'max_ai_messages_per_month', label: 'AI replies / month' },
  { key: 'max_agents', label: 'AI agents' },
  { key: 'max_seats', label: 'Team members' },
  { key: 'max_knowledge_docs', label: 'Knowledge sources' },
  { key: 'max_storage_mb', label: 'Storage (MB)' },
] as const

const PLAN_ACCENTS = ['', 'accent', 'purple', 'teal']
const accentFor = (i: number) => PLAN_ACCENTS[i % PLAN_ACCENTS.length]

// ── Limits editing ─────────────────────────────────────────────────────────

const editingLimits = ref<string | null>(null)
// Strings, not numbers: an empty field must be distinguishable from 0, because
// blank means "unlimited" and 0 means "none allowed" — genuinely different
// statements, and a numeric input collapses them.
const draft = ref<Record<string, string>>({})

const startEdit = (plan: PlatformPlan) => {
  draft.value = {
    name: plan.name,
    description: plan.description ?? '',
    price: (plan.price_cents / 100).toString(),
  }
  for (const f of LIMIT_FIELDS) {
    const value = (plan as unknown as Record<string, number | null>)[f.key]
    draft.value[f.key] = value === null || value === undefined ? '' : String(value)
  }
  editingLimits.value = plan.code
}

const cancelEdit = () => { editingLimits.value = null; draft.value = {} }

const saveLimits = async (plan: PlatformPlan) => {
  busy.value = true
  try {
    const payload: Record<string, unknown> = {
      name: draft.value.name.trim(),
      description: draft.value.description.trim() || null,
      price_cents: Math.round(parseFloat(draft.value.price || '0') * 100),
    }
    for (const f of LIMIT_FIELDS) {
      const raw = (draft.value[f.key] ?? '').trim()
      // Explicit null tells the server "unlimited"; omitting the key would
      // instead mean "leave unchanged", which is not what a cleared field says.
      payload[f.key] = raw === '' ? null : Number(raw)
    }
    const result = await updatePlan(plan.code, payload)
    toast.success(result.message ?? 'Plan saved')
    cancelEdit()
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not save the plan'))
  } finally {
    busy.value = false
  }
}

const limitText = (plan: PlatformPlan, key: string) => {
  const value = (plan as unknown as Record<string, number | null>)[key]
  return value === null || value === undefined ? 'Unlimited' : num(value)
}

// ── Feature matrix editing ─────────────────────────────────────────────────

const editingFeatures = ref<string | null>(null)
const featureDraft = ref<Record<string, boolean>>({})
const pendingSave = ref<string | null>(null)

const startFeatureEdit = (planCode: string) => {
  const plan = matrix.value?.plans.find((p) => p.code === planCode)
  if (!plan) return
  featureDraft.value = { ...plan.features }
  editingFeatures.value = planCode
}

const cancelFeatureEdit = () => { editingFeatures.value = null; featureDraft.value = {} }

const affectedBy = computed(() => {
  const code = pendingSave.value
  return code ? plans.value.find((p) => p.code === code)?.tenant_count ?? 0 : 0
})

const removedFeatures = computed(() => {
  const code = pendingSave.value
  if (!code || !matrix.value) return []
  const current = matrix.value.plans.find((p) => p.code === code)
  if (!current) return []
  return matrix.value.features
    .filter((f) => current.features[f.key] && !featureDraft.value[f.key])
    .map((f) => f.label)
})

const confirmFeatureSave = async () => {
  const code = pendingSave.value
  if (!code) return
  busy.value = true
  try {
    const result = await setPlanFeatures(code, featureDraft.value)
    toast.success(result.message ?? 'Features saved')
    pendingSave.value = null
    cancelFeatureEdit()
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not save the feature set'))
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
          :class="accentFor(i)"
        >
          <div class="plan-top">
            <div>
              <span class="plan-kicker">{{ plan.code }}</span>
              <h2>
                {{ plan.price_cents ? money(plan.price_cents / 100).replace('.00', '') : '$0' }}
                <small>{{ plan.price_cents ? '/month' : ' forever' }}</small>
              </h2>
              <p>{{ plan.description || 'No description' }}</p>
            </div>
            <PfPill v-if="plan.is_default" tone="accent">Default</PfPill>
            <PfPill v-else-if="!plan.is_active" tone="neutral">Retired</PfPill>
          </div>

          <div class="plan-users">
            {{ num(plan.tenant_count) }}
            {{ plan.tenant_count === 1 ? 'workspace' : 'workspaces' }}
          </div>

          <ul>
            <li v-for="f in LIMIT_FIELDS" :key="f.key">
              <span>✓</span>{{ limitText(plan, f.key) }} {{ f.label.toLowerCase() }}
            </li>
          </ul>

          <button class="wide-button" @click="startEdit(plan)">Edit plan</button>
        </article>
      </section>

      <!-- Limits table ------------------------------------------------------->
      <section class="panel table-panel">
        <div class="table-toolbar">
          <div>
            <h2 class="section-title">Usage limits</h2>
            <p class="section-sub">
              Blank means unlimited. Zero means none allowed — a genuinely
              different statement, and both are enforced as written.
            </p>
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
              <tr>
                <td><strong>Price / month</strong></td>
                <td v-for="p in plans" :key="p.code" class="num">
                  {{ p.price_cents ? money(p.price_cents / 100) : 'Free' }}
                </td>
              </tr>
              <tr v-for="f in LIMIT_FIELDS" :key="f.key">
                <td><strong>{{ f.label }}</strong></td>
                <td v-for="p in plans" :key="p.code" class="num">{{ limitText(p, f.key) }}</td>
              </tr>
              <tr>
                <td><strong>Workspaces on this plan</strong></td>
                <td v-for="p in plans" :key="p.code" class="num">{{ num(p.tenant_count) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Feature matrix ----------------------------------------------------->
      <section class="panel table-panel">
        <div class="table-toolbar">
          <div>
            <h2 class="section-title">Feature availability</h2>
            <p class="section-sub">
              Every switch here is enforced by real code — the path is named under
              each capability, so nothing in this table is decorative.
            </p>
          </div>
          <div class="toolbar-actions">
            <template v-if="editingFeatures">
              <span class="editing-label">Editing {{ editingFeatures }}</span>
              <button class="select-button" @click="cancelFeatureEdit">Cancel</button>
              <button class="primary-button" @click="pendingSave = editingFeatures">
                Review &amp; save
              </button>
            </template>
            <template v-else>
              <label class="filter-select">
                <span>Edit</span>
                <select
                  :value="''"
                  aria-label="Choose a plan to edit"
                  @change="startFeatureEdit(($event.target as HTMLSelectElement).value)"
                >
                  <option value="" disabled>Choose a plan…</option>
                  <option v-for="p in matrix.plans" :key="p.code" :value="p.code">{{ p.name }}</option>
                </select>
              </label>
            </template>
          </div>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Capability</th>
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
                    :class="{ 'editing-cell': editingFeatures === p.code }"
                  >
                    <button
                      v-if="editingFeatures === p.code"
                      class="feature-access-toggle"
                      :class="{ on: featureDraft[f.key] }"
                      role="switch"
                      :aria-checked="!!featureDraft[f.key]"
                      @click="featureDraft[f.key] = !featureDraft[f.key]"
                    >
                      <i />
                      <span>{{ featureDraft[f.key] ? 'Included' : 'No' }}</span>
                    </button>
                    <span v-else-if="!p.configured" class="feature-yes muted">✓ (unset)</span>
                    <span v-else-if="p.features[f.key]" class="feature-yes">✓ Included</span>
                    <span v-else class="feature-no">— Not included</span>
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
            @click="saveLimits(plans.find((p) => p.code === editingLimits)!)"
          >{{ busy ? 'Saving…' : 'Save plan' }}</button>
        </div>
      </aside>
    </div>

    <!-- Feature save confirmation --------------------------------------------->
    <div v-if="pendingSave" class="pf-overlay center" @mousedown.self="pendingSave = null">
      <section class="pf-modal" role="dialog" aria-modal="true">
        <div class="pf-modal-head">
          <div>
            <span>Applies immediately</span>
            <h2>Save feature changes to {{ pendingSave }}?</h2>
          </div>
          <button class="pf-close" aria-label="Close" @click="pendingSave = null">×</button>
        </div>

        <div class="pf-modal-body">
          <div class="note-box" :class="removedFeatures.length ? 'danger' : 'accent'">
            <strong>
              {{ num(affectedBy) }} workspace{{ affectedBy === 1 ? '' : 's' }} on this plan
            </strong>
            <span v-if="removedFeatures.length">
              Losing access to {{ removedFeatures.join(', ') }} the moment this is
              saved. There is no grace period — the gate reads this table on the
              next request. Any workspace you have given an explicit override
              keeps its exception.
            </span>
            <span v-else>
              Gaining access as soon as this is saved. Nothing is being taken away.
            </span>
          </div>
        </div>

        <div class="pf-modal-footer">
          <button class="select-button" @click="pendingSave = null">Back to editing</button>
          <button
            :class="removedFeatures.length ? 'danger-button' : 'primary-button'"
            :disabled="busy"
            @click="confirmFeatureSave"
          >{{ busy ? 'Saving…' : 'Save and apply' }}</button>
        </div>
      </section>
    </div>
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
