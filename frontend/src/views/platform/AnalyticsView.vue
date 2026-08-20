<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Conversation performance across every workspace.

Where a figure has no data behind it — satisfaction with no ratings yet — the
page says so instead of showing a zero. Zero CSAT and "nobody has rated
anything" look identical on a dashboard and mean opposite things.
-->

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfDonut from '@/components/platform/ui/PfDonut.vue'
import PfBars from '@/components/platform/ui/PfBars.vue'
import { getPlatformAnalytics, getPlatformPlans, type PlatformAnalytics, type PlatformPlan } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, compact, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<PlatformAnalytics | null>(null)
const range = ref<'7d' | '30d' | '90d'>('30d')

// Scope filters. Applied server-side rather than in the browser: filtering a
// page of results would silently narrow only what had already been fetched,
// and every total on the page would then describe a different set.
const planFilter = ref('')
const channelFilter = ref('')
const plans = ref<PlatformPlan[]>([])

const hasFilters = computed(() => !!planFilter.value || !!channelFilter.value)
const clearFilters = () => { planFilter.value = ''; channelFilter.value = '' }

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await getPlatformAnalytics(range.value, {
      plan_code: planFilter.value || undefined,
      channel: channelFilter.value || undefined,
    })
  } catch (e) {
    error.value = extractApiError(e, 'Could not load analytics')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    plans.value = await getPlatformPlans()
  } catch {
    plans.value = []
  }
})

watch([range, planFilter, channelFilter], load)

// Channel options come from what the data actually contains, so the dropdown
// can never offer a channel no workspace uses. Kept from the unfiltered load
// so selecting one does not collapse the list to just that channel.
const knownChannels = ref<string[]>([])
watch(data, (d) => {
  if (d && !hasFilters.value) knownChannels.value = d.channels.map((c) => c.channel)
}, { immediate: true })

const rangeLabel = computed(
  () => ({ '7d': 'last 7 days', '30d': 'last 30 days', '90d': 'last 90 days' })[range.value],
)

const resolutionRate = computed(() => {
  const c = data.value?.conversations
  if (!c || !c.total) return null
  return Math.round((c.ai_only / c.total) * 100)
})

// Daily counts, bucketed into the number of bars the chart can show legibly.
// 90 individual bars in a 600px panel is a smear, not a chart.
const volumeBars = computed(() => {
  const daily = data.value?.conversations.daily ?? []
  if (!daily.length) return []
  const buckets = Math.min(12, daily.length)
  const size = Math.ceil(daily.length / buckets)
  const out: { label: string; value: number }[] = []
  for (let i = 0; i < daily.length; i += size) {
    const slice = daily.slice(i, i + size)
    out.push({
      label: new Date(slice[0].date).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
      value: slice.reduce((t, d) => t + d.count, 0),
    })
  }
  return out
})

const volumeStats = computed(() => {
  const bars = volumeBars.value
  if (!bars.length) return null
  const total = bars.reduce((t, b) => t + b.value, 0)
  return {
    total,
    average: Math.round(total / bars.length),
    peak: Math.max(...bars.map((b) => b.value)),
  }
})

const CHANNEL_COLORS = ['var(--accent-ink)', 'var(--c-teal)', 'var(--c-purple)', 'var(--c-coral)', 'var(--muted2)']

const channelSlices = computed(() =>
  (data.value?.channels ?? []).map((c, i) => ({
    label: c.channel,
    value: c.count,
    color: CHANNEL_COLORS[i % CHANNEL_COLORS.length],
  })),
)

const outcomeSlices = computed(() => {
  const c = data.value?.conversations
  if (!c || !c.total) return []
  return [
    { label: 'AI handled', value: c.ai_only, color: 'var(--accent-ink)' },
    { label: 'Human handover', value: c.handovers, color: 'var(--c-purple)' },
  ].filter((s) => s.value > 0)
})
</script>

