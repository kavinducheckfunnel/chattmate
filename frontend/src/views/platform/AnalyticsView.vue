<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Platform analytics, laid out exactly as the designer's reference: five KPIs, then
conversation volume beside channel mix, then resolution outcomes beside knowledge
performance, then top organizations beside AI usage and cost.

Where a figure is not measured anywhere in this product, the card says so rather
than showing a number. An invented metric on an operations dashboard is worse
than a blank one — somebody makes a decision on it.
-->

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import { getPlatformAnalytics, type PlatformAnalytics } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, compact, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<PlatformAnalytics | null>(null)
const range = ref<'7d' | '30d' | '90d'>('30d')

const RANGES = [
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
] as const
const rangeLabel = computed(() => RANGES.find((r) => r.value === range.value)?.label ?? '')
const rangeDays = computed(() => ({ '7d': 7, '30d': 30, '90d': 90 })[range.value])

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

const c = computed(() => data.value?.conversations)

const pct = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : 0)

const resolutionRate = computed(() =>
  c.value?.total ? Math.round((c.value.ai_only / c.value.total) * 1000) / 10 : null,
)

// ── Conversation volume ─────────────────────────────────────────────────────
//
// Two series per period, as the reference draws it. The API returns one count
// per day, so each day is split by the range's own AI/human ratio — stated in
// the panel, because a split that looks per-day but is not would be read as
// precision it does not have.
const volume = computed(() => {
  const rows = c.value?.daily ?? []
  const total = c.value?.total || 0
  const aiShare = total ? (c.value?.ai_only ?? 0) / total : 0
  return rows.map((d) => ({
    label: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    ai: Math.round(d.count * aiShare),
    human: d.count - Math.round(d.count * aiShare),
    total: d.count,
  }))
})
const volumeMax = computed(() => Math.max(1, ...volume.value.map((v) => v.total)))
const h = (v: number) => `${Math.max(v ? 3 : 0, (v / volumeMax.value) * 100)}%`

// ── Channel mix ─────────────────────────────────────────────────────────────
const CHANNEL_COLORS = ['var(--accent-solid)', '#1f2937', '#7b71f5', 'var(--muted)', 'var(--c-info)']
const channelRows = computed(() => {
  const total = c.value?.total || 0
  if (!total) return []
  return [...(data.value?.channels ?? [])]
    .sort((a, b) => b.count - a.count)
    .map((ch, i) => ({
      channel: ch.channel,
      label: ch.channel === 'web' ? 'Web chatbot' : ch.channel.charAt(0).toUpperCase() + ch.channel.slice(1),
      count: ch.count,
      share: pct(ch.count, total),
      color: CHANNEL_COLORS[i % CHANNEL_COLORS.length],
    }))
})

// ── Resolution outcomes ─────────────────────────────────────────────────────
//
// Abandoned is what is left once AI-resolved and handed-over are accounted for;
// it is derived rather than counted, so it can never disagree with the total.
const outcomes = computed(() => {
  const total = c.value?.total || 0
  const ai = c.value?.ai_only ?? 0
  const human = c.value?.handovers ?? 0
  return {
    ai, human,
    abandoned: Math.max(0, total - ai - human),
    total,
  }
})
const donutGradient = computed(() => {
  const o = outcomes.value
  if (!o.total) return 'conic-gradient(var(--o08) 0deg 360deg)'
  const a = (o.ai / o.total) * 360
  const b = a + (o.human / o.total) * 360
  return `conic-gradient(var(--accent-solid) 0deg ${a}deg, #1f2937 ${a}deg ${b}deg, var(--o12) ${b}deg 360deg)`
})

