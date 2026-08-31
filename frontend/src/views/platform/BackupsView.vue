<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Backups & recovery — the reference's OneDriveBackups, wired to real work.

Every control here does the thing it says. "Prepare local backup" runs pg_dump,
packs the uploads tree and encrypts the archive; "Connect & test" signs into
Microsoft Entra and writes a probe file into the destination folder; the
schedule is what the server's scheduler actually reads. Nothing on this page is
a placeholder, because a backup screen that lies is the one screen someone
checks before deciding they are safe.
-->

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import {
  disconnectBackups,
  downloadLocalBackup,
  getBackups,
  prepareLocalBackup,
  runBackupNow,
  saveBackupConnection,
  saveBackupSchedule,
  testBackupConnection,
  type BackupOverview,
  type BackupRun,
} from '@/services/platform'
import { extractApiError } from '@/utils/apiError'

const loading = ref(true)
const error = ref('')
const notice = ref('')
const actionError = ref('')
const data = ref<BackupOverview | null>(null)

// --- local backup ----------------------------------------------------------
const includeFiles = ref(true)
const creating = ref(false)
const downloading = ref(false)
const prepared = ref<BackupRun | null>(null)

// --- connection ------------------------------------------------------------
const tenantId = ref('')
const clientId = ref('')
const clientSecret = ref('')
const accountEmail = ref('')
const folder = ref('/Growmiq mini Backups')
const connecting = ref(false)
const disconnecting = ref(false)

// --- schedule --------------------------------------------------------------
const scheduleEnabled = ref(false)
const frequency = ref('daily')
const weekday = ref(6)
const dayOfMonth = ref(1)
const backupTime = ref('02:00')
const zone = ref('UTC')
const contents = ref('database_and_files')
const savingSchedule = ref(false)
const scheduleSaved = ref(false)
const runningNow = ref(false)