<template>
  <PfPage
    title="Platform analytics"
    :description="`Conversation performance across every workspace, ${rangeLabel}.`"
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <label class="filter-select">
        <span>Range</span>
        <select v-model="range" aria-label="Date range">
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
        </select>
      </label>
      <button class="select-button" @click="load">Refresh</button>
    </template>

    <template v-if="data">
      <section class="panel filter-panel">
        <div class="filter-summary">
          <div>
            <span>Reporting scope</span>
            <strong>{{ planFilter || channelFilter ? 'Filtered' : 'Entire platform' }}</strong>
            <small>
              {{ rangeLabel }}
              · {{ planFilter ? (plans.find((p) => p.code === planFilter)?.name ?? planFilter) : 'all plans' }}
              · {{ channelFilter || 'all channels' }}
            </small>
          </div>
          <span class="live-status"><i class="live-dot" /> {{ num(data.active_organizations) }} workspace(s) active in this window</span>
        </div>
        <div class="filter-controls">
          <label class="filter-select">
            <span>Plan</span>
            <select v-model="planFilter" aria-label="Filter by plan">
              <option value="">All plans</option>
              <option v-for="p in plans" :key="p.code" :value="p.code">{{ p.name }}</option>
            </select>
          </label>
          <label class="filter-select">
            <span>Channel</span>
            <select v-model="channelFilter" aria-label="Filter by channel">
              <option value="">All channels</option>
              <option v-for="c in knownChannels" :key="c" :value="c">{{ c }}</option>
            </select>
          </label>
          <button v-if="hasFilters" class="clear-filter-button" @click="clearFilters">Clear filters</button>
        </div>
      </section>

      <!-- The reference's own KPI row: label, figure, note. Not PfMetric —
           that renders an icon/copy/pill trio into .metric-card's three-column
           grid, and on this page the note landed in the pill column and sat on
           top of the label. -->
      <section class="analytics-kpis">
        <article>
          <span>Conversations</span>
          <strong>{{ compact(data.conversations.total) }}</strong>
          <small>{{ compact(data.conversations.messages) }} messages exchanged</small>
        </article>
        <article>
          <span>AI-resolved</span>
          <strong>{{ compact(data.conversations.ai_only) }}</strong>
          <small>
            <b v-if="resolutionRate !== null" class="positive">{{ resolutionRate }}%</b>
            {{ resolutionRate === null ? 'No conversations yet' : 'resolution rate' }}
          </small>
        </article>
        <article>
          <span>Human handovers</span>
          <strong>{{ compact(data.conversations.handovers) }}</strong>
          <small>
            {{ data.conversations.total
              ? `${Math.round((data.conversations.handovers / data.conversations.total) * 100)}% of conversations`
              : 'None' }}
          </small>
        </article>
        <article>
          <span>Active workspaces</span>
          <strong>{{ num(data.active_organizations) }}</strong>
          <small>had a conversation in this window</small>
        </article>
        <article>
          <span>Customer satisfaction</span>
          <strong>{{ data.satisfaction.average === null ? '—' : data.satisfaction.average }}</strong>
          <small>
            {{ data.satisfaction.responses
              ? `from ${num(data.satisfaction.responses)} ratings`
              : 'No ratings yet' }}
          </small>
        </article>
      </section>

      <div v-if="!data.conversations.total" class="pf-banner info">
        No conversations in the {{ rangeLabel }}. Widen the range, or check that
        a workspace has a live agent connected to a channel.
      </div>

      <section class="dashboard-grid">
        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Conversation volume</h2>
              <p>Started per period over the {{ rangeLabel }}</p>
            </div>
          </div>
          <PfBars v-if="volumeBars.length" :bars="volumeBars" :format="compact" />
          <div v-else class="empty-state">
            <strong>Nothing to plot</strong>
            <span>No conversations were started in this range.</span>
          </div>
          <div v-if="volumeStats" class="chart-footer">
            <span><strong>{{ num(volumeStats.total) }}</strong> total</span>
            <span><strong>{{ num(volumeStats.average) }}</strong> average per bar</span>
            <span><strong>{{ num(volumeStats.peak) }}</strong> peak</span>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Channel mix</h2>
              <p>Where conversations arrive from</p>
            </div>
          </div>
          <PfDonut
            v-if="channelSlices.length"
            :slices="channelSlices"
            :total="data.conversations.total"
            caption="conversations"
          />
          <div v-else class="empty-state">
            <strong>No channel data</strong>
            <span>Connect a channel to see the split.</span>
          </div>
        </article>
      </section>

      <section class="dashboard-grid lower-grid">
        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Busiest workspaces</h2>
              <p>Ranked by conversations in the {{ rangeLabel }}</p>
            </div>
            <RouterLink to="/platform/organizations" class="text-button">All organizations →</RouterLink>
          </div>

          <div v-if="data.top_organizations.length" class="compact-list">
            <RouterLink
              v-for="(org, i) in data.top_organizations"
              :key="org.id"
              :to="`/platform/organizations/${org.id}`"
              class="compact-row leader"
            >
              <em class="rank">{{ i + 1 }}</em>
              <span class="org-avatar">{{ initials(org.name) }}</span>
              <span class="grow">
                <strong>{{ org.name }}</strong>
                <small>{{ org.domain }} · {{ org.plan_code || 'no plan' }}</small>
              </span>
              <strong class="count">{{ num(org.conversations) }}</strong>
              <span class="row-arrow">›</span>
            </RouterLink>
          </div>
          <div v-else class="empty-state">
            <strong>No activity</strong>
            <span>No workspace had a conversation in this range.</span>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Resolution</h2>
              <p>Who finished the conversation</p>
            </div>
          </div>
          <PfDonut
            v-if="outcomeSlices.length"
            :slices="outcomeSlices"
            :total="data.conversations.total"
            caption="total"
          />
          <div v-else class="empty-state">
            <strong>No outcomes yet</strong>
            <span>This fills in as conversations complete.</span>
          </div>

          <div class="stat-strip">
            <div>
              <span>Knowledge sources</span>
              <strong>{{ num(data.knowledge.sources) }}</strong>
            </div>
            <div>
              <span>Messages exchanged</span>
              <strong>{{ compact(data.conversations.messages) }}</strong>
            </div>
          </div>
        </article>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>Plan utilization</h2>
            <p>
              AI replies consumed this month against each plan's ceiling, summed
              across the workspaces on it
            </p>
          </div>
          <PfPill v-if="data.plan_usage.some((r) => (r.percent ?? 0) >= 80)" tone="warning">
            {{ data.plan_usage.filter((r) => (r.percent ?? 0) >= 80).length }} near limit
          </PfPill>
        </div>

        <div v-if="data.plan_usage.length" class="usage-rows">
          <div v-for="row in data.plan_usage" :key="row.plan_code" class="usage-row">
            <span class="usage-label">
              <strong>{{ row.plan_name }}</strong>
              <small>
                {{ num(row.used) }} /
                {{ row.allowance === null ? 'unlimited' : num(row.allowance) }} replies
                · {{ row.tenants }} workspace{{ row.tenants === 1 ? '' : 's' }}
              </small>
            </span>
            <div class="usage-track" :class="(row.percent ?? 0) >= 100 ? 'danger' : (row.percent ?? 0) >= 80 ? 'warn' : ''">
              <i :style="{ width: `${row.percent ?? 0}%` }" />
            </div>
            <!-- Unlimited reports no percentage rather than 0%: a plan with no
                 ceiling is not a plan sitting unused. -->
            <strong class="usage-pct">{{ row.percent === null ? '—' : `${row.percent}%` }}</strong>
          </div>
        </div>
        <div v-else class="empty-state">
          <strong>No plans in use</strong>
          <span>Assign a workspace to a plan to see consumption.</span>
        </div>
      </section>

      <section v-if="Object.keys(data.conversations.by_status).length" class="panel">
        <div class="panel-heading">
          <div>
            <h2>Conversation status</h2>
            <p>Current state of every conversation started in this range</p>
          </div>
        </div>
        <div class="status-row">
          <div v-for="(count, status) in data.conversations.by_status" :key="status">
            <PfPill :tone="status === 'closed' ? 'success' : status === 'open' ? 'info' : 'neutral'">
              {{ status }}
            </PfPill>
            <strong>{{ num(count) }}</strong>
          </div>
        </div>
      </section>
    </template>
  </PfPage>
