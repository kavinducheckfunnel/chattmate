<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.
-->

<script setup lang="ts">
import { computed } from 'vue'

export interface Bar { label: string; value: number }

const props = withDefaults(
  defineProps<{ bars: Bar[]; format?: (v: number) => string; ticks?: number }>(),
  { ticks: 5 },
)

const max = computed(() => Math.max(1, ...props.bars.map((b) => b.value)))

/**
 * Axis labels descend from the peak. Deriving them from the data rather than
 * hard-coding "$4K / $3K …" means the chart stays honest when the numbers are
 * an order of magnitude smaller than the design mock assumed.
 */
const axis = computed(() => {
  const fmt = props.format ?? ((v: number) => String(Math.round(v)))
  return Array.from({ length: props.ticks }, (_, i) => fmt((max.value * (props.ticks - 1 - i)) / (props.ticks - 1)))
})

const height = (v: number) => `${Math.max(2, (v / max.value) * 100)}%`
</script>

<template>
  <div class="chart-area">
    <div class="chart-grid"><span v-for="(t, i) in axis" :key="i">{{ t }}</span></div>
    <div class="bars">
      <div v-for="b in bars" :key="b.label" class="bar-wrap" :title="`${b.label}: ${format ? format(b.value) : b.value}`">
        <div class="bar" :style="{ height: height(b.value) }" />
        <span>{{ b.label }}</span>
      </div>
    </div>
  </div>
</template>
