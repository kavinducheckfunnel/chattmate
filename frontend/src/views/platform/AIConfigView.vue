<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Which AI provider and model each workspace runs on.

This deployment is bring-your-own-key: each customer configures their own
provider, and the platform holds no shared model account. That shapes the page
— there is nothing central to route or rate-limit here, so the useful questions
are "who has not set one up" and "who is on what", both of which this answers.

API keys are never fetched, not even masked. A masked key still identifies the
provider account a customer pays for.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfMetric from '@/components/platform/ui/PfMetric.vue'
import { getAIConfiguration, type AIConfigOverview } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, date, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<AIConfigOverview | null>(null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await getAIConfiguration()
  } catch (e) {
    error.value = extractApiError(e, 'Could not load AI configuration')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const totalWorkspaces = computed(
  () => (data.value?.workspaces.length ?? 0) + (data.value?.unconfigured.length ?? 0),
)

const activeCount = computed(
  () => (data.value?.workspaces ?? []).filter((w) => w.is_active).length,
)

const search = ref('')
const visible = computed(() => {
  const q = search.value.trim().toLowerCase()
  const rows = data.value?.workspaces ?? []
  if (!q) return rows
  return rows.filter((w) =>
    `${w.organization_name} ${w.domain} ${w.model_type} ${w.model_name}`.toLowerCase().includes(q),
  )
})
</script>

<template>
  <PfPage
    title="AI configuration"
    description="The model behind every workspace, and who has not set one up yet."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="select-button" @click="load">Refresh</button>
    </template>

    <template v-if="data">
      <section class="metrics-grid">
        <PfMetric
          label="Workspaces with a model"
          :value="num(data.workspaces.length)"
          :delta="`of ${num(totalWorkspaces)} total`"
          icon="aiconfig"
        />
        <PfMetric
          label="Active configurations"
          :value="num(activeCount)"
          :delta="activeCount === data.workspaces.length ? 'All enabled' : `${data.workspaces.length - activeCount} disabled`"
          :delta-tone="activeCount === data.workspaces.length ? 'success' : 'warning'"
          icon="check"
          tone="teal"
        />
        <PfMetric
          label="Distinct models"
          :value="num(data.by_model.length)"
          :delta="data.by_model[0]?.model ?? 'None in use'"
          icon="agents"
          tone="purple"
        />
        <PfMetric
          label="Not configured"
          :value="num(data.unconfigured.length)"
          :delta="data.unconfigured.length ? 'Their agents cannot answer' : 'Everyone is set up'"
          :delta-tone="data.unconfigured.length ? 'danger' : 'success'"
          icon="alert"
          tone="coral"
        />
      </section>

      <!-- The single most actionable thing on the page, so it comes first. -->
      <section v-if="data.unconfigured.length" class="panel">
        <div class="panel-heading">
          <div>
            <h2>Workspaces without a model</h2>
            <p>
              An agent with no AI configuration cannot answer anything. This is
              the commonest reason a new customer reports that "the bot does not
              work".
            </p>
          </div>
          <PfPill tone="danger">{{ data.unconfigured.length }} to fix</PfPill>
        </div>

        <div class="compact-list">
          <RouterLink
            v-for="o in data.unconfigured"
            :key="o.organization_id"
            :to="`/platform/organizations/${o.organization_id}`"
            class="compact-row"
          >
            <span class="org-avatar">{{ initials(o.organization_name) }}</span>
            <span class="grow">
              <strong>{{ o.organization_name }}</strong>
              <small>{{ o.domain }} · {{ o.plan_code || 'no plan' }}</small>
            </span>
            <PfPill tone="warning">No model set</PfPill>
            <span class="row-arrow">›</span>
          </RouterLink>
        </div>
      </section>

      <section class="dashboard-grid">
        <article class="panel table-panel">
          <div class="table-toolbar">
            <label class="search-box">
              <span>⌕</span>
              <input v-model="search" placeholder="Search workspace or model…" />
            </label>
          </div>

          <div v-if="visible.length" class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Workspace</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="w in visible" :key="w.organization_id">
                  <td>
                    <RouterLink :to="`/platform/organizations/${w.organization_id}`" class="org-link">
                      <div class="org-cell">
                        <span class="org-avatar">{{ initials(w.organization_name) }}</span>
                        <span>
                          <strong>{{ w.organization_name }}</strong>
                          <small>{{ w.domain }}</small>
                        </span>
                      </div>
                    </RouterLink>
                  </td>
                  <td><strong class="capitalize">{{ w.model_type || '—' }}</strong></td>
                  <td><code class="model">{{ w.model_name }}</code></td>
                  <td>
                    <PfPill :tone="w.is_active ? 'success' : 'neutral'">
                      {{ w.is_active ? 'Active' : 'Disabled' }}
                    </PfPill>
                  </td>
                  <td>{{ date(w.updated_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-table-state">
            <strong>No configurations</strong>
            <span v-if="search">Nothing matches that search.</span>
            <span v-else>No workspace has set up a model yet.</span>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Models in use</h2>
              <p>Across all workspaces</p>
            </div>
          </div>

          <div v-if="data.by_model.length" class="model-list">
            <div v-for="m in data.by_model" :key="m.model">
              <span class="model-name">{{ m.model }}</span>
              <div class="model-bar">
                <i :style="{ width: `${(m.workspaces / (data.by_model[0]?.workspaces || 1)) * 100}%` }" />
              </div>
              <strong>{{ m.workspaces }}</strong>
            </div>
          </div>
          <div v-else class="empty-state">
            <strong>No models configured</strong>
            <span>Nothing to summarise yet.</span>
          </div>

          <div class="note-box byok">
            <strong>Bring your own key</strong>
            <span>
              Every workspace uses its own provider account, so their AI spend is
              billed to them directly and there is no shared platform key to
              route, cap or exhaust. Keys are encrypted at rest and are never
              returned to this console — not even masked.
            </span>
          </div>

          <div v-if="!data.platform_default.configured" class="note-box">
            <strong>No platform-wide default</strong>
            <span>{{ data.platform_default.note }}</span>
          </div>
        </article>
      </section>
    </template>
  </PfPage>
</template>

<style scoped>
.compact-row { text-decoration: none; }
.org-link { text-decoration: none; color: inherit; display: block; }

.model {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text3);
  background: var(--o05);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}

.capitalize { text-transform: capitalize; }

.model-list { display: flex; flex-direction: column; gap: 12px; margin: 16px 0; }
.model-list > div {
  display: grid;
  grid-template-columns: 1fr 70px auto;
  align-items: center;
  gap: 10px;
}
.model-name {
  font-size: 11px;
  color: var(--text3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-bar { height: 6px; background: var(--o08); border-radius: var(--radius-pill); overflow: hidden; }
.model-bar > i { display: block; height: 100%; background: var(--accent-ink); border-radius: var(--radius-pill); }
.model-list strong { font-variant-numeric: tabular-nums; font-size: var(--text-xs); }

.note-box.byok { border-color: var(--accent-border); background: var(--accent-bg-06); }
.note-box + .note-box { margin-top: 10px; }
</style>