</template>

<style scoped>
.compact-row.leader { text-decoration: none; }

.rank {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted2);
  width: 16px;
  flex: 0 0 16px;
  text-align: center;
}

.count { font-variant-numeric: tabular-nums; font-size: var(--text-sm); }

.stat-strip {
  display: flex;
  gap: 20px;
  border-top: 1px solid var(--o08);
  padding-top: 14px;
  margin-top: 14px;
}
.stat-strip > div { display: flex; flex-direction: column; gap: 2px; }
.stat-strip span { font-size: 10px; color: var(--muted2); }
.stat-strip strong {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-variant-numeric: tabular-nums;
}

.filter-panel { margin-bottom: 16px; }

.filter-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--o08);
}
.filter-summary > div { display: flex; flex-direction: column; gap: 2px; }
.filter-summary span:first-child { font-size: 10px; color: var(--muted2); }
.filter-summary strong { font-family: var(--font-display); font-size: var(--text-base); }
.filter-summary small { font-size: 11px; color: var(--muted2); }

.live-status { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--muted); }

.filter-controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding-top: 14px; }

.metrics-grid.five { grid-template-columns: repeat(5, minmax(0, 1fr)); }
@media (max-width: 1180px) { .metrics-grid.five { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px)  { .metrics-grid.five { grid-template-columns: minmax(0, 1fr); } }

.chart-footer {
  display: flex;
  gap: 22px;
  flex-wrap: wrap;
  border-top: 1px solid var(--o08);
  margin-top: 14px;
  padding-top: 12px;
  font-size: 11px;
  color: var(--muted2);
}
.chart-footer strong { color: var(--text2); font-variant-numeric: tabular-nums; }

.usage-rows { display: flex; flex-direction: column; gap: 14px; margin-top: 16px; }

.usage-row {
  display: grid;
  grid-template-columns: minmax(150px, 1.2fr) minmax(0, 2fr) 46px;
  gap: 14px;
  align-items: center;
}
.usage-label { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.usage-label strong { font-size: var(--text-xs); }
.usage-label small { font-size: 10px; color: var(--muted2); }

.usage-track { height: 8px; background: var(--o08); border-radius: var(--radius-pill); overflow: hidden; }
.usage-track > i { display: block; height: 100%; background: var(--accent-ink); border-radius: var(--radius-pill); }
.usage-track.warn > i { background: var(--c-warn); }
.usage-track.danger > i { background: var(--c-danger); }

.usage-pct { font-size: var(--text-xs); text-align: right; font-variant-numeric: tabular-nums; }

@media (max-width: 640px) {
  .usage-row { grid-template-columns: minmax(0, 1fr) 46px; }
  .usage-track { grid-column: 1 / -1; }
}

.status-row { display: flex; gap: 26px; flex-wrap: wrap; margin-top: 16px; }
.status-row > div { display: flex; align-items: center; gap: 9px; }
.status-row strong { font-variant-numeric: tabular-nums; font-size: var(--text-sm); }

a.text-button { text-decoration: none; }
</style>
