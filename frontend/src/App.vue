<!--
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

<script setup lang="ts">
import { RouterView } from 'vue-router'
import { Toaster } from 'vue-sonner'
import VerifyEmailBanner from '@/components/common/VerifyEmailBanner.vue'
</script>

<template>
  <Toaster position="top-right" />
  <!-- Above RouterView so it sits at the top of every authenticated screen.
       The component decides for itself whether to render — it stays out of the
       way on the auth screens, which have no signed-in user to prompt. -->
  <VerifyEmailBanner />
  <RouterView />
</template>

<style>
@import './assets/styles/main.css';
</style>
