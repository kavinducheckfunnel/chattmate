<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

The platform's own provider accounts, and which model every workspace runs on.

Two things live here because they answer one question. The top card holds the
credentials the operator pays for: a tenant may select the managed model instead
of bringing their own key, and these are the accounts behind that option. The
lower sections then show who took it up and who has configured nothing at all,
which is the usual reason an agent never answers.

API keys are never fetched, not even masked. A masked key still identifies the
provider account a customer pays for, and the console only needs to know whether
one is set.
-->

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import PfPage from '@/components/platform/ui/PfPage.vue'
import PfPill from '@/components/platform/ui/PfPill.vue'
import PfMetric from '@/components/platform/ui/PfMetric.vue'
import {
  getAIConfiguration, getPlatformAIConfig, savePlatformAIConfig,
  type AIConfigOverview, type PlatformAIResponse, type CatalogProvider,
} from '@/services/platform'
import { extractApiError } from '@/utils/apiError'
import { num, date, initials } from '@/utils/platformFormat'

const loading = ref(true)
const error = ref('')
const saving = ref(false)
const data = ref<AIConfigOverview | null>(null)
const platform = ref<PlatformAIResponse | null>(null)

// Draft state. Keys stay separate from the loaded config because they are
// write-only: the server never sends one back, so an untouched field must mean
// "keep what is stored" rather than "clear it".
const form = ref({
  textProvider: '',
  textModel: '',
  textKey: '',
  imageProvider: '',
  imageModel: '',
  imageKey: '',
  fallbackEnabled: false,
  fallbackProvider: '',
  fallbackModel: '',
})

