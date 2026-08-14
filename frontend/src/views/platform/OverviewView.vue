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
import { useRouter } from 'vue-router'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfMetric from '@/components/platform/ui/PfMetric.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfDonut from '@/components/platform/ui/PfDonut.vue'
import PfBars from '@/components/platform/ui/PfBars.vue'
import { getOverview, type Overview } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { compact, money, money0, num, date, initials } from '@/utils/platformFormat'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const data = ref<Overview | null>(null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await getOverview()
  } catch (e) {
    error.value = extractApiError(e, 'Could not load the platform overview')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const mrr = computed(() => (data.value ? data.value.revenue.mrr_cents / 100 : 0))

const greeting = computed(() => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
})

// Only periods that were actually recorded become bars. A month with no
// snapshot is not zero revenue — it is a month before anything was written
// down, and drawing it as zero would show a collapse that never happened.
const revenueBars = computed(() =>
  (data.value?.revenue_history ?? [])
    .filter((p) => p.recorded && p.mrr_cents !== null)
    .map((p) => ({ label: monthLabel(p.period), value: (p.mrr_cents as number) / 100 })),
)

const missingMonths = computed(
  () => (data.value?.revenue_history ?? []).filter((p) => !p.recorded).length,
)

const usageBars = computed(() =>
  (data.value?.usage_history ?? []).map((p) => ({
    label: monthLabel(p.period),
    value: p.ai_messages,
  })),
)

const monthLabel = (period: string) => {
  const [y, m] = period.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'short' })
}

// Colours come from the token set so the donut follows the theme rather than
// pinning its own palette.
const PLAN_COLORS = [
  'var(--accent-ink)', 'var(--c-purple)', 'var(--c-teal)',
  'var(--c-coral)', 'var(--muted2)',
]

const planSlices = computed(() =>
  (data.value?.revenue.by_plan ?? []).map((p, i) => ({
    label: p.name,
    value: p.tenants,
    color: PLAN_COLORS[i % PLAN_COLORS.length],
  })),
)

const openTenant = (id: string) => router.push(`/platform/organizations/${id}`)
</script>

<template>
  <PfPage
    :title="`${greeting}`"
    description="What is happening across the platform today."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="select-button" @click="load">Refresh</button>
      <RouterLink to="/platform/organizations" class="primary-button">＋ Add organization</RouterLink>
    </template>

    <template v-if="data">
      <section class="metrics-grid">
        <PfMetric
          label="Organizations"
          :value="num(data.organizations.total)"
          :delta="data.organizations.new_this_month ? `+${data.organizations.new_this_month} this month` : 'No new signups'"
          :delta-tone="data.organizations.new_this_month ? 'success' : 'neutral'"
          icon="org"
        />
        <PfMetric
          label="Users"
          :value="num(data.users)"
          :delta="`${num(data.agents)} AI agents`"
          icon="people"
          tone="teal"
        />
        <PfMetric
          label="Recurring revenue"
          :value="money0(mrr)"
          :delta="`${data.revenue.paying_tenants} paying`"
          :delta-tone="data.revenue.paying_tenants ? 'success' : 'neutral'"
          icon="dollar"
          tone="purple"
        />
        <PfMetric
          label="AI replies this month"
          :value="compact(data.usage.ai_messages)"
          :delta="`${compact(data.usage.conversations)} conversations`"
          icon="message"
          tone="coral"
        />
      </section>

      <!-- Said plainly rather than left for someone to work out from a chart
           that looks lower than they expected. -->
      <div v-if="!data.revenue.paying_tenants" class="pf-banner info">
        Every workspace is on a free plan, so recurring revenue is
        {{ money(0) }}. Set a price under Plans &amp; Limits, or move a customer
        to a paid plan, and this figure starts tracking it.
      </div>

      <section class="dashboard-grid">
        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Recurring revenue</h2>
              <p>Plan price × active workspaces, recorded at the end of each month</p>
            </div>
            <RouterLink to="/platform/billing" class="text-button">Billing →</RouterLink>
          </div>

          <div class="revenue-total">
            <strong>{{ money(mrr) }}</strong>
            <PfPill tone="neutral">per month</PfPill>
          </div>

          <PfBars v-if="revenueBars.length" :bars="revenueBars" :format="money0" />
          <div v-else class="empty-state">
            <strong>No history yet</strong>
            <span>This month's figure is being recorded now. The chart fills in as months pass.</span>
          </div>

          <p v-if="revenueBars.length && missingMonths" class="chart-note">
            {{ missingMonths }} earlier
            {{ missingMonths === 1 ? 'month is' : 'months are' }} not shown — revenue
            was not being recorded then, and reconstructing it from today's prices
            would show a figure that never happened.
          </p>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Plan mix</h2>
              <p>Active workspaces by plan</p>
            </div>
          </div>
          <PfDonut
            v-if="planSlices.length"
            :slices="planSlices"
            :total="data.revenue.active_tenants"
            caption="active"
          />
          <div v-else class="empty-state">
            <strong>No active workspaces</strong>
            <span>Add a customer to see the mix.</span>
          </div>
        </article>
      </section>

      <section class="dashboard-grid lower-grid">
        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Recent organizations</h2>
              <p>Newest customer workspaces</p>
            </div>
            <RouterLink to="/platform/organizations" class="text-button">View all →</RouterLink>
          </div>

          <div v-if="data.recent_organizations.length" class="compact-list">
            <button
              v-for="org in data.recent_organizations"
              :key="org.id"
              class="compact-row"
              @click="openTenant(org.id)"
            >
              <span class="org-avatar">{{ initials(org.name) }}</span>
              <span class="grow">
                <strong>{{ org.name }}</strong>
                <small>{{ org.domain }} · joined {{ date(org.created_at) }}</small>
              </span>
              <PfPill :tone="org.is_active ? 'success' : 'danger'">
                {{ org.is_active ? 'Active' : 'Suspended' }}
              </PfPill>
              <strong class="plan-name">{{ org.plan_code || '—' }}</strong>
              <span class="row-arrow">›</span>
            </button>
          </div>
          <div v-else class="empty-state">
            <strong>No organizations yet</strong>
            <span>The first customer workspace will appear here.</span>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>AI replies</h2>
              <p>Metered volume across all workspaces</p>
            </div>
          </div>
          <PfBars v-if="usageBars.some((b) => b.value)" :bars="usageBars" :format="compact" />
          <div v-else class="empty-state">
            <strong>No AI replies recorded</strong>
            <span>Volume appears here once agents start answering.</span>
          </div>
          <div class="usage-note">
            <span class="live-dot" />
            <span>Metering is live — every AI reply is counted as it is sent</span>
          </div>
        </article>
      </section>
    </template>
  </PfPage>
</template>

<style scoped>
.chart-note {
  margin: 12px 0 0;
  font-size: 11px;
  color: var(--muted2);
  line-height: 1.55;
}

.plan-name {
  min-width: 52px;
  font-size: 11px;
  text-align: center;
  text-transform: capitalize;
  color: var(--text3);
}

/* RouterLink styled as a button needs the text decoration removed and the
   flex centring the real <button> rules already provide. */
a.primary-button,
a.text-button { text-decoration: none; }
</style>
