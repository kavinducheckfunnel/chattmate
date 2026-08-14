<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Backup status.

Nothing on this page pretends. There is no off-site backup configured for this
deployment, so the page says that in the largest type on it rather than showing
a green tick and a list of invented recovery points. A backup page that lies is
worse than no backup page: it is the one screen someone checks before deciding
they are safe.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import { getPlatformHealth, type PlatformHealth } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const health = ref<PlatformHealth | null>(null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    health.value = await getPlatformHealth()
  } catch (e) {
    error.value = extractApiError(e, 'Could not read platform counts')
  } finally {
    loading.value = false
  }
}
onMounted(load)

// What would be lost. Concrete numbers, because "your data" is easy to shrug at
// and "1,284 conversations" is not.
const atRisk = computed(() => {
  const c = health.value?.counts ?? {}
  return [
    { label: 'Customer workspaces', value: c.organizations ?? 0 },
    { label: 'User accounts', value: c.users ?? 0 },
    { label: 'Conversations', value: c.conversations ?? 0 },
    { label: 'AI agents', value: c.agents ?? 0 },
    { label: 'Knowledge sources', value: c.knowledge_sources ?? 0 },
    { label: 'Connected channels', value: c.channels ?? 0 },
  ]
})
</script>

<template>
  <PfPage
    title="Backups &amp; recovery"
    description="What is protected, what is not, and what it would take to fix that."
    :loading="loading"
    :error="error"
  >
    <section class="panel status-card">
      <span class="status-icon">!</span>
      <div>
        <h2>No off-site backups are configured</h2>
        <p>
          Everything lives on a single VPS. If that machine's disk fails, is
          deleted, or the provider account is lost, every workspace below goes
          with it. There is no snapshot to restore from and no copy anywhere else.
        </p>
      </div>
      <PfPill tone="danger">Unprotected</PfPill>
    </section>

    <section class="panel">
      <div class="panel-heading">
        <div>
          <h2>What is currently at risk</h2>
          <p>Live counts from the database this page is reading</p>
        </div>
      </div>
      <div class="risk-grid">
        <div v-for="row in atRisk" :key="row.label">
          <span>{{ row.label }}</span>
          <strong>{{ num(row.value) }}</strong>
        </div>
      </div>
    </section>

    <section class="panel setup-card">
      <div class="setup-head">
        <span class="setup-icon">☁</span>
        <div>
          <h2>Turning this on</h2>
          <p>
            The work itself is roughly an hour: a nightly <code>pg_dump</code>
            plus the uploads directory, encrypted, pushed off the box, with a
            retention window and a restore test. It is blocked on one thing only
            — somewhere to put the files.
          </p>
        </div>
      </div>

      <div class="setup-grid">
        <div>
          <h3>Pick any one</h3>
          <ul class="options">
            <li>
              <strong>Backblaze B2</strong>
              <small>Cheapest for this size — around $1/month. S3-compatible.</small>
            </li>
            <li>
              <strong>Amazon S3</strong>
              <small>Most familiar. Use a bucket-scoped IAM key, not a root key.</small>
            </li>
            <li>
              <strong>DigitalOcean Spaces</strong>
              <small>Flat $5/month, S3-compatible, simple billing.</small>
            </li>
            <li>
              <strong>Hetzner Storage Box</strong>
              <small>Cheap SFTP if you would rather not use an S3 API at all.</small>
            </li>
          </ul>
        </div>

        <div>
          <h3>What to send over</h3>
          <ul class="creds">
            <li><span>1</span><div><strong>Endpoint / region</strong><small>e.g. <code>s3.us-west-002.backblazeb2.com</code></small></div></li>
            <li><span>2</span><div><strong>Bucket name</strong><small>Create it empty and private first.</small></div></li>
            <li><span>3</span><div><strong>Access key and secret</strong><small>Scoped to that one bucket, write-only if the provider allows it.</small></div></li>
          </ul>
          <div class="note-box">
            <strong>They go straight onto the server</strong>
            <span>
              Stored in the VPS <code>.env</code> at mode 600, gitignored, never
              committed — the same handling as the database and SMTP credentials
              already in use.
            </span>
          </div>
        </div>
      </div>

      <div class="plan-preview">
        <h3>What gets built once those exist</h3>
        <ol>
          <li>Nightly <code>pg_dump</code> of the full database, gzipped and encrypted at rest.</li>
          <li>The uploads directory — knowledge documents and chat attachments — in the same archive.</li>
          <li>Upload off-box, with the local temporary copy deleted afterwards.</li>
          <li>A retention window, so old snapshots are pruned rather than billed forever.</li>
          <li>A restore rehearsal into a scratch database, because an untested backup is a guess.</li>
          <li>This page rebuilt to show real recovery points, sizes and the last verified restore.</li>
        </ol>
      </div>

      <div class="note-box danger">
        <strong>Why there is no "Run backup now" button here yet</strong>
        <span>
          A button that produced a file on the same disk as the database would
          protect against nothing except an accidental <code>DELETE</code> — not
          against disk failure, not against losing the server, which are the
          cases that actually end a business. Shipping it would mean this page
          could show a green tick while the real risk was unchanged.
        </span>
      </div>
    </section>
  </PfPage>
</template>

<style scoped>
.status-card {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
  border-color: color-mix(in srgb, var(--error-color) 30%, transparent);
  background: linear-gradient(var(--error-bg), var(--error-bg)), var(--surface);
}
.status-card > div { flex: 1; min-width: 0; }
.status-card h2 { font-family: var(--font-display); font-size: var(--text-lg); margin: 0; }
.status-card p { margin: 6px 0 0; font-size: var(--text-xs); color: var(--muted); line-height: 1.65; max-width: 74ch; }

.status-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--error-color) 18%, transparent);
  color: var(--error-color);
  font-size: 19px;
  font-weight: var(--font-weight-bold);
}

.risk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 18px;
  margin-top: 16px;
}
.risk-grid > div { display: flex; flex-direction: column; gap: 3px; }
.risk-grid span { font-size: 10px; color: var(--muted2); }
.risk-grid strong {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-variant-numeric: tabular-nums;
}

.setup-card { margin-top: 16px; }
.setup-head { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 22px; }
.setup-head > div { flex: 1; min-width: 0; }
.setup-head h2 { font-family: var(--font-display); font-size: var(--text-lg); margin: 0; }
.setup-head p { margin: 5px 0 0; font-size: var(--text-xs); color: var(--muted2); line-height: 1.65; max-width: 74ch; }

.setup-icon {
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border-radius: var(--radius-chip);
  display: grid;
  place-items: center;
  background: var(--teal-bg);
  color: var(--c-teal);
  font-size: 17px;
}

.setup-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 26px;
  margin-bottom: 22px;
}

.setup-grid h3,
.plan-preview h3 {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--muted2);
  margin: 0 0 12px;
}

.options, .creds { list-style: none; margin: 0 0 14px; padding: 0; display: flex; flex-direction: column; gap: 11px; }

.options li { display: flex; flex-direction: column; gap: 2px; }
.options strong { font-size: var(--text-xs); color: var(--text2); }
.options small { font-size: 11px; color: var(--muted2); line-height: 1.5; }

.creds li { display: flex; gap: 11px; }
.creds li > span {
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
.creds li > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.creds strong { font-size: var(--text-xs); color: var(--text2); }
.creds small { font-size: 11px; color: var(--muted2); line-height: 1.5; }

.plan-preview { margin-bottom: 18px; }
.plan-preview ol {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.plan-preview li { font-size: var(--text-xs); color: var(--text3); line-height: 1.6; }

code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--o05);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--text3);
}
</style>
