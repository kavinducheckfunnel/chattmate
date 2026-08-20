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
import PfRing from '@/components/platform/ui/PfRing.vue'
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

// Share of the allowance actually sold, or null where a plan has no ceiling —
// a percentage of unlimited is not a number, and drawing 0% would read as
// "nothing used" when the truth is "nothing to measure against".
const messagesPercent = computed(() => data.value?.allowances?.ai_messages.percent ?? null)
const imagesPercent = computed(() => data.value?.allowances?.image_requests.percent ?? null)

const uncappedNote = computed(() => {
  const n = data.value?.allowances?.ai_messages.uncapped_tenants ?? 0
  if (!n) return ''
  return `${n} workspace${n === 1 ? '' : 's'} on an unlimited plan ${n === 1 ? 'is' : 'are'} not counted here.`
})

const messagesDelta = computed(() => {
  const percent = messagesPercent.value
  if (percent === null) return `${compact(data.value?.usage.conversations ?? 0)} conversations`
  return `${percent}% of limit`
})

/** Downloads what is on screen as CSV, generated in the browser from the data
 *  already loaded — no endpoint, and nothing that can disagree with the page. */
const exportReport = () => {
  const d = data.value
  if (!d) return
  const rows: (string | number)[][] = [
    ['Metric', 'Value'],
    ['Period', d.period],
    ['Organizations', d.organizations.total],
    ['New this month', d.organizations.new_this_month],
    ['Active users', d.users],
    ['AI agents', d.agents],
    ['Monthly revenue', money(mrr.value)],
    ['Paying workspaces', d.revenue.paying_tenants],
    ['Conversations', d.usage.conversations],
    ['Messages used', d.usage.ai_messages],
    ['Messages allowance', d.allowances?.ai_messages.limit ?? 'Unlimited'],
    ['Image requests', d.allowances?.image_requests.used ?? 0],
    ['Image allowance', d.allowances?.image_requests.limit ?? 'Unlimited'],
  ]
  // Quote every field: organization names contain commas often enough that an
  // unquoted export silently shifts columns.
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `platform-overview-${d.period}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

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
      <button class="select-button" @click="exportReport">↗ Export report</button>
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
          label="Active users"
          :value="num(data.users)"
          :delta="`${num(data.agents)} AI agents`"
          icon="people"
          tone="teal"
        />
        <PfMetric
          label="Monthly revenue"
          :value="money0(mrr)"
          :delta="`${data.revenue.paying_tenants} paying`"
          :delta-tone="data.revenue.paying_tenants ? 'success' : 'neutral'"
          icon="dollar"
          tone="purple"
        />
        <PfMetric
          label="Messages used"
          :value="compact(data.usage.ai_messages)"
          :delta="messagesDelta"
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
              <h2>Revenue overview</h2>
              <p>Recurring revenue over the last 6 months</p>
            </div>
            <RouterLink to="/platform/billing" class="select-button">Last 6 months⌄</RouterLink>
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
              <h2>Plan distribution</h2>
              <p>Organizations by active plan</p>
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
              <p>Latest client workspaces added to the platform</p>
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

        <article class="panel usage-panel">
          <div class="panel-heading">
            <div>
              <h2>Platform usage</h2>
              <p>Current month consumption</p>
            </div>
          </div>
          <div class="ring-grid two-rings">
            <!-- A ring needs a ceiling to fill against. On an unlimited plan
                 there is none, so the count is shown instead of a fabricated
                 percentage. -->
            <PfRing
              :value="messagesPercent ?? 0"
              :label="messagesPercent === null ? 'Messages · no limit' : 'Messages'"
              color="var(--accent-solid)"
            />
            <PfRing
              :value="imagesPercent ?? 0"
              :label="imagesPercent === null ? 'Images · no limit' : 'Images'"
              color="#7b71f5"
            />
          </div>
          <!-- Named rather than folded into the percentage: a ring drawn over
               a partial set of tenants should say so. -->
          <div v-if="uncappedNote" class="chart-note">{{ uncappedNote }}
          </div>
          <div class="usage-note">
            <span class="live-dot" />
            <span>All usage services are reporting normally</span>
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