const apply = (payload: BackupOverview) => {
  data.value = payload
  const c = payload.connection
  tenantId.value = c.tenant_id
  clientId.value = c.client_id
  accountEmail.value = c.account_email
  folder.value = c.folder
  // Never repopulated from the server — it is never sent. An empty box against a
  // stored secret is honest; a row of dots that cannot be submitted is not.
  clientSecret.value = ''

  const s = payload.schedule
  scheduleEnabled.value = s.enabled
  frequency.value = s.frequency
  weekday.value = s.weekday
  dayOfMonth.value = s.day_of_month
  backupTime.value = s.backup_time
  zone.value = s.timezone
  contents.value = s.contents
  scheduleSaved.value = false
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    apply(await getBackups())
  } catch (e) {
    error.value = extractApiError(e, 'Could not read the backup configuration')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const connection = computed(() => data.value?.connection)
const connected = computed(() => Boolean(connection.value?.is_connected))
const canDump = computed(() => data.value?.server.can_dump !== false)

/**
 * A stored secret counts as filled. Requiring it to be retyped to change the
 * folder would mean fetching it out of Entra again for a one-word edit.
 */
const canConnect = computed(() =>
  Boolean(
    tenantId.value.trim() &&
      clientId.value.trim() &&
      accountEmail.value.trim() &&
      (clientSecret.value.trim() || connection.value?.has_client_secret),
  ),
)

/** Any credential edit invalidates a previous successful test. */
const invalidate = () => {
  if (data.value) data.value.connection.is_connected = false
  scheduleSaved.value = false
}

const clearMessages = () => {
  actionError.value = ''
  notice.value = ''
}

// -------------------------------------------------------------- local backup

const createLocalBackup = async () => {
  clearMessages()
  creating.value = true
  prepared.value = null
  try {
    const payload = await prepareLocalBackup(
      includeFiles.value ? 'database_and_files' : 'database_only',
    )
    apply(payload)
    prepared.value = payload.prepared ?? null
  } catch (e) {
    actionError.value = extractApiError(e, 'The backup could not be created')
  } finally {
    creating.value = false
  }
}

const saveToComputer = async () => {
  if (!prepared.value) return
  clearMessages()
  downloading.value = true
  const run = prepared.value
  try {
    await downloadLocalBackup(run.id, run.filename ?? 'chattermate-backup.cmbk')
    // The server deletes its copy on delivery, so the button must go back to
    // offering a fresh preparation rather than a second download that 404s.
    prepared.value = null
    notice.value = 'Backup downloaded. The temporary server copy has been deleted.'
    apply(await getBackups())
  } catch (e) {
    actionError.value = extractApiError(e, 'The download failed')
  } finally {
    downloading.value = false
  }
}

// ----------------------------------------------------------------- connection

const connectAndTest = async () => {
  clearMessages()
  connecting.value = true
  try {
    await saveBackupConnection({
      tenant_id: tenantId.value.trim(),
      client_id: clientId.value.trim(),
      // Omitted when untouched, which the server reads as "keep the stored one".
      ...(clientSecret.value.trim() ? { client_secret: clientSecret.value.trim() } : {}),
      account_email: accountEmail.value.trim(),
      folder: folder.value.trim() || '/Growmiq mini Backups',
    })
    apply(await testBackupConnection())
    notice.value = 'Connected. A test file was written to the destination folder and removed.'
  } catch (e) {
    actionError.value = extractApiError(e, 'Could not connect to OneDrive')
  } finally {
    connecting.value = false
  }
}

const disconnect = async () => {
  clearMessages()
  disconnecting.value = true
  try {
    apply(await disconnectBackups())
    notice.value = 'Disconnected. Scheduled uploads are off.'
  } catch (e) {
    actionError.value = extractApiError(e, 'Could not disconnect')
  } finally {
    disconnecting.value = false
  }
}

// ------------------------------------------------------------------- schedule

const saveSchedule = async () => {
  clearMessages()
  savingSchedule.value = true
  try {
    apply(
      await saveBackupSchedule({
        enabled: scheduleEnabled.value,
        frequency: frequency.value,
        weekday: weekday.value,
        day_of_month: dayOfMonth.value,
        backup_time: backupTime.value,
        timezone: zone.value,
        contents: contents.value,
      }),
    )
    scheduleSaved.value = true
  } catch (e) {
    actionError.value = extractApiError(e, 'Could not save the schedule')
  } finally {
    savingSchedule.value = false
  }
}

const runNow = async () => {
  clearMessages()
  runningNow.value = true
  try {
    apply(await runBackupNow())
    notice.value = 'Backup uploaded to OneDrive.'
  } catch (e) {
    actionError.value = extractApiError(e, 'The backup failed')
  } finally {
    runningNow.value = false
  }
}

// -------------------------------------------------------------------- display

const WEEKDAYS = [
  // Sunday first, as the reference lists them; the value is Python's
  // datetime.weekday(), where Monday is 0.
  { value: 6, label: 'Sunday' },
  { value: 0, label: 'Monday' },
  { value: 1, label: 'Tuesday' },
  { value: 2, label: 'Wednesday' },
  { value: 3, label: 'Thursday' },
  { value: 4, label: 'Friday' },
  { value: 5, label: 'Saturday' },
]

const offsetLabel = (tz: string): string => {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      timeZoneName: 'longOffset',
    }).formatToParts(new Date())
    const name = parts.find((part) => part.type === 'timeZoneName')?.value ?? 'GMT'
    return name === 'GMT' ? 'UTC' : name.replace('GMT', 'UTC')
  } catch {
    return 'UTC'
  }
}

/**
 * Every IANA zone the browser knows, so an operator anywhere can set a window
 * in their own time. The server's configured zone is merged in — it may not be
 * in the browser's list on an older engine, and it must always be selectable.
 */