const hydrate = (response: PlatformAIResponse) => {
  const c = response.config
  form.value = {
    textProvider: c.text.provider ?? '',
    textModel: c.text.model ?? '',
    textKey: '',
    imageProvider: c.image.provider ?? '',
    imageModel: c.image.model ?? '',
    imageKey: '',
    fallbackEnabled: c.fallback.enabled,
    fallbackProvider: c.fallback.provider ?? '',
    fallbackModel: c.fallback.model ?? '',
  }
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const [overview, platformConfig] = await Promise.all([
      getAIConfiguration(),
      getPlatformAIConfig(),
    ])
    data.value = overview
    platform.value = platformConfig
    hydrate(platformConfig)
  } catch (e) {
    error.value = extractApiError(e, 'Could not load AI configuration')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const providers = computed<CatalogProvider[]>(() => platform.value?.providers ?? [])

const modelsFor = (providerValue: string) =>
  providers.value.find((p) => p.value === providerValue)?.models ?? []

const labelFor = (providerValue: string | null) =>
  providers.value.find((p) => p.value === providerValue)?.label ?? providerValue ?? '—'

/** The fallback borrows a key from a provider already configured above, so it
 *  can only offer those two — a third account nothing exercises until an outage
 *  is one nobody notices has expired. */
const fallbackProviders = computed(() =>
  providers.value.filter(
    (p) => p.value === form.value.textProvider || p.value === form.value.imageProvider,
  ),
)

// Changing provider invalidates the model chosen from the previous one.
const onTextProvider = () => {
  form.value.textModel = modelsFor(form.value.textProvider)[0]?.value ?? ''
  form.value.textKey = ''
}
const onImageProvider = () => {
  form.value.imageModel = modelsFor(form.value.imageProvider)[0]?.value ?? ''
  form.value.imageKey = ''
}
const onFallbackProvider = () => {
  form.value.fallbackModel = modelsFor(form.value.fallbackProvider)[0]?.value ?? ''
}

const keyIsSet = (section: 'text' | 'image') =>
  Boolean(platform.value?.config[section].has_api_key)

/** A provider newly chosen has no stored key, so one must be typed now. */
const needsKey = computed(() => {
  const changed = form.value.textProvider !== (platform.value?.config.text.provider ?? '')
  return changed || !keyIsSet('text')
})

const canSave = computed(() => {
  if (!form.value.textProvider || !form.value.textModel) return false
  if (needsKey.value && !form.value.textKey.trim()) return false
  if (form.value.fallbackEnabled && !form.value.fallbackProvider) return false
  return true
})

const save = async () => {
  saving.value = true
  try {
    const result = await savePlatformAIConfig({
      text: {
        provider: form.value.textProvider || null,
        model: form.value.textModel || null,
        // Omitted rather than sent empty: absent means "keep the stored key".
        ...(form.value.textKey.trim() ? { api_key: form.value.textKey.trim() } : {}),
      },
      image: {
        provider: form.value.imageProvider || null,
        model: form.value.imageModel || null,
        ...(form.value.imageKey.trim() ? { api_key: form.value.imageKey.trim() } : {}),
      },
      fallback: {
        enabled: form.value.fallbackEnabled,
        provider: form.value.fallbackEnabled ? form.value.fallbackProvider || null : null,
        model: form.value.fallbackEnabled ? form.value.fallbackModel || null : null,
      },
    })
    toast.success(result.message)
    await load()
  } catch (e) {
    toast.error(extractApiError(e, 'Could not save the AI configuration'))
  } finally {
    saving.value = false
  }
}

// ── Workspace overview ─────────────────────────────────────────────────────

const totalWorkspaces = computed(
  () => (data.value?.workspaces.length ?? 0) + (data.value?.unconfigured.length ?? 0),
)

const activeCount = computed(
  () => (data.value?.workspaces ?? []).filter((w) => w.is_active).length,
)

const search = ref('')
const visible = computed(() => {
  const q = search.value.trim().toLowerCase()
  const rows = data.value?.workspaces ?? []
  if (!q) return rows
  return rows.filter((w) =>
    `${w.organization_name} ${w.domain} ${w.model_type} ${w.model_name}`.toLowerCase().includes(q),
  )
})
</script>

<template>
  <PfPage
    title="AI configuration"
    description="Control platform models, routing, provider access and AI cost safeguards."
    :loading="loading"
    :error="error"
  >
    <template #actions>
      <button class="select-button" @click="load">Refresh</button>
    </template>

    <!-- Platform model setup ------------------------------------------------->
    <section v-if="platform" class="panel ai-setup">
      <header class="ai-setup-head">
        <div>
          <h2 class="section-title">AI model setup</h2>
          <p class="section-sub">Choose the models used to answer text and image messages.</p>
        </div>
        <PfPill :tone="platform.config.is_configured ? 'success' : 'warning'">
          {{ platform.config.is_configured ? 'Active' : 'Not configured' }}
        </PfPill>
      </header>

      <!-- 1. Text ------------------------------------------------------------>
      <div class="ai-step">
        <span class="ai-step-num">1</span>
        <div class="ai-step-body">
          <h3>Text messages</h3>
          <p class="section-sub">Used when a customer sends a message without an image.</p>

          <div class="form-grid two">
            <label class="field">
              <span>Provider</span>
              <select v-model="form.textProvider" @change="onTextProvider">
                <option value="">Select a provider…</option>
                <option v-for="p in providers" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>Model</span>
              <select v-model="form.textModel" :disabled="!form.textProvider">
                <option value="">Select a model…</option>
                <option v-for="m in modelsFor(form.textProvider)" :key="m.value" :value="m.value">
                  {{ m.label }}
                </option>
              </select>
            </label>
          </div>

          <label class="field">
            <span>{{ labelFor(form.textProvider) }} API key</span>
            <input
              v-model="form.textKey"
              type="password"
              autocomplete="off"
              :placeholder="needsKey ? 'Paste the API key' : '•••••••••••••••••• (stored)'"
            />
            <small class="field-hint">
              Stored encrypted and never shown again — a masked key would still
              reveal which account is in use.
            </small>
          </label>
        </div>
      </div>

      <!-- 2. Image ----------------------------------------------------------->
      <div class="ai-step">
        <span class="ai-step-num">2</span>
        <div class="ai-step-body">
          <h3>Image messages</h3>
          <p class="section-sub">Used only when a customer attaches an image.</p>

          <div class="form-grid two">
            <label class="field">
              <span>Provider</span>
              <select v-model="form.imageProvider" @change="onImageProvider">
                <option value="">Not offered</option>
                <option v-for="p in providers" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>Model</span>
              <select v-model="form.imageModel" :disabled="!form.imageProvider">
                <option value="">Select a model…</option>
                <option v-for="m in modelsFor(form.imageProvider)" :key="m.value" :value="m.value">
                  {{ m.label }}
                </option>
              </select>
            </label>
          </div>

          <label v-if="form.imageProvider" class="field">
            <span>{{ labelFor(form.imageProvider) }} API key</span>
            <input
              v-model="form.imageKey"
              type="password"
              autocomplete="off"
              :placeholder="keyIsSet('image') ? '•••••••••••••••••• (stored)' : 'Paste the API key'"
            />
            <small class="field-hint">
              This model answers the image allowance sold on paid plans.
            </small>
          </label>
        </div>
      </div>

      <!-- 3. Fallback -------------------------------------------------------->
      <div class="ai-step">
        <span class="ai-step-num">3</span>
        <div class="ai-step-body">
          <h3>Fallback</h3>
          <p class="section-sub">Use another model automatically if the main text model is unavailable.</p>

          <div class="ai-fallback">
            <label class="config-toggle">
              <input v-model="form.fallbackEnabled" type="checkbox" />
              <span>
                <strong>Enable fallback model</strong>
                <small>Keeps customer conversations running during a provider outage.</small>
              </span>
            </label>

            <div v-if="form.fallbackEnabled" class="ai-fallback-picks">
              <label class="field">
                <span>Provider</span>
                <select v-model="form.fallbackProvider" @change="onFallbackProvider">
                  <option value="">Select…</option>
                  <option v-for="p in fallbackProviders" :key="p.value" :value="p.value">
                    {{ p.label }}
                  </option>
                </select>
              </label>
              <label class="field">
                <span>Model</span>
                <select v-model="form.fallbackModel" :disabled="!form.fallbackProvider">
                  <option value="">Select…</option>
                  <option
                    v-for="m in modelsFor(form.fallbackProvider)"
                    :key="m.value"
                    :value="m.value"
                  >
                    {{ m.label }}
                  </option>
                </select>
              </label>
            </div>
          </div>

          <p v-if="form.fallbackEnabled && !fallbackProviders.length" class="pf-banner warn">
            Configure a text or image provider first — the fallback reuses one of
            those accounts rather than holding a key of its own.
          </p>
        </div>
      </div>

      <!-- Routing summary ---------------------------------------------------->
      <div class="ai-routing">
        <div>
          <span>Text only</span>
          <strong>{{ form.textModel || 'Not set' }}</strong>
        </div>
        <span class="ai-routing-arrow" aria-hidden="true">→</span>
        <div>
          <span>Image attached</span>
          <strong>{{ form.imageModel || 'Not offered' }}</strong>
        </div>
      </div>

      <footer class="ai-setup-foot">
        <span class="section-sub">
          Changes apply to new AI requests after saving.
          <template v-if="platform.tenants_using_platform_model">
            {{ num(platform.tenants_using_platform_model) }}
            workspace{{ platform.tenants_using_platform_model === 1 ? '' : 's' }}
            currently use the platform model.
          </template>
        </span>
        <button class="primary-button" :disabled="!canSave || saving" @click="save">
          {{ saving ? 'Saving…' : 'Save AI configuration' }}
        </button>
      </footer>
    </section>

    <!-- Workspace overview --------------------------------------------------->
    <template v-if="data">
      <section class="metrics-grid">
        <PfMetric
          label="Workspaces with a model"
          :value="num(data.workspaces.length)"
          :delta="`of ${num(totalWorkspaces)} total`"
          icon="aiconfig"
        />
        <PfMetric
          label="Active configurations"
          :value="num(activeCount)"
          :delta="activeCount === data.workspaces.length ? 'All enabled' : `${data.workspaces.length - activeCount} disabled`"
          :delta-tone="activeCount === data.workspaces.length ? 'success' : 'warning'"
          icon="check"
          tone="teal"
        />
        <PfMetric
          label="On the platform model"
          :value="num(platform?.tenants_using_platform_model ?? 0)"
          delta="Billed to the platform"
          icon="aiconfig"
          tone="purple"
        />
        <PfMetric
          label="Distinct models"
          :value="num(data.by_model.length)"
          delta="Across all workspaces"
          icon="chart"
        />
      </section>

      <section class="panel table-panel">
        <div class="table-toolbar">
          <div>
            <h2 class="section-title">Workspace models</h2>
            <p class="section-sub">Which model each workspace answers with today.</p>
          </div>
          <input v-model="search" class="filter-select" placeholder="Search workspaces…" />
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Workspace</th>
                <th>Plan</th>
                <th>Provider</th>
                <th>Model</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="w in visible" :key="w.organization_id">
                <td>
                  <div class="cell-identity">
                    <span class="avatar">{{ initials(w.organization_name) }}</span>
                    <div>
                      <strong>{{ w.organization_name }}</strong>
                      <small>{{ w.domain }}</small>
                    </div>
                  </div>
                </td>
                <td>{{ w.plan_code ?? '—' }}</td>
                <td>{{ w.model_type ?? '—' }}</td>
                <td>{{ w.model_name }}</td>
                <td>
                  <PfPill :tone="w.is_active ? 'success' : 'neutral'">
                    {{ w.is_active ? 'Active' : 'Disabled' }}
                  </PfPill>
                </td>
                <td>{{ date(w.updated_at) }}</td>
              </tr>
              <tr v-if="!visible.length">
                <td colspan="6" class="empty-table-state">No workspaces match that search.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="data.unconfigured.length" class="panel table-panel">
        <div class="table-toolbar">
          <div>
            <h2 class="section-title">No model configured</h2>
            <p class="section-sub">
              These workspaces cannot answer a customer at all — the usual reason
              an agent appears silent.
            </p>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Workspace</th><th>Domain</th><th>Plan</th></tr>
            </thead>
            <tbody>
              <tr v-for="u in data.unconfigured" :key="u.organization_id">
                <td><strong>{{ u.organization_name }}</strong></td>
                <td>{{ u.domain }}</td>
                <td>{{ u.plan_code ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </PfPage>
</template>
