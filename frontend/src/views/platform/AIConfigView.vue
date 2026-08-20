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
/** The fallback select carries "PROVIDER|model" in one option, as the reference
 *  shows a single dropdown rather than a provider/model pair. */
const onFallbackModel = () => {
  const [provider, model] = String(form.value.fallbackModel).split('|')
  if (model) {
    form.value.fallbackProvider = provider
    form.value.fallbackModel = model
  }
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
            <div class="ai-key-row">
              <input
                v-model="form.textKey"
                type="password"
                autocomplete="off"
                :placeholder="needsKey ? 'Paste the API key' : '••••••••••••••••••'"
              />
              <button
                class="select-button"
                type="button"
                :disabled="!form.textKey.trim() || saving"
                @click="save"
              >Update key</button>
            </div>
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
            <div class="ai-key-row">
              <input
                v-model="form.imageKey"
                type="password"
                autocomplete="off"
                :placeholder="keyIsSet('image') ? '••••••••••••••••••' : 'Paste the API key'"
              />
              <button
                class="select-button"
                type="button"
                :disabled="!form.imageKey.trim() || saving"
                @click="save"
              >Update key</button>
            </div>
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

          <!-- One row: switch, its label, and the model it selects. The switch
               is a button carrying .config-toggle, which the reference styles as
               the 34px control itself — putting that class on a label wrapping
               text squeezed the whole label to 34px and stacked it one word per
               line. -->
          <div class="ai-fallback">
            <button
              type="button"
              class="config-toggle"
              role="switch"
              :aria-checked="form.fallbackEnabled"
              aria-label="Enable fallback model"
              :class="{ on: form.fallbackEnabled }"
              @click="form.fallbackEnabled = !form.fallbackEnabled"
            ><i /></button>

            <span class="ai-fallback-text">
              <strong>Enable fallback model</strong>
              <small>Keeps customer conversations running during a provider outage.</small>
            </span>

            <select
              v-model="form.fallbackModel"
              class="ai-fallback-model"
              aria-label="Fallback model"
              :disabled="!form.fallbackEnabled"
              @change="onFallbackModel"
            >
              <option value="">Select a model…</option>
              <optgroup v-for="p in fallbackProviders" :key="p.value" :label="p.label">
                <option v-for="m in p.models" :key="m.value" :value="`${p.value}|${m.value}`">
                  {{ m.label }}
                </option>
              </optgroup>
            </select>
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

  </PfPage>
</template>
