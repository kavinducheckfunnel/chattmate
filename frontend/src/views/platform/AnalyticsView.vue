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
import PfMetric from '@/components/platform/ui/PfMetric.vue'
import PfDonut from '@/components/platform/ui/PfDonut.vue'
import PfBars from '@/components/platform/ui/PfBars.vue'
import { getPlatformAnalytics, type PlatformAnalytics } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, compact, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<PlatformAnalytics | null>(null)
const range = ref<'7d' | '30d' | '90d'>('30d')

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await getPlatformAnalytics(range.value)
  } catch (e) {
    error.value = extractApiError(e, 'Could not load analytics')
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(range, load)

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
      <section class="metrics-grid">
        <PfMetric
          label="Conversations"
          :value="compact(data.conversations.total)"
          :delta="`${compact(data.conversations.messages)} messages`"
          icon="message"
        />
        <PfMetric
          label="AI handled alone"
          :value="resolutionRate === null ? '—' : `${resolutionRate}%`"
          :delta="resolutionRate === null ? 'No conversations yet' : `${compact(data.conversations.ai_only)} conversations`"
          :delta-tone="resolutionRate !== null && resolutionRate >= 70 ? 'success' : 'neutral'"
          icon="agents"
          tone="teal"
        />
        <PfMetric
          label="Human handovers"
          :value="compact(data.conversations.handovers)"
          :delta="data.conversations.total ? `${Math.round((data.conversations.handovers / data.conversations.total) * 100)}% of conversations` : 'None'"
          icon="humans"
          tone="purple"
        />
        <PfMetric
          label="Customer satisfaction"
          :value="data.satisfaction.average === null ? '—' : `${data.satisfaction.average} / 5`"
          :delta="data.satisfaction.responses ? `${num(data.satisfaction.responses)} ratings` : 'No ratings yet'"
          :delta-tone="data.satisfaction.average !== null && data.satisfaction.average >= 4 ? 'success' : 'neutral'"
          icon="trend"
          tone="coral"
        />
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

.status-row { display: flex; gap: 26px; flex-wrap: wrap; margin-top: 16px; }
.status-row > div { display: flex; align-items: center; gap: 9px; }
.status-row strong { font-variant-numeric: tabular-nums; font-size: var(--text-sm); }

a.text-button { text-decoration: none; }
</style>
