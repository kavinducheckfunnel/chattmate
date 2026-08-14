<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.
-->

<script setup lang="ts">
withDefaults(
  defineProps<{ tone?: 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'accent' }>(),
  { tone: 'neutral' },
)
</script>

<template>
  <span class="pill" :class="`pill-${tone}`"><slot /></span>
</template>
