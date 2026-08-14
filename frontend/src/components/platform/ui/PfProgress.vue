<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.
-->

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ label: string; value: string; percent: number }>()

const width = computed(() => Math.max(0, Math.min(100, props.percent)))

// Colour is the warning, not just decoration: a bar that turns amber at 80%
// and red at capacity says "act now" without the operator reading the numbers.
const tone = computed(() => (width.value >= 100 ? 'danger' : width.value >= 80 ? 'warn' : ''))
</script>

<template>
  <div class="progress-item">
    <div><span>{{ label }}</span><strong>{{ value }}</strong></div>
    <div class="progress-track" :class="tone"><i :style="{ width: `${width}%` }" /></div>
  </div>
</template>
