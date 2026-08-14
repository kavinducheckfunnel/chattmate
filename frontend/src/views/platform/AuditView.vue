<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Everything platform staff have done, newest first.

Filtering happens in the browser over the fetched window rather than on the
server. The log is small — it records operator actions, not customer traffic —
and keeping it client-side means the search is instant and the export contains
exactly the rows on screen.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import { listAudit, type AuditEntry } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, dateTime } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const entries = ref<AuditEntry[]>([])

const search = ref('')
const actionFilter = ref('all')
const expanded = ref<string | null>(null)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    entries.value = await listAudit()
  } catch (e) {
    error.value = extractApiError(e, 'Could not load the audit log')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const actions = computed(() =>
  Array.from(new Set(entries.value.map((e) => e.action))).sort(),
)

const visible = computed(() =>
  entries.value.filter((e) => {
    if (actionFilter.value !== 'all' && e.action !== actionFilter.value) return false
    const q = search.value.trim().toLowerCase()
    if (!q) return true
    return (
      e.actor_email.toLowerCase().includes(q) ||
      e.action.toLowerCase().includes(q) ||
      (e.target_organization_domain ?? '').toLowerCase().includes(q) ||
      JSON.stringify(e.details).toLowerCase().includes(q)
    )
  }),
)

const hasFilters = computed(() => !!search.value || actionFilter.value !== 'all')
const clearFilters = () => { search.value = ''; actionFilter.value = 'all' }

/** Read-heavy actions are informational; deletions are the ones to notice. */
const toneFor = (action: string) =>
  action.includes('delete') ? 'danger'
    : action.includes('read') ? 'info'
      : action.includes('create') ? 'success'
        : 'neutral'

const iconFor = (action: string) =>
  action.includes('delete') ? '!' : action.includes('read') ? '↗' : '✓'

const summarise = (entry: AuditEntry): string => {
  const d = entry.details ?? {}
  if (entry.action === 'conversation.read') {
    return `Opened a conversation with ${d.customer_email || 'an anonymous visitor'} (${d.message_count ?? '?'} messages)`
  }
  if (entry.action === 'tenant.create') return `Created the workspace, owner ${d.admin_email}`
  if (entry.action === 'tenant.delete') {
    const del = (d.deleted ?? {}) as Record<string, unknown>
    return `Deleted the workspace — ${del.users ?? 0} users, ${del.agents ?? 0} agents`
  }
  if (entry.action === 'user.create') return `Added ${d.target_user_email} as ${d.role}`
  if (entry.action === 'user.delete') return `Removed ${d.target_user_email}`
  if (entry.action === 'tenant.feature') return `Feature ${d.feature}: ${describeChanges(d.changes)}`
  if (d.changes) return describeChanges(d.changes)
  return Object.keys(d).length ? JSON.stringify(d) : 'No further detail'
}

const describeChanges = (changes: unknown): string => {
  if (!changes || typeof changes !== 'object') return '—'
  return Object.entries(changes as Record<string, { before?: unknown; after?: unknown }>)
    .map(([field, c]) => `${field}: ${fmt(c?.before)} → ${fmt(c?.after)}`)
    .join(', ')
}

const fmt = (v: unknown): string =>
  v === null || v === undefined ? 'unset' : typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v)

/**
 * Export what is on screen, not the whole log. An export that silently ignores
 * the filters produces a file that does not match the question that prompted it.
 */
const exportCsv = () => {
  const header = ['Timestamp', 'Operator', 'Action', 'Workspace', 'IP', 'Details']
  const escape = (s: string) => `"${s.replace(/"/g, '""')}"`
  const rows = visible.value.map((e) => [
    e.created_at ?? '',
    e.actor_email,
    e.action,
    e.target_organization_domain ?? '',
    e.ip_address ?? '',
    JSON.stringify(e.details ?? {}),
  ].map((c) => escape(String(c))).join(','))

  const blob = new Blob([[header.join(','), ...rows].join('\n')], {
    type: 'text/csv;charset=utf-8;',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `platform-audit-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  toast.success(`Exported ${visible.value.length} entries`)
}
</script>

<template>
  <PfPage
    title="Audit log"
    description="A record of every action platform staff have taken, including transcripts opened."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="select-button" :disabled="!visible.length" @click="exportCsv">
        ⇩ Export CSV
      </button>
      <button class="select-button" @click="load">Refresh</button>
    </template>

    <section class="panel table-panel">
      <div class="table-toolbar">
        <label class="search-box">
          <span>⌕</span>
          <input v-model="search" placeholder="Search operator, workspace or detail…" />
        </label>
        <div class="toolbar-actions">
          <label class="filter-select">
            <span>Action</span>
            <select v-model="actionFilter" aria-label="Filter by action">
              <option value="all">All actions</option>
              <option v-for="a in actions" :key="a" :value="a">{{ a }}</option>
            </select>
          </label>
          <button v-if="hasFilters" class="clear-filter-button" @click="clearFilters">
            Clear filters
          </button>
        </div>
      </div>

      <div v-if="visible.length" class="audit-list">
        <div
          v-for="entry in visible"
          :key="entry.id"
          class="audit-row"
          :class="{ open: expanded === entry.id }"
        >
          <span class="audit-icon" :class="toneFor(entry.action) === 'neutral' ? '' : toneFor(entry.action)">
            {{ iconFor(entry.action) }}
          </span>

          <div class="grow">
            <div class="audit-title">
              <strong>{{ entry.action }}</strong>
              <PfPill v-if="entry.target_organization_domain" tone="neutral">
                {{ entry.target_organization_domain }}
              </PfPill>
            </div>
            <p>{{ summarise(entry) }}</p>
            <pre v-if="expanded === entry.id" class="raw">{{ JSON.stringify(entry.details, null, 2) }}</pre>
          </div>

          <div class="audit-meta">
            <strong>{{ entry.actor_email }}</strong>
            <span>{{ dateTime(entry.created_at) }}</span>
            <span v-if="entry.ip_address" class="ip">{{ entry.ip_address }}</span>
          </div>

          <button
            class="icon-button"
            :aria-label="expanded === entry.id ? 'Hide raw detail' : 'Show raw detail'"
            @click="expanded = expanded === entry.id ? null : entry.id"
          >{{ expanded === entry.id ? '−' : '+' }}</button>
        </div>
      </div>

      <div v-else class="empty-table-state">
        <strong>No entries</strong>
        <span v-if="hasFilters">Try clearing the search or action filter.</span>
        <span v-else>Operator actions will appear here as they happen.</span>
      </div>

      <div class="pagination">
        <span>
          Showing {{ num(visible.length) }} of {{ num(entries.length) }} entries
          {{ hasFilters ? '· filters applied' : '' }}
        </span>
        <span class="retention-note">
          The log keeps the newest 100 actions. It survives the deletion of the
          workspaces it describes.
        </span>
      </div>
    </section>
  </PfPage>
</template>

<style scoped>
.audit-title { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }

.audit-row.open { background: var(--o03); }

.raw {
  margin: 8px 0 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-deep);
  border: 1px solid var(--o08);
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--code);
  overflow-x: auto;
  line-height: 1.6;
}

.ip { font-family: var(--font-mono); font-size: 9.5px; color: var(--faint); }

.retention-note { max-width: 46ch; text-align: right; line-height: 1.5; }
</style>
