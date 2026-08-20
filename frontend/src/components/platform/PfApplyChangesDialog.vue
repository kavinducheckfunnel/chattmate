<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Asks who a pricing change applies to before it is saved.

Editing a plan and re-pricing the customers already on it are two different
acts, and the operator is the only one who knows which they meant. Defaulting
silently would mean the safe-looking "save" button quietly changes the terms of
every live subscription, so the choice is made here, explicitly, every time.
-->

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ApplyPolicy } from '@/services/platform'

const props = defineProps<{
  open: boolean
  /** How many organizations sit on the plans being edited. */
  affected: number
  /** e.g. "Prices and usage limits" — what the operator actually touched. */
  changeType: string
  saving?: boolean
  error?: string
}>()

const emit = defineEmits<{
  (e: 'confirm', policy: ApplyPolicy): void
  (e: 'cancel'): void
}>()

// Renewal is the recommended default: it gives new customers the new offer
// immediately while letting existing ones finish the period they paid for.
const policy = ref<ApplyPolicy>('at_next_renewal')

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) policy.value = 'at_next_renewal'
  },
)

const options: { value: ApplyPolicy; title: string; detail: string; recommended?: boolean }[] = [
  {
    value: 'new_subscriptions_only',
    title: 'New subscriptions only',
    detail: 'Existing customers keep their current plan configuration.',
  },
  {
    value: 'at_next_renewal',
    title: 'Apply at next renewal',
    detail: 'New customers receive changes now. Existing customers update safely on renewal.',
    recommended: true,
  },
  {
    value: 'immediately',
    title: 'Apply immediately to everyone',
    detail: '',
  },
]

const detailFor = (value: ApplyPolicy, fallback: string) =>
  value === 'immediately'
    ? `All ${props.affected} organization${props.affected === 1 ? '' : 's'} update now. ` +
      'Customers may lose access or exceed a reduced limit.'
    : fallback

const effectiveLabel: Record<ApplyPolicy, string> = {
  new_subscriptions_only: 'New subscriptions only',
  at_next_renewal: 'Existing customers at renewal',
  immediately: 'Everyone, immediately',
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="pf-modal-backdrop" @click.self="emit('cancel')">
      <div class="pf-modal" role="dialog" aria-modal="true" aria-labelledby="apply-title">
        <header class="pf-modal-head">
          <span class="pf-modal-icon" aria-hidden="true">↻</span>
          <div>
            <h2 id="apply-title">Apply plan limit changes</h2>
            <p>Choose when these changes should affect customer organizations.</p>
          </div>
          <button class="pf-modal-close" aria-label="Close" @click="emit('cancel')">×</button>
        </header>

        <div class="pf-modal-body">
          <label
            v-for="option in options"
            :key="option.value"
            class="pf-choice"
            :class="{ 'pf-choice-active': policy === option.value }"
          >
            <input v-model="policy" type="radio" :value="option.value" name="apply-policy" />
            <span class="pf-choice-text">
              <span class="pf-choice-title">
                {{ option.title }}
                <span v-if="option.recommended" class="pf-choice-badge">Recommended</span>
              </span>
              <span class="pf-choice-detail">{{ detailFor(option.value, option.detail) }}</span>
            </span>
          </label>

          <dl class="pf-modal-summary">
            <div>
              <dt>Change type</dt>
              <dd>{{ changeType }}</dd>
            </div>
            <div>
              <dt>Effective policy</dt>
              <dd>{{ effectiveLabel[policy] }}</dd>
            </div>
          </dl>

          <p v-if="error" class="pf-modal-error" role="alert">{{ error }}</p>
        </div>

        <footer class="pf-modal-foot">
          <button class="select-button" :disabled="saving" @click="emit('cancel')">
            Back to editing
          </button>
          <button class="pf-primary" :disabled="saving" @click="emit('confirm', policy)">
            {{ saving ? 'Saving…' : 'Confirm & save changes' }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>
