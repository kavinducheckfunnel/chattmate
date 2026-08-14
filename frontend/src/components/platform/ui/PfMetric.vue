<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.
-->

<script setup lang="ts">
import { pfIcon } from '@/components/platform/platformIcons'
import PfPill from './PfPill.vue'

withDefaults(
  defineProps<{
    label: string
    value: string
    /** Optional context line. Omitted entirely rather than filled with a placeholder. */
    delta?: string
    deltaTone?: 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'accent'
    icon: string
    tone?: 'lime' | 'teal' | 'purple' | 'coral'
  }>(),
  { tone: 'lime', deltaTone: 'neutral', delta: '' },
)
</script>

<template>
  <article class="metric-card">
    <div class="metric-icon" :class="`tone-${tone}`" v-html="pfIcon(icon, 19)" />
    <div class="metric-copy">
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
    </div>
    <PfPill v-if="delta" :tone="deltaTone">{{ delta }}</PfPill>
  </article>
</template>
