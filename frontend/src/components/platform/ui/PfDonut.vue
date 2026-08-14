<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.
-->

<script setup lang="ts">
import { computed } from 'vue'

export interface Slice { label: string; value: number; color: string }

const props = defineProps<{ slices: Slice[]; total: number; caption: string }>()

/**
 * A conic-gradient needs hard stops at cumulative angles. Building the string
 * from a running total keeps the segments adjacent with no seam, which a
 * per-slice start/end calculation tends to get wrong by a fraction of a degree.
 */
const gradient = computed(() => {
  const sum = props.slices.reduce((t, s) => t + s.value, 0)
  if (!sum) return 'var(--o08)'
  let deg = 0
  const stops = props.slices.map((s) => {
    const start = deg
    deg += (s.value / sum) * 360
    return `${s.color} ${start}deg ${deg}deg`
  })
  return `conic-gradient(${stops.join(',')})`
})

const pct = (v: number) => {
  const sum = props.slices.reduce((t, s) => t + s.value, 0)
  return sum ? Math.round((v / sum) * 100) : 0
}
</script>

<template>
  <div class="donut-wrap">
    <div class="donut" :style="{ background: gradient }">
      <div>
        <strong>{{ total.toLocaleString() }}</strong>
        <span>{{ caption }}</span>
      </div>
    </div>
    <div class="legend">
      <div v-for="s in slices" :key="s.label">
        <i class="dot" :style="{ background: s.color }" />
        <span>{{ s.label }}</span>
        <strong>{{ s.value.toLocaleString() }}</strong>
        <small>{{ pct(s.value) }}%</small>
      </div>
    </div>
  </div>
</template>
