<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Recurring revenue as the plan catalog currently stands.

Every figure here is real and derived from live data: plan price × active
workspaces on that plan. What it is *not* is money collected — no card has been
charged, because payment collection needs a Stripe account this deployment does
not have yet. The page says which of the two it is showing rather than letting
a number labelled "revenue" imply cash in the bank.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfMetric from '@/components/platform/ui/PfMetric.vue'
import PfBars from '@/components/platform/ui/PfBars.vue'
import { getOverview, type Overview } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, money, money0, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<Overview | null>(null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    data.value = await getOverview()
  } catch (e) {
    error.value = extractApiError(e, 'Could not load billing figures')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const revenue = computed(() => data.value?.revenue ?? null)
const mrr = computed(() => (revenue.value ? revenue.value.mrr_cents / 100 : 0))
const arr = computed(() => mrr.value * 12)
const arpa = computed(() => (revenue.value ? revenue.value.arpa_cents / 100 : 0))

const monthLabel = (period: string) => {
  const [y, m] = period.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'short' })
}

const historyBars = computed(() =>
  (data.value?.revenue_history ?? [])
    .filter((p) => p.recorded && p.mrr_cents !== null)
    .map((p) => ({ label: monthLabel(p.period), value: (p.mrr_cents as number) / 100 })),
)

const missingMonths = computed(
  () => (data.value?.revenue_history ?? []).filter((p) => !p.recorded).length,
)

const freeTenants = computed(() =>
  (revenue.value?.by_plan ?? [])
    .filter((p) => p.price_cents === 0)
    .reduce((t, p) => t + p.tenants, 0),
)
</script>

<template>
  <PfPage
    title="Billing"
    description="Recurring revenue by plan, and what is still needed to collect it."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="select-button" @click="load">Refresh</button>
    </template>

    <template v-if="revenue && data">
      <!-- Stated before any number, so nothing on this page can be misread. -->
      <div class="pf-banner warn">
        <span>
          <strong>No payments are being collected.</strong>
          The figures below are what the plan catalog says these workspaces
          <em>should</em> be billed — real numbers from live data, but not money
          received. Connecting Stripe is what turns them into charges; see the
          card at the bottom for exactly what that needs.
        </span>
      </div>

      <section class="metrics-grid">
        <PfMetric
          label="Monthly recurring revenue"
          :value="money0(mrr)"
          :delta="`${num(revenue.paying_tenants)} paying`"
          :delta-tone="revenue.paying_tenants ? 'success' : 'neutral'"
          icon="dollar"
        />
        <PfMetric
          label="Annual run rate"
          :value="money0(arr)"
          delta="MRR × 12"
          icon="trend"
          tone="teal"
        />
        <PfMetric
          label="Average per paying workspace"
          :value="revenue.paying_tenants ? money(arpa) : '—'"
          :delta="revenue.paying_tenants ? 'Across paid plans' : 'No paid workspaces'"
          icon="billing"
          tone="purple"
        />
        <PfMetric
          label="On a free plan"
          :value="num(freeTenants)"
          :delta="revenue.active_tenants ? `${Math.round((freeTenants / revenue.active_tenants) * 100)}% of active` : '—'"
          icon="people"
          tone="coral"
        />
      </section>

      <section class="dashboard-grid">
        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Revenue by plan</h2>
              <p>Plan price × active workspaces on that plan</p>
            </div>
          </div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Plan</th>
                  <th>Price</th>
                  <th>Workspaces</th>
                  <th>Monthly total</th>
                  <th>Share</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in revenue.by_plan" :key="p.code">
                  <td>
                    <strong>{{ p.name }}</strong>
                    <small class="table-subtext">{{ p.code }}</small>
                  </td>
                  <td class="num">{{ p.price_cents ? money(p.price_cents / 100) : 'Free' }}</td>
                  <td class="num">{{ num(p.tenants) }}</td>
                  <td class="num"><strong>{{ money(p.mrr_cents / 100) }}</strong></td>
                  <td>
                    <div class="share">
                      <div class="share-bar">
                        <i :style="{ width: `${revenue.mrr_cents ? (p.mrr_cents / revenue.mrr_cents) * 100 : 0}%` }" />
                      </div>
                      <span>{{ revenue.mrr_cents ? Math.round((p.mrr_cents / revenue.mrr_cents) * 100) : 0 }}%</span>
                    </div>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td><strong>Total</strong></td>
                  <td />
                  <td class="num"><strong>{{ num(revenue.active_tenants) }}</strong></td>
                  <td class="num"><strong>{{ money(mrr) }}</strong></td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>

          <RouterLink to="/platform/plans" class="text-button spaced">
            Change prices under Plans &amp; Limits →
          </RouterLink>
        </article>

        <article class="panel">
          <div class="panel-heading">
            <div>
              <h2>Recorded history</h2>
              <p>Month-end snapshots</p>
            </div>
          </div>

          <PfBars v-if="historyBars.length" :bars="historyBars" :format="money0" />
          <div v-else class="empty-state">
            <strong>No history yet</strong>
            <span>This month's figure is being recorded. The chart fills in as months pass.</span>
          </div>

          <p v-if="missingMonths" class="chart-note">
            {{ missingMonths }} earlier
            {{ missingMonths === 1 ? 'month has' : 'months have' }} no snapshot.
            They are left out rather than reconstructed: recomputing them from
            today's prices would show a figure that never happened.
          </p>
        </article>
      </section>

      <!-- What is missing, stated concretely enough to act on. -->
      <section class="panel setup-card">
        <div class="setup-head">
          <span class="setup-icon">◇</span>
          <div>
            <h2>Collecting payments</h2>
            <p>
              Everything upstream of a charge is already built and running:
              plans, prices, per-workspace metering and quota enforcement. What
              is missing is the payment processor.
            </p>
          </div>
          <PfPill tone="warning">Not connected</PfPill>
        </div>

        <div class="setup-grid">
          <div class="setup-done">
            <h3>Already working</h3>
            <ul>
              <li><span>✓</span>Plan catalog with editable prices and limits</li>
              <li><span>✓</span>Usage metered per workspace, per month</li>
              <li><span>✓</span>Quotas enforced — over-limit requests return 402</li>
              <li><span>✓</span>Plan changes apply live, with an audit entry</li>
              <li><span>✓</span>Revenue recorded monthly so history accumulates</li>
            </ul>
          </div>

          <div class="setup-todo">
            <h3>Needed to charge cards</h3>
            <ul>
              <li>
                <span>1</span>
                <div>
                  <strong>A Stripe account</strong>
                  <small>Test mode is enough to build and verify the whole flow.</small>
                </div>
              </li>
              <li>
                <span>2</span>
                <div>
                  <strong>Secret key and webhook signing secret</strong>
                  <small>
                    <code>sk_test_…</code> and <code>whsec_…</code>. They go into
                    the server's .env, never into this repository.
                  </small>
                </div>
              </li>
              <li>
                <span>3</span>
                <div>
                  <strong>A decision on proration</strong>
                  <small>
                    Whether a mid-month upgrade is charged immediately or at the
                    next renewal. It changes what the checkout does, so it is
                    worth deciding before rather than after.
                  </small>
                </div>
              </li>
            </ul>
          </div>
        </div>

        <div class="note-box">
          <strong>Why this is not stubbed out</strong>
          <span>
            A fake "Upgrade" button that silently changed a plan without taking
            payment would look finished and quietly give the product away. The
            plan can already be changed from the workspace page, which is honest
            about being a manual operator action.
          </span>
        </div>
      </section>
    </template>
  </PfPage>