const timezones = computed(() => {
  let names: string[] = []
  try {
    names = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] })
      .supportedValuesOf?.('timeZone') ?? []
  } catch {
    names = []
  }
  if (!names.length) {
    names = ['UTC', 'Asia/Colombo', 'Europe/London', 'America/New_York', 'Asia/Dubai']
  }
  const merged = new Set(['UTC', ...names])
  if (zone.value) merged.add(zone.value)
  if (data.value?.server.timezone) merged.add(data.value.server.timezone)
  return [...merged]
    .sort()
    .map((name) => ({ value: name, label: `${name} (${offsetLabel(name)})` }))
})

const stamp = (iso: string | null): string => {
  if (!iso) return '—'
  const when = new Date(iso)
  const day = when.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  const time = when.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return `${day} · ${time}`
}

const sizeLabel = (bytes: number | null): string => {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return index < 2 ? `${Math.round(value)} ${units[index]}` : `${value.toFixed(1)} ${units[index]}`
}

const METHOD_LABELS: Record<string, string> = {
  scheduled: 'Scheduled',
  manual: 'Manual upload',
  local: 'Local download',
}
const CONTENTS_LABELS: Record<string, string> = {
  database_and_files: 'Database + files',
  database_only: 'Database only',
}
const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Uploaded',
  downloaded: 'Downloaded',
  ready: 'Ready',
  running: 'In progress',
  failed: 'Failed',
  expired: 'Expired',
}
const STATUS_TONES: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  uploaded: 'success',
  downloaded: 'success',
  ready: 'info',
  running: 'warning',
  failed: 'danger',
  expired: 'neutral',
}

const history = computed(() => data.value?.history ?? [])

const nextRunLabel = computed(() => {
  if (!scheduleEnabled.value) return 'Automatic OneDrive backups are disabled'
  if (!connected.value) return 'Connect OneDrive to schedule automatic backups'
  const next = data.value?.schedule.next_run_at
  if (!next) return 'Save the schedule to set the next run'
  const cadence =
    frequency.value === 'weekly'
      ? `Weekly, ${WEEKDAYS.find((d) => d.value === weekday.value)?.label ?? 'Sunday'}`
      : frequency.value === 'monthly'
        ? `Monthly, day ${dayOfMonth.value}`
        : 'Daily'
  return `Next run: ${cadence} at ${backupTime.value} — ${stamp(next)} local time`
})
</script>

