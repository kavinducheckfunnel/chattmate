<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.
-->

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ value: number; label: string; color?: string }>(),
  { color: 'var(--accent-ink)' },
)

// Clamped because a tenant over its allowance would otherwise wrap the ring
// past 360° and read as a low number.
const clamped = computed(() => Math.max(0, Math.min(100, Math.round(props.value))))
</script>

<template>
  <div class="ring-item">
    <div class="ring" :style="{ background: `conic-gradient(${color} ${clamped * 3.6}deg, var(--o08) 0deg)` }">
      <div><strong>{{ clamped }}%</strong></div>
    </div>
    <span>{{ label }}</span>
  </div>
</template>