</template>

<style scoped>
.share { display: flex; align-items: center; gap: 8px; min-width: 110px; }
.share-bar { flex: 1; height: 6px; background: var(--o08); border-radius: var(--radius-pill); overflow: hidden; }
.share-bar > i { display: block; height: 100%; background: var(--accent-ink); border-radius: var(--radius-pill); }
.share span { font-size: 10px; color: var(--muted2); font-variant-numeric: tabular-nums; }

.chart-note { margin: 12px 0 0; font-size: 11px; color: var(--muted2); line-height: 1.55; }

.spaced { display: inline-block; margin-top: 14px; text-decoration: none; }

.setup-card { margin-top: 16px; }

.setup-head { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 20px; }
.setup-head > div { flex: 1; min-width: 0; }
.setup-head h2 { font-family: var(--font-display); font-size: var(--text-lg); margin: 0; }
.setup-head p { margin: 5px 0 0; font-size: var(--text-xs); color: var(--muted2); line-height: 1.6; max-width: 68ch; }

.setup-icon {
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border-radius: var(--radius-chip);
  display: grid;
  place-items: center;
  background: var(--accent-bg-12);
  color: var(--accent-ink);
  font-size: 16px;
}

.setup-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  margin-bottom: 18px;
}

.setup-grid h3 {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--muted2);
  margin: 0 0 12px;
}

.setup-grid ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 11px; }

.setup-done li {
  display: flex;
  gap: 10px;
  font-size: var(--text-xs);
  color: var(--text3);
  line-height: 1.5;
}
.setup-done li > span { color: var(--c-positive); flex: 0 0 auto; }

.setup-todo li { display: flex; gap: 11px; }
.setup-todo li > span {
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--o08);
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 10px;
}
.setup-todo li > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.setup-todo strong { font-size: var(--text-xs); color: var(--text2); }
.setup-todo small { font-size: 11px; color: var(--muted2); line-height: 1.55; }
.setup-todo code {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--o05);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--text3);
}
</style>
