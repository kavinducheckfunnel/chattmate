<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Sales, subscriptions, usage and the AI operating cost behind them.

Ported from the designer's reference (app/page.tsx, Billing) panel for panel.
Every figure is derived from our own plans, organizations and usage counters
rather than from a payment provider — which is what makes the page honest on a
deployment with no processor connected, and keeps revenue consistent with the
same plan prices the quota service enforces.

The one thing it cannot know is whether money arrived. Payment status is
reported as "Unbilled" rather than guessed at.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import { getPlatformBilling, type BillingOverview } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<BillingOverview | null>(null)
const period = ref('')

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await getPlatformBilling(period.value || undefined)
    period.value = data.value.period
  } catch (e) {
    error.value = extractApiError(e, 'Could not load billing')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const t = computed(() => data.value?.totals)
const money = (cents: number | null | undefined) =>
  `$${((cents ?? 0) / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** Selectable periods, newest first, labelled as months. */
const periods = computed(() => (data.value?.monthly ?? []).map((m) => m.period).reverse())
const monthLabel = (p: string) => {
  const [y, mo] = p.split('-').map(Number)
  return new Date(Date.UTC(y, mo - 1, 1))
    .toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' })
}

// ── Revenue trend ───────────────────────────────────────────────────────────
//
// Bars are scaled against the largest value present, not a fixed ceiling, so a
// month is readable whatever the absolute numbers are.
const trend = computed(() => data.value?.monthly ?? [])
const trendMax = computed(() =>
  Math.max(1, ...trend.value.map((m) => Math.max(m.revenue_cents ?? 0, m.ai_cost_cents))),
)
const barHeight = (v: number | null) => `${Math.max(2, ((v ?? 0) / trendMax.value) * 100)}%`

// ── Plan mix donut ──────────────────────────────────────────────────────────
//
// Built as a conic-gradient rather than SVG: the reference does the same, and a
// gradient needs no viewBox arithmetic to stay circular at any size.
const MIX_COLORS = ['var(--muted)', 'var(--accent-solid)', 'var(--bg-deep)', 'var(--c-info)']
const mixRows = computed(() =>
  (data.value?.by_plan ?? []).filter((p) => p.customers > 0),
)
const donutGradient = computed(() => {
  const total = t.value?.customers || 1
  let at = 0
  const stops = mixRows.value.map((row, i) => {
    const from = (at / total) * 360
    at += row.customers
    const to = (at / total) * 360
    return `${MIX_COLORS[i % MIX_COLORS.length]} ${from}deg ${to}deg`
  })
  return `conic-gradient(${stops.join(',') || 'var(--o08) 0deg 360deg'})`
})

const gaugeGradient = computed(() => {
  const pct = Math.min(100, t.value?.reserve_usage_rate ?? 0)
  return `conic-gradient(var(--accent-solid) 0 ${pct * 3.6}deg, var(--o08) ${pct * 3.6}deg 360deg)`
})

const usagePct = (used: number, allowance: number | null) =>
  allowance ? Math.min(100, Math.round((used / allowance) * 100)) : null

const exportCsv = () => {
  const d = data.value
  if (!d) return
  const rows = [['Organization', 'Domain', 'Plan', 'Monthly revenue', 'Messages', 'Allowance', 'Est. AI cost', 'Status']]
  for (const s of d.subscriptions) {
    rows.push([s.organization, s.domain, s.plan, money(s.revenue_cents), String(s.used),
               s.allowance === null ? 'Unlimited' : String(s.allowance), money(s.ai_cost_cents), s.status])
  }
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `billing-${d.period}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <PfPage
    title="Billing &amp; subscriptions"
    description="Track recurring revenue, renewals and payment status."
    :loading="loading"
    :error="error"
  >
    <template v-if="data && t">
      <!-- Period bar ---------------------------------------------------------->
      <div class="billing-period-bar panel">
        <div>
          <strong>Sales &amp; billing overview</strong>
          <span>Revenue, subscriptions, usage and AI operating cost</span>
        </div>
        <div class="billing-period-controls">
          <label class="filter-select">
            <span>Period</span>
            <select v-model="period" aria-label="Billing period" @change="load">
              <option v-for="p in periods" :key="p" :value="p">{{ monthLabel(p) }}</option>
            </select>
          </label>
        </div>
      </div>

      <!-- Finance overview ---------------------------------------------------->
      <section class="billing-finance-overview">
        <article class="billing-primary-card">
          <span>Monthly recurring revenue</span>
          <strong>{{ money(t.revenue_cents) }}</strong>
          <small>{{ num(t.paid_customers) }} of {{ num(t.customers) }} organizations are paying</small>
          <div>
            <span><b>{{ num(t.paid_customers) }}</b> paying customers</span>
            <span><b>{{ money(t.average_revenue_cents) }}</b> average revenue</span>
            <span><b>{{ money(t.net_after_reserve_cents) }}</b> after API reserve</span>
          </div>
        </article>

        <article class="panel api-reserve-card">
          <div class="api-reserve-head">
            <div>
              <span>Recommended monthly API reserve</span>
              <strong>{{ money(t.api_reserve_cents) }}</strong>
            </div>
            <em>25% safety buffer</em>
          </div>
          <div class="api-reserve-progress">
            <i :style="{ width: `${Math.min(100, t.reserve_usage_rate)}%` }" />
          </div>
          <div class="api-reserve-values">
            <span>Estimated used <strong>{{ money(t.estimated_ai_cost_cents) }}</strong></span>
            <span>Reserve remaining <strong>{{ money(t.reserve_remaining_cents) }}</strong></span>
          </div>
          <p>
            Keep this aside from MRR for provider usage. Projected from message
            volume, not from an invoice — reconcile it against the real bill monthly.
          </p>
        </article>

        <article class="panel billing-quick-stats">
          <div><span>Total organizations</span><strong>{{ num(t.customers) }}</strong></div>
          <div><span>AI cost / paying customer</span><strong>{{ money(t.ai_cost_per_paying_customer_cents) }}</strong></div>
          <div>
            <span>AI spend share of MRR</span>
            <strong>{{ t.ai_spend_share === null ? '—' : `${t.ai_spend_share}%` }}</strong>
          </div>
          <div>
            <span>Outstanding payments</span>
            <!-- No processor is connected, so nothing is known to be owed. -->
            <strong>Not tracked</strong>
          </div>
        </article>
      </section>

      <!-- Charts -------------------------------------------------------------->
      <section class="billing-chart-grid">
        <article class="panel revenue-trend-card">
          <div class="billing-chart-heading">
            <div><h2>Revenue trend</h2><p>MRR and estimated AI spend over six months</p></div>
            <div class="chart-keys">
              <span><i class="revenue-key" />Revenue</span>
              <span><i class="api-key" />AI cost</span>
            </div>
          </div>
          <div class="revenue-chart">
            <div class="revenue-bars">
              <div v-for="m in trend" :key="m.period" class="revenue-month">
                <div class="bar-value">{{ m.revenue_cents === null ? '—' : money(m.revenue_cents) }}</div>
                <div class="bar-track">
                  <i class="revenue-bar" :style="{ height: barHeight(m.revenue_cents) }" />
                  <i class="api-cost-mark" :style="{ height: barHeight(m.ai_cost_cents) }" />
                </div>
                <span>{{ monthLabel(m.period).slice(0, 3) }}</span>
              </div>
            </div>
          </div>
          <div class="trend-footer">
            <span><strong>{{ num(t.used_messages) }}</strong> messages this period</span>
            <span>
              <strong>{{ t.ai_spend_share === null ? '—' : `${t.ai_spend_share}%` }}</strong>
              AI cost as share of MRR
            </span>
          </div>
          <!-- Said plainly rather than drawn as five zero-height bars. -->
          <p v-if="trend.filter((m) => m.revenue_cents !== null).length < 2" class="chart-note">
            Only the current period has a revenue figure. Earlier months show
            message volume and its projected cost, which is what was recorded.
          </p>
        </article>

        <article class="panel plan-mix-card">
          <div class="billing-chart-heading">
            <div><h2>Customer plan mix</h2><p>All {{ num(t.customers) }} organizations</p></div>
          </div>
          <div class="plan-donut-wrap">
            <div class="plan-donut" :style="{ background: donutGradient }">
              <div><strong>{{ num(t.customers) }}</strong><span>customers</span></div>
            </div>
            <div class="plan-donut-legend">
              <div v-for="(row, i) in mixRows" :key="row.code">
                <span>
                  <i class="mix-dot" :style="{ background: MIX_COLORS[i % MIX_COLORS.length] }" />
                  {{ row.plan }}
                </span>
                <strong>
                  {{ num(row.customers) }}
                  <small>{{ Math.round((row.customers / (t.customers || 1)) * 100) }}%</small>
                </strong>
              </div>
            </div>
          </div>
          <div class="paid-conversion">
            <span>Paid conversion</span>
            <strong>{{ t.paid_conversion }}%</strong>
            <div><i :style="{ width: `${t.paid_conversion}%` }" /></div>
          </div>
        </article>

        <article class="panel cost-monitor-card">
          <div class="billing-chart-heading">
            <div><h2>AI cost monitor</h2><p>Estimated provider spend versus reserved budget</p></div>
          </div>
          <div class="cost-gauge" :style="{ background: gaugeGradient }">
            <div>
              <strong>{{ Math.round(t.reserve_usage_rate) }}%</strong>
              <span>of reserve</span>
            </div>
          </div>
          <div class="provider-cost-list">
            <div><span><i class="deepseek-dot" />Text messages</span><strong>{{ money(data.providers.text_cost_cents) }}</strong></div>
            <div><span><i class="gemini-dot" />Image requests</span><strong>{{ money(data.providers.image_cost_cents) }}</strong></div>
            <div class="provider-total"><span>Total estimated</span><strong>{{ money(t.estimated_ai_cost_cents) }}</strong></div>
          </div>
          <div class="reserve-status">
            <span class="live-dot" />
            <span>
              {{ t.reserve_remaining_cents >= 0
                ? 'API reserve is sufficient for current usage'
                : 'Projected spend exceeds the reserve' }}
            </span>
          </div>
        </article>
      </section>

      <!-- Plan performance + allocation --------------------------------------->
      <section class="billing-business-grid">
        <article class="panel plan-sales-card">
          <div class="panel-heading">
            <div><h2>Plan performance</h2><p>Sales, included message capacity and estimated AI spend by plan</p></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>Plan</th><th>Customers</th><th>MRR</th><th>Messages used</th><th>Usage</th><th>Est. AI cost</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in data.by_plan" :key="row.code">
                  <td><span class="plan-badge" :class="row.code">{{ row.plan }}</span></td>
                  <td><strong>{{ num(row.customers) }}</strong></td>
                  <td><strong>{{ money(row.revenue_cents) }}</strong></td>
                  <td>
                    {{ num(row.used) }}
                    <template v-if="row.allowance !== null"> / {{ num(row.allowance) }}</template>
                  </td>
                  <td>
                    <div v-if="usagePct(row.used, row.allowance) !== null" class="billing-usage-cell">
                      <div><i :style="{ width: `${usagePct(row.used, row.allowance)}%` }" /></div>
                      <span>{{ usagePct(row.used, row.allowance) }}%</span>
                    </div>
                    <span v-else class="muted-cell">No limit</span>
                  </td>
                  <td><strong>{{ money(row.ai_cost_cents) }}</strong></td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td><strong>Total</strong></td>
                  <td><strong>{{ num(t.customers) }}</strong></td>
                  <td><strong>{{ money(t.revenue_cents) }}</strong></td>
                  <td><strong>{{ num(t.used_messages) }} / {{ num(t.allocated_messages) }}</strong></td>
                  <td><strong>{{ t.usage_rate === null ? '—' : `${t.usage_rate}%` }}</strong></td>
                  <td><strong>{{ money(t.estimated_ai_cost_cents) }}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </article>

        <article class="panel profitability-card">
          <div class="panel-heading">
            <div><h2>Monthly revenue allocation</h2><p>How much remains after reserving API funds</p></div>
          </div>
          <div class="profit-amount">
            <span>Revenue after API reserve</span>
            <strong>{{ money(t.net_after_reserve_cents) }}</strong>
            <small>
              {{ t.margin_after_reserve === null ? '—' : `${t.margin_after_reserve}%` }}
              of MRR remains before other operating costs
            </small>
          </div>
          <div class="profit-breakdown">
            <div><span>Monthly recurring revenue</span><strong>{{ money(t.revenue_cents) }}</strong></div>
            <div><span>Recommended API reserve</span><strong>− {{ money(t.api_reserve_cents) }}</strong></div>
            <div><span>Current estimated API usage</span><strong>{{ money(t.estimated_ai_cost_cents) }}</strong></div>
            <div><span>Unused reserve buffer</span><strong>{{ money(t.reserve_remaining_cents) }}</strong></div>
          </div>
          <div class="cost-assumption-note">
            <strong>Not deducted here</strong>
            <span>
              Server, payment gateway fees, taxes, backups and support labour must
              be entered separately before treating this as final profit.
            </span>
          </div>
        </article>
      </section>

      <!-- Capacity + health --------------------------------------------------->
      <section class="billing-usage-overview">
        <article class="panel">
          <div class="panel-heading">
            <div><h2>Message capacity</h2><p>Included plan allowance compared with actual consumption</p></div>
            <strong>{{ t.usage_rate === null ? '—' : `${t.usage_rate}% used` }}</strong>
          </div>
          <div class="capacity-bar"><i :style="{ width: `${Math.min(100, t.usage_rate ?? 0)}%` }" /></div>
          <div class="capacity-values">
            <span><strong>{{ num(t.used_messages) }}</strong> messages used</span>
            <span><strong>{{ num(Math.max(0, t.allocated_messages - t.used_messages)) }}</strong> remaining</span>
            <span><strong>{{ num(t.allocated_messages) }}</strong> allocated</span>
          </div>
          <p v-if="t.has_unlimited_plans" class="chart-note">
            Workspaces on an unlimited plan are not counted here — they have no
            allowance to measure against.
          </p>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div><h2>Sales health</h2><p>Key subscription signals for {{ monthLabel(data.period) }}</p></div>
          </div>
          <div class="sales-health-list">
            <div><span>Active paid subscriptions</span><strong>{{ num(t.paid_customers) }}</strong></div>
            <div><span>Paid conversion</span><strong class="positive">{{ t.paid_conversion }}%</strong></div>
            <div><span>Image requests</span><strong>{{ num(t.image_requests) }}</strong></div>
            <div><span>Payments connected</span><strong>{{ data.payments_connected ? 'Yes' : 'No' }}</strong></div>
          </div>
        </article>
      </section>

      <!-- Subscriptions ------------------------------------------------------->
      <section class="panel table-panel billing-records sales-subscriptions">
        <div class="billing-table-header">
          <div>
            <h2>Customer subscriptions</h2>
            <p>Revenue and consumption for individual organizations</p>
          </div>
          <div class="toolbar-actions">
            <button class="select-button" @click="exportCsv">Export CSV</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Organization</th><th>Plan</th><th>Monthly revenue</th>
                <th>Messages</th><th>Est. AI cost</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in data.subscriptions" :key="s.organization_id">
                <td>
                  <div class="org-cell">
                    <span class="org-avatar">{{ initials(s.organization) }}</span>
                    <span><strong>{{ s.organization }}</strong><small>{{ s.domain }}</small></span>
                  </div>
                </td>
                <td><PfPill tone="info">{{ s.plan }}</PfPill></td>
                <td><strong>{{ money(s.revenue_cents) }}</strong></td>
                <td>
                  {{ num(s.used) }}
                  <template v-if="s.allowance !== null"> / {{ num(s.allowance) }}</template>
                </td>
                <td>{{ money(s.ai_cost_cents) }}</td>
                <td><PfPill :tone="s.status === 'Free' ? 'neutral' : 'warning'">{{ s.status }}</PfPill></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="billing-table-footer">
          <span>Showing {{ num(data.subscriptions.length) }} of {{ num(t.customers) }} organizations</span>
        </div>
      </section>

      <!-- Stated once, plainly, rather than implied by empty columns. -->
      <div v-if="!data.payments_connected" class="pf-banner info">
        No payment processor is connected, so nothing here is a record of money
        received. Revenue is plan price × active organizations, and AI cost is
        projected from message volume.
      </div>
    </template>
  </PfPage>
</template>

<style scoped>
.chart-note { margin: 12px 0 0; font-size: 11px; color: var(--muted); line-height: 1.55; }
.muted-cell { color: var(--muted); }
</style>
