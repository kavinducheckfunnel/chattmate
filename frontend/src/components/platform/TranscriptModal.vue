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
import { ref, watch } from 'vue'
import { getTranscript, type Transcript } from '@/services/platform'
import { extractApiError } from '@/utils/apiError'

const props = defineProps<{ tenantId: string; sessionId: string | null }>()
const emit = defineEmits<{ close: [] }>()

const loading = ref(false)
const error = ref('')
const transcript = ref<Transcript | null>(null)

watch(
  () => props.sessionId,
  async (id) => {
    transcript.value = null
    error.value = ''
    if (!id) return
    loading.value = true
    try {
      transcript.value = await getTranscript(props.tenantId, id)
    } catch (e) {
      error.value = extractApiError(e, 'Could not load this conversation')
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const time = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  }) : ''

/**
 * Who said it. 'user' is the tenant's customer, 'bot' the AI, 'agent' a human
 * on the tenant's team — three different speakers that must not be conflated
 * when someone is reading this to work out what went wrong.
 */
const speaker = (type: string) =>
  ({ user: 'Customer', bot: 'AI agent', agent: 'Human agent' }[type] ?? type)
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="sheet">
      <header class="sheet-head">
        <div>
          <h2>Conversation</h2>
          <p v-if="transcript" class="sub">
            {{ transcript.customer?.email || 'Anonymous visitor' }}
            · {{ transcript.channel }}
            · {{ transcript.messages.length }} messages
          </p>
        </div>
        <button class="close" @click="emit('close')" aria-label="Close">×</button>
      </header>

      <!-- Stated plainly rather than hidden. An operator reading a customer's
           conversation should know the record exists, and the tenant should be
           able to be told truthfully that it does. -->
      <p class="audit-notice">
        This conversation belongs to <strong>{{ transcript?.organization_domain || 'this tenant' }}</strong>.
        Opening it has been recorded in the audit log against your account.
      </p>

      <div v-if="loading" class="state">Loading…</div>
      <div v-else-if="error" class="state error">{{ error }}</div>
      <div v-else-if="transcript && !transcript.messages.length" class="state">
        No messages in this conversation.
      </div>

      <div v-else-if="transcript" class="thread">
        <div
          v-for="m in transcript.messages"
          :key="m.id"
          class="msg"
          :class="m.message_type"
        >
          <div class="msg-meta">
            <span class="who">{{ speaker(m.message_type) }}</span>
            <span class="when">{{ time(m.created_at) }}</span>
          </div>
          <div class="bubble">{{ m.message }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 9, 0.72);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
  padding: var(--space-md);
}

.sheet {
  background: var(--surface);
  border: 1px solid var(--o10);
  border-radius: var(--radius-card-lg);
  width: 100%;
  max-width: 720px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
}

.sheet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-lg);
  border-bottom: 1px solid var(--o08);
}

.sheet-head h2 {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  color: var(--text);
  margin: 0 0 2px;
}

.sub { color: var(--muted2); font-size: var(--text-xs); margin: 0; }

.close {
  background: none;
  border: 1px solid var(--o12);
  border-radius: var(--radius-md);
  width: 30px;
  height: 30px;
  color: var(--muted2);
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
}

.close:hover { background: var(--o06); color: var(--text); }

.audit-notice {
  margin: 0;
  padding: var(--space-sm) var(--space-lg);
  background: var(--warning-bg);
  border-bottom: 1px solid color-mix(in srgb, var(--warning-color) 25%, transparent);
  color: var(--warning-color);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.audit-notice strong { font-weight: 600; }

.state {
  padding: var(--space-2xl) var(--space-lg);
  text-align: center;
  color: var(--muted2);
  font-size: var(--text-sm);
}

.state.error { color: var(--error-color); }

.thread {
  overflow-y: auto;
  padding: var(--space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.msg { display: flex; flex-direction: column; max-width: 76%; }

/* The customer on the left, the tenant's side on the right — the reading
   convention of every chat client, so the thread is scannable at a glance. */
.msg.user { align-self: flex-start; }
.msg.bot, .msg.agent { align-self: flex-end; align-items: flex-end; }

.msg-meta {
  display: flex;
  gap: var(--space-sm);
  font-size: var(--text-xs);
  color: var(--muted2);
  margin-bottom: 4px;
}

.who { font-weight: 600; }

.bubble {
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  font-size: var(--text-sm);
  line-height: 1.55;
  color: var(--text2);
  background: var(--o06);
  border: 1px solid var(--o08);
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.bot .bubble {
  background: var(--accent-bg-08);
  border-color: var(--accent-border);
}

.msg.agent .bubble {
  background: color-mix(in srgb, var(--c-purple, #8b7bd8) 12%, transparent);
  border-color: color-mix(in srgb, var(--c-purple, #8b7bd8) 28%, transparent);
}

@media (max-width: 640px) {
  .msg { max-width: 92%; }
}
</style>