<template>
  <PfPage
    title="Backups &amp; recovery"
    description="Protect platform data and manage recovery points."
    :loading="loading"
    :error="error"
  >
    <div class="onedrive-backups-page">
      <div v-if="actionError" class="pf-banner error">{{ actionError }}</div>
      <div v-else-if="notice" class="pf-banner info">{{ notice }}</div>
      <div v-if="!canDump" class="pf-banner warn">
        This server has no <code>pg_dump</code>, so the database cannot be exported.
        Rebuild the backend image to enable backups.
      </div>

      <section class="backup-top-grid">
        <!-- 01 — Download to local computer -->
        <article class="panel backup-compact-card">
          <div class="backup-card-title">
            <span>01</span>
            <div>
              <h2>Download to local computer</h2>
              <p>Create an encrypted backup and save it directly to this computer.</p>
            </div>
          </div>

          <div class="backup-option-list">
            <label class="backup-option">
              <!-- Always included: an archive without the database is not a backup.
                   Held checked by preventing the click rather than by `disabled`,
                   which greys the box out — the reference (and the design) show
                   both options at the same full-strength green. -->
              <input type="checkbox" :checked="true" @click.prevent />
              <span>
                <strong>Database</strong>
                <small>Platform data, configuration and settings</small>
              </span>
            </label>
            <label class="backup-option">
              <input v-model="includeFiles" type="checkbox" />
              <span>
                <strong>Uploaded files</strong>
                <small>Knowledge documents, images and attachments</small>
              </span>
            </label>
          </div>

          <div class="backup-delivery-summary">
            <span>Destination</span>
            <strong>Local computer</strong>
            <small>Encrypted downloadable backup file</small>
          </div>

          <div class="backup-method-actions">
            <button
              v-if="!prepared"
              class="primary-button"
              :disabled="creating || !canDump"
              @click="createLocalBackup"
            >
              {{ creating ? 'Preparing download…' : 'Prepare local backup' }}
            </button>
            <button v-else class="primary-button" :disabled="downloading" @click="saveToComputer">
              {{ downloading ? 'Downloading…' : 'Download to this computer' }}
            </button>
            <span v-if="prepared" class="backup-success-text">
              Ready for download ({{ sizeLabel(prepared.size_bytes) }}). The temporary server
              copy will be deleted after delivery.
            </span>
          </div>
        </article>

        <!-- Microsoft OneDrive connection -->
        <article class="panel onedrive-connection-card">
          <div class="backup-card-title">
            <span class="microsoft-step">M</span>
            <div>
              <h2>Microsoft OneDrive connection</h2>
              <p>Connect through a Microsoft Entra application using Microsoft Graph.</p>
            </div>
          </div>

          <div class="onedrive-status-line">
            <div>
              <span>Connection status</span>
              <strong>{{ connected ? accountEmail : 'Not connected' }}</strong>
            </div>
            <PfPill :tone="connected ? 'success' : 'neutral'">
              {{ connected ? 'Connected' : 'Setup required' }}
            </PfPill>
          </div>

          <div class="onedrive-fields">
            <label>
              <span>Microsoft tenant ID</span>
              <input v-model="tenantId" placeholder="Directory (tenant) ID" @input="invalidate" />
            </label>
            <label>
              <span>Application client ID</span>
              <input v-model="clientId" placeholder="Application (client) ID" @input="invalidate" />
            </label>
            <label>
              <span>Client secret</span>
              <input
                v-model="clientSecret"
                type="password"
                autocomplete="new-password"
                :placeholder="
                  connection?.has_client_secret
                    ? 'Stored — enter a new value to replace it'
                    : 'Enter client secret value'
                "
                @input="invalidate"
              />
            </label>
            <label>
              <span>OneDrive account email</span>
              <input
                v-model="accountEmail"
                type="email"
                placeholder="backups@company.com"
                @input="invalidate"
              />
            </label>
            <label class="full-field">
              <span>Destination folder</span>
              <input v-model="folder" @input="invalidate" />
            </label>
          </div>

          <div class="onedrive-connect-actions">
            <small>Required Microsoft Graph permission: Files.ReadWrite.All</small>
            <button
              v-if="connected"
              class="select-button"
              :disabled="disconnecting"
              @click="disconnect"
            >
              {{ disconnecting ? 'Disconnecting…' : 'Disconnect' }}
            </button>
            <button
              v-else
              class="primary-button"
              :disabled="!canConnect || connecting"
              @click="connectAndTest"
            >
              {{ connecting ? 'Testing…' : 'Connect &amp; test' }}
            </button>
          </div>
        </article>
      </section>

      <!-- OneDrive backup schedule -->
      <section class="panel onedrive-schedule-card">
        <div class="panel-heading">
          <div>
            <h2>OneDrive backup schedule</h2>
            <p>
              Scheduled backups upload directly to OneDrive. The temporary VPS archive is
              deleted after transfer.
            </p>
          </div>
          <label class="schedule-toggle">
            <input
              v-model="scheduleEnabled"
              type="checkbox"
              :disabled="!connected"
              @change="scheduleSaved = false"
            />
            <span>{{ scheduleEnabled ? 'Enabled' : 'Disabled' }}</span>
          </label>
        </div>

        <div class="schedule-fields">
          <label>
            <span>Frequency</span>
            <select
              v-model="frequency"
              :disabled="!scheduleEnabled"
              @change="scheduleSaved = false"
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </label>
          <label v-if="frequency === 'weekly'">
            <span>Day</span>
            <select
              v-model.number="weekday"
              :disabled="!scheduleEnabled"
              @change="scheduleSaved = false"
            >
              <option v-for="day in WEEKDAYS" :key="day.value" :value="day.value">
                {{ day.label }}
              </option>
            </select>
          </label>
          <!-- Monthly needs a day for the schedule to mean anything; the
               reference only ever shows Daily, so it has no equivalent. -->
          <label v-else-if="frequency === 'monthly'">
            <span>Day of month</span>
            <select
              v-model.number="dayOfMonth"
              :disabled="!scheduleEnabled"
              @change="scheduleSaved = false"
            >
              <option v-for="day in 31" :key="day" :value="day">{{ day }}</option>
            </select>
          </label>
          <label>
            <span>Backup time</span>
            <input
              v-model="backupTime"
              type="time"
              :disabled="!scheduleEnabled"
              @change="scheduleSaved = false"
            />
          </label>
          <label>
            <span>Time zone</span>
            <select v-model="zone" :disabled="!scheduleEnabled" @change="scheduleSaved = false">
              <option v-for="tz in timezones" :key="tz.value" :value="tz.value">
                {{ tz.label }}
              </option>
            </select>
          </label>
          <label>
            <span>Backup contents</span>
            <select v-model="contents" :disabled="!scheduleEnabled" @change="scheduleSaved = false">
              <option value="database_and_files">Database and uploaded files</option>
              <option value="database_only">Database only</option>
            </select>
          </label>
        </div>

        <div class="schedule-footer">
          <span>{{ nextRunLabel }}</span>
          <button
            class="primary-button"
            :disabled="!connected || savingSchedule"
            @click="saveSchedule"
          >
            {{ savingSchedule ? 'Saving…' : scheduleSaved ? 'Saved' : 'Save schedule' }}
          </button>
        </div>
      </section>

      <!-- OneDrive backup history -->
      <section class="panel table-panel onedrive-history">
        <div class="billing-table-header">
          <div>
            <h2>OneDrive backup history</h2>
            <p>
              Delivery records only. Backup files are stored in Microsoft OneDrive, not on this
              server.
            </p>
          </div>
          <button class="select-button" :disabled="!connected || runningNow" @click="runNow">
            {{ runningNow ? 'Running…' : 'Run backup now' }}
          </button>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Created</th>
                <th>Method</th>
                <th>Contents</th>
                <th>Destination</th>
                <th>Size</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="run in history" :key="run.id">
                <td><strong>{{ stamp(run.created_at) }}</strong></td>
                <td>{{ METHOD_LABELS[run.method] ?? run.method }}</td>
                <td>{{ CONTENTS_LABELS[run.contents] ?? run.contents }}</td>
                <td>{{ run.destination }}</td>
                <td>{{ sizeLabel(run.size_bytes) }}</td>
                <td>
                  <PfPill :tone="STATUS_TONES[run.status] ?? 'neutral'">
                    {{ STATUS_LABELS[run.status] ?? run.status }}
                  </PfPill>
                  <!-- A failed row without its reason sends the operator to the
                       server logs for something the API already told us. -->
                  <small v-if="run.error" class="pf-run-error">{{ run.error }}</small>
                </td>
              </tr>
              <tr v-if="!history.length">
                <td colspan="6" class="pf-empty-row">
                  No backups yet. Prepare a local backup, or connect OneDrive to schedule them.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </PfPage>
</template>

<style scoped>
/* Two additions only; every other rule on this page comes from the ported
   reference stylesheet so the layout cannot drift from the design. */
.pf-run-error {
  display: block;
  margin-top: 6px;
  max-width: 320px;
  color: var(--error-color);
  font-size: 11px;
  line-height: 1.4;
  white-space: normal;
}

.pf-empty-row {
  padding: 34px 0;
  color: var(--muted);
  text-align: center;
}
</style>
