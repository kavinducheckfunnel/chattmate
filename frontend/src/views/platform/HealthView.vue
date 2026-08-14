<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Live status of the services this deployment depends on.

Every row is measured when the page loads. Nothing is cached and nothing is
averaged over a window this deployment does not keep — a health page showing a
comfortable "99.98% uptime" during an outage is the one moment it had a job to
do. What is shown is what a probe returned just now, and the latency is the
time that probe actually took.
-->

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import { getPlatformHealth, type PlatformHealth } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, dateTime } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const data = ref<PlatformHealth | null>(null)
const lastChecked = ref<Date | null>(null)

const load = async () => {
  error.value = ''
  try {
    data.value = await getPlatformHealth()
    lastChecked.value = new Date()
  } catch (e) {
    error.value = extractApiError(e, 'Could not reach the health endpoint')
  } finally {
    loading.value = false
  }
}

// Auto-refresh, because this is the page left open during an incident. Cleared
// on unmount so it does not keep polling from a route nobody is looking at.
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  load()
  timer = setInterval(load, 30_000)
})
onBeforeUnmount(() => clearInterval(timer))

const COUNT_LABELS: Record<string, string> = {
  organizations: 'Workspaces',
  users: 'Users',
  agents: 'AI agents',
  channels: 'Connected channels',
  conversations: 'Conversations',
  knowledge_sources: 'Knowledge sources',
}

const uptimeText = computed(() => {
  const s = data.value?.api_uptime_seconds ?? 0
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m}m`
  return `${m}m`
})

const headline = computed(() => {
  const s = data.value?.status
  if (s === 'operational') return 'All systems operational'
  if (s === 'degraded') return 'Some services are degraded'
  return 'Services are down'
})

const downCount = computed(
  () => (data.value?.services ?? []).filter((s) => s.status === 'down').length,
)
</script>

<template>
  <PfPage
    title="System health"
    description="Measured now, on every load — not averaged and not cached."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <span class="checked-note">
        {{ lastChecked ? `Checked ${dateTime(lastChecked.toISOString())}` : '' }}
      </span>
      <button class="select-button" @click="load">Check now</button>
    </template>

    <template v-if="data">
      <section class="panel banner" :class="data.status">
        <span class="banner-icon">
          {{ data.status === 'operational' ? '✓' : data.status === 'degraded' ? '!' : '✕' }}
        </span>
        <div>
          <h2>{{ headline }}</h2>
          <p>
            <template v-if="downCount">
              {{ downCount }} of {{ data.services.length }} checks failed. The detail
              is in the failing row below.
            </template>
            <template v-else>
              Every dependency answered. API process has been up {{ uptimeText }}.
            </template>
          </p>
        </div>
        <PfPill :tone="data.status === 'operational' ? 'success' : data.status === 'degraded' ? 'warning' : 'danger'">
          {{ data.status }}
        </PfPill>
      </section>

      <section class="service-grid">
        <article v-for="s in data.services" :key="s.name" class="panel service-card">
          <div class="service-head">
            <span class="service-dot" :class="s.status" />
            <h3>{{ s.name }}</h3>
            <PfPill :tone="s.status === 'operational' ? 'success' : 'danger'">
              {{ s.status === 'operational' ? 'OK' : 'Down' }}
            </PfPill>
          </div>
          <p class="service-detail">{{ s.detail }}</p>
          <dl>
            <div>
              <dt>Response</dt>
              <dd>{{ s.latency_ms }} ms</dd>
            </div>
          </dl>
        </article>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>Platform totals</h2>
            <p>Row counts across every workspace, at this moment</p>
          </div>
        </div>
        <div class="count-grid">
          <div v-for="(value, key) in data.counts" :key="key">
            <span>{{ COUNT_LABELS[key] ?? key }}</span>
            <strong>{{ num(value) }}</strong>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>What is not shown here</h2>
            <p>So the gaps are known rather than assumed</p>
          </div>
        </div>
        <ul class="honesty-list">
          <li>
            <strong>Uptime percentages.</strong> Nothing in this deployment records
            service availability over time, so any "99.9%" on this page would be a
            number someone made up. The API process uptime above is real because
            the process can measure itself.
          </li>
          <li>
            <strong>Incident history.</strong> There is no incident store yet.
            Operator actions are in the audit log; service outages are only in the
            container logs on the server.
          </li>
          <li>
            <strong>Off-site backup status.</strong> Backups are not configured —
            see Backups, which explains exactly what it needs.
          </li>
        </ul>
      </section>
    </template>
  </PfPage>
</template>

<style scoped>
.checked-note { font-size: 10px; color: var(--muted2); }

.banner {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.banner h2 { font-family: var(--font-display); font-size: var(--text-lg); margin: 0; }
.banner p { margin: 4px 0 0; font-size: var(--text-xs); color: var(--muted2); }
.banner > div { flex: 1; min-width: 0; }

.banner-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 17px;
}
.banner.operational .banner-icon {
  background: color-mix(in srgb, var(--c-positive) 16%, transparent);
  color: var(--c-positive);
}
.banner.degraded .banner-icon {
  background: color-mix(in srgb, var(--c-warn) 16%, transparent);
  color: var(--c-warn);
}
.banner.down .banner-icon { background: var(--coral-bg); color: var(--c-danger); }

.service-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.service-card { display: flex; flex-direction: column; gap: 10px; }
.service-head { display: flex; align-items: center; gap: 9px; }
.service-head h3 { flex: 1; min-width: 0; }

.service-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 auto;
  background: var(--c-positive);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-positive) 18%, transparent);
}
.service-dot.down {
  background: var(--c-danger);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-danger) 18%, transparent);
}

.service-detail {
  margin: 0;
  font-size: 11px;
  color: var(--muted2);
  line-height: 1.5;
  word-break: break-word;
}

.service-card dl { margin: 0; display: flex; gap: 20px; }
.service-card dl > div { display: flex; flex-direction: column; gap: 2px; }
.service-card dt { font-size: 9.5px; color: var(--muted2); text-transform: uppercase; letter-spacing: .06em; }
.service-card dd { margin: 0; font-size: var(--text-xs); color: var(--text2); font-variant-numeric: tabular-nums; }

.count-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
  margin-top: 16px;
}
.count-grid > div { display: flex; flex-direction: column; gap: 3px; }
.count-grid span { font-size: 10px; color: var(--muted2); }
.count-grid strong {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-variant-numeric: tabular-nums;
}

.honesty-list {
  margin: 16px 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.honesty-list li { font-size: var(--text-xs); color: var(--muted); line-height: 1.6; }
.honesty-list strong { color: var(--text2); }
</style>
