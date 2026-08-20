<!--
Copyright 2024-2026 ChatterMate
Licensed under the Apache License, Version 2.0 — see LICENSE.

Page frame shared by every console view: heading, optional back link, an
actions slot, and the loading/error states. Centralised so a failed request
looks the same everywhere and no view has to reinvent an empty screen.
-->

<script setup lang="ts">
defineProps<{
  title: string
  description?: string
  back?: { to: string; label: string }
  loading?: boolean
  error?: string
}>()
</script>

<template>
  <main class="pf-page">
    <!-- page-heading / heading-actions / back-button are the reference's own
         class names. Using them here means every page picks up its header
         treatment from the ported stylesheet rather than from a parallel set of
         rules that would have to be kept in step by hand. -->
    <div class="page-heading pf-page-head">
      <div>
        <RouterLink v-if="back" :to="back.to" class="back-button pf-back">
          ← {{ back.label }}
        </RouterLink>
        <h1>{{ title }}</h1>
        <p v-if="description">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="heading-actions head-actions">
        <slot name="actions" />
      </div>
    </div>

    <div v-if="error" class="pf-banner error">{{ error }}</div>
    <div v-if="loading" class="pf-state">Loading…</div>
    <slot v-else />
  </main>
</template>