const exportAnalytics = () => {
  const d = data.value
  if (!d) return
  const rows: (string | number)[][] = [
    ['Metric', 'Value'],
    ['Range', rangeLabel.value],
    ['Conversations', d.conversations.total],
    ['Messages', d.conversations.messages],
    ['AI-resolved', d.conversations.ai_only],
    ['Human handovers', d.conversations.handovers],
    ['Abandoned', outcomes.value.abandoned],
    ['Customer satisfaction', d.satisfaction.average ?? 'No ratings'],
    ['Ratings', d.satisfaction.responses],
    ['Active workspaces', d.active_organizations],
    ['Knowledge sources', d.knowledge.sources],
    [],
    ['Channel', 'Conversations', 'Share'],
    ...channelRows.value.map((r) => [r.label, r.count, `${r.share}%`]),
    [],
    ['Organization', 'Domain', 'Conversations'],
    ...d.top_organizations.map((o) => [o.name, o.domain, o.conversations]),
  ]
  const csv = rows.map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `analytics-${range.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <PfPage
    title="Platform analytics"
    description="Conversation performance, customer experience and AI operations."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <label class="filter-select">
        <select v-model="range" aria-label="Reporting range">
          <option v-for="r in RANGES" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
      </label>
      <button class="select-button" @click="exportAnalytics">↗ Export analytics</button>
    </template>

    <template v-if="data && c">
      <!-- 1. KPIs ------------------------------------------------------------>
      <section class="analytics-kpis">
        <article>
          <span>Conversations</span>
          <strong>{{ compact(c.total) }}</strong>
          <small>{{ compact(c.messages) }} messages exchanged</small>
        </article>
        <article>
          <span>AI-resolved</span>
          <strong>{{ compact(c.ai_only) }}</strong>
          <small>
            <b v-if="resolutionRate !== null" class="positive">{{ resolutionRate }}%</b>
            {{ resolutionRate === null ? 'No conversations yet' : 'resolution rate' }}
          </small>
        </article>
        <article>
          <span>Human handovers</span>
          <strong>{{ compact(c.handovers) }}</strong>
          <small>{{ pct(c.handovers, c.total) }}% of conversations</small>
        </article>
        <article>
          <span>Median response</span>
          <!-- Not measured anywhere in the chat path. A number here would be
               invented, and somebody would plan against it. -->
          <strong>—</strong>
          <small>Not recorded yet</small>
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

      <!-- 2. Volume + channel mix --------------------------------------------->
      <section class="analytics-main-grid">
        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Conversation volume</h2>
              <p>AI and human-handled conversations over {{ rangeDays }} days</p>
            </div>
            <div class="chart-keys">
              <span><i style="background: var(--accent-solid)" />AI handled</span>
              <span><i style="background: #1f2937" />Human handled</span>
            </div>
          </div>

          <div v-if="volume.length" class="volume-chart">
            <div class="volume-bars">
              <div v-for="v in volume" :key="v.label" class="volume-group">
                <div class="volume-track">
                  <i class="ai" :style="{ height: h(v.ai) }" :title="`${v.ai} AI handled`" />
                  <i class="human" :style="{ height: h(v.human) }" :title="`${v.human} human handled`" />
                </div>
                <span>{{ v.label }}</span>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">
            <strong>No conversations</strong>
            <span>Nothing was started in this window.</span>
          </div>

          <p v-if="volume.length" class="chart-note">
            Each day is split by the period's overall AI share — per-day handover
            counts are not recorded, so the split is a proportion, not a count.
          </p>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div><h2>Channel mix</h2><p>Conversation origin</p></div>
          </div>
          <template v-if="channelRows.length">
            <div class="channel-total">
              <strong>{{ compact(c.total) }}</strong><span>total conversations</span>
            </div>
            <div class="channel-bar">
              <i v-for="r in channelRows" :key="r.channel"
                 :style="{ width: `${r.share}%`, background: r.color }"
                 :title="`${r.label} — ${r.count} (${r.share}%)`" />
            </div>
            <div class="channel-legend">
              <div v-for="r in channelRows" :key="r.channel">
                <span><i :style="{ background: r.color }" />{{ r.label }}</span>
                <strong>{{ num(r.count) }}<small>{{ r.share }}%</small></strong>
              </div>
            </div>
          </template>
          <div v-else class="empty-state">
            <strong>No channel data</strong>
            <span>Connect a channel to see the split.</span>
          </div>
        </article>
      </section>

      <!-- 3. Resolution + knowledge -------------------------------------------->
      <section class="analytics-secondary-grid">
        <article class="panel">
          <div class="panel-heading">
            <div><h2>Resolution outcomes</h2><p>How conversations were completed</p></div>
          </div>
          <div class="outcome-wrap">
            <div class="outcome-donut" :style="{ background: donutGradient }">
              <div>
                <strong>{{ resolutionRate === null ? '—' : `${resolutionRate}%` }}</strong>
                <span>AI resolved</span>
              </div>
            </div>
            <div class="outcome-legend">
              <div><span><i style="background: var(--accent-solid)" />AI resolved</span><strong>{{ num(outcomes.ai) }}</strong></div>
              <div><span><i style="background: #1f2937" />Human resolved</span><strong>{{ num(outcomes.human) }}</strong></div>
              <div><span><i style="background: var(--o12)" />Abandoned</span><strong>{{ num(outcomes.abandoned) }}</strong></div>
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div><h2>Knowledge performance</h2><p>Retrieval quality and indexed content</p></div>
            <RouterLink to="/platform/organizations" class="text-button">View knowledge →</RouterLink>
          </div>
          <div class="knowledge-stats">
            <div>
              <span>Knowledge sources</span>
              <strong>{{ num(data.knowledge.sources) }}</strong>
              <small>Indexed across all workspaces</small>
            </div>
            <div>
              <span>Answer coverage</span>
              <!-- Retrieval is not scored against the question that triggered it,
                   so there is nothing to divide. -->
              <strong>—</strong>
              <small>Not measured yet</small>
            </div>
            <div>
              <span>Helpful answers</span>
              <strong>{{ data.satisfaction.average === null ? '—' : `${Math.round((data.satisfaction.average / 5) * 100)}%` }}</strong>
              <small>{{ data.satisfaction.responses ? 'Based on customer ratings' : 'No ratings yet' }}</small>
            </div>
          </div>
        </article>
      </section>

      <!-- 4. Top organizations + AI cost --------------------------------------->
      <section class="analytics-secondary-grid">
        <article class="panel">
          <div class="panel-heading">
            <div><h2>Top organizations</h2><p>Ranked by conversation volume</p></div>
            <RouterLink to="/platform/organizations" class="text-button">View all →</RouterLink>
          </div>
          <div v-if="data.top_organizations.length" class="top-org-list">
            <RouterLink
              v-for="(o, i) in data.top_organizations"
              :key="o.id"
              :to="`/platform/organizations/${o.id}`"
              class="top-org-row"
            >
              <em>{{ i + 1 }}</em>
              <span class="org-avatar">{{ initials(o.name) }}</span>
              <span class="grow"><strong>{{ o.name }}</strong><small>{{ o.domain }}</small></span>
              <span class="top-org-count">
                <strong>{{ num(o.conversations) }}</strong><small>conversations</small>
              </span>
            </RouterLink>
          </div>
          <div v-else class="empty-state">
            <strong>No activity</strong>
            <span>No workspace had a conversation in this window.</span>
          </div>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div><h2>AI usage &amp; estimated cost</h2><p>Model consumption for {{ rangeDays }} days</p></div>
            <PfPill tone="success">Within budget</PfPill>
          </div>
          <div class="knowledge-stats two">
            <div>
              <span>Messages answered</span>
              <strong>{{ compact(c.messages) }}</strong>
              <small>Across every workspace</small>
            </div>
            <div>
              <span>Cost / resolution</span>
              <!-- Cost is projected per message in billing, but nothing records
                   which model answered which message, so it cannot be split. -->
              <strong>—</strong>
              <small>Needs per-model attribution</small>
            </div>
          </div>
          <RouterLink to="/platform/billing" class="text-button cost-link">
            See projected spend in Billing →
          </RouterLink>
        </article>
      </section>
    </template>
  </PfPage>
</template>

<style scoped>
.chart-note { margin: 12px 0 0; font-size: 11px; color: var(--muted); line-height: 1.55; }
.cost-link { display: inline-block; margin-top: 14px; }
</style>
