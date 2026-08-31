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

Shell for the platform operator console.

Deliberately not DashboardLayout. That layout is built around a tenant — it
reads the signed-in user's organization for the plan badge, the message-limit
banner and the notification feed. A platform operator has no organization, so
every one of those would render empty or, worse, borrow whichever tenant was
looked at last. A separate shell also makes the context switch obvious: the
operator can see at a glance that they are outside any customer's workspace.
-->

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { pfIcon } from '@/components/platform/platformIcons'
import { useTheme } from '@/composables/useTheme'
import { useAuth } from '@/composables/useAuth'
import { userService } from '@/services/user'
import { getPlatformStats, type PlatformStats } from '@/services/platform'

const route = useRoute()
const router = useRouter()
const { mode: themeMode, toggle: toggleTheme } = useTheme()
const { logout } = useAuth()

type NavItem = { to: string; label: string; icon: string; group: 'platform' | 'system' }

const NAV: NavItem[] = [
  { to: '/platform/overview', label: 'Overview', icon: 'overview', group: 'platform' },
  { to: '/platform/organizations', label: 'Organizations', icon: 'org', group: 'platform' },
  { to: '/platform/users', label: 'Users', icon: 'people', group: 'platform' },
  { to: '/platform/plans', label: 'Plans & Limits', icon: 'plans', group: 'platform' },
  { to: '/platform/ai', label: 'AI Configuration', icon: 'aiconfig', group: 'platform' },
  { to: '/platform/billing', label: 'Billing', icon: 'billing', group: 'platform' },
  { to: '/platform/analytics', label: 'Analytics', icon: 'trend', group: 'platform' },
  { to: '/platform/health', label: 'System Health', icon: 'health', group: 'system' },
  { to: '/platform/backups', label: 'Backups & Recovery', icon: 'backups', group: 'system' },
  { to: '/platform/audit', label: 'Audit Logs', icon: 'audit', group: 'system' },
]

const platformNav = NAV.filter((i) => i.group === 'platform')
const systemNav = NAV.filter((i) => i.group === 'system')

// Persisted so the console opens the way the operator left it. A collapsed
// sidebar is a working preference, not a per-visit decision.
const collapsed = ref(localStorage.getItem('pf.sidebar') === 'collapsed')
const menuOpen = ref(false)
const profileOpen = ref(false)

watch(collapsed, (v) => localStorage.setItem('pf.sidebar', v ? 'collapsed' : 'expanded'))

// Closing on navigation matters on mobile, where the sidebar covers the page.
watch(() => route.fullPath, () => { menuOpen.value = false; profileOpen.value = false })

const user = computed(() => userService.getCurrentUser())
const displayName = computed(() => user.value?.full_name || user.value?.email || 'Operator')
const initials = computed(() =>
  displayName.value.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || 'OP',
)

// Tenant count in the nav badge. Fetched once here rather than by the
// Organizations view, so the number is present even before that page is opened.
const tenantCount = ref<number | null>(null)
const loadCount = async () => {
  try {
    const s: PlatformStats = await getPlatformStats()
    tenantCount.value = s.organizations.total
  } catch {
    tenantCount.value = null
  }
}

// Global search is a router jump, not its own result surface — every target it
// can reach already has a real filtered list behind it.
const search = ref('')
const submitSearch = () => {
  const q = search.value.trim()
  if (!q) return
  router.push({ path: '/platform/organizations', query: { q } })
  search.value = ''
}

const searchInput = ref<HTMLInputElement | null>(null)
const onKeydown = (e: KeyboardEvent) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    searchInput.value?.focus()
  }
}

const themeTitle = computed(() =>
  themeMode.value === 'dark' ? 'Theme: Dark — click for Light'
    : themeMode.value === 'light' ? 'Theme: Light — click for System'
      : 'Theme: System — click for Dark',
)

const isActive = (to: string) => route.path === to || route.path.startsWith(to + '/')

onMounted(() => {
  loadCount()
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="pf-shell" :class="{ 'pf-collapsed': collapsed, 'pf-menu-open': menuOpen }">
    <button v-if="menuOpen" class="pf-backdrop" aria-label="Close menu" @click="menuOpen = false" />

    <aside class="pf-sidebar">
      <div class="pf-brand">
        <span class="pf-brand-mark">GM</span>
        <span>Growmiq mini</span>
        <span class="pf-brand-tag">ADMIN</span>
      </div>

      <button
        class="pf-collapse-btn"
        :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="collapsed = !collapsed"
      >{{ collapsed ? '›' : '‹' }}</button>

      <nav class="pf-nav">
        <span class="pf-nav-section">PLATFORM</span>
        <RouterLink
          v-for="item in platformNav"
          :key="item.to"
          :to="item.to"
          :class="{ active: isActive(item.to) }"
          :title="collapsed ? item.label : undefined"
        >
          <i class="pf-nav-icon" v-html="pfIcon(item.icon)" />
          <span class="pf-nav-label">{{ item.label }}</span>
          <em v-if="item.to === '/platform/organizations' && tenantCount !== null" class="pf-nav-count">
            {{ tenantCount }}
          </em>
        </RouterLink>

        <span class="pf-nav-section">SYSTEM</span>
        <RouterLink
          v-for="item in systemNav"
          :key="item.to"
          :to="item.to"
          :class="{ active: isActive(item.to) }"
          :title="collapsed ? item.label : undefined"
        >
          <i class="pf-nav-icon" v-html="pfIcon(item.icon)" />
          <span class="pf-nav-label">{{ item.label }}</span>
          <b v-if="item.to === '/platform/health'" class="pf-nav-live" />
        </RouterLink>
      </nav>

      <div class="pf-sidebar-bottom">
        <div class="pf-profile-wrap">
          <button class="pf-profile" @click="profileOpen = !profileOpen">
            <span class="pf-avatar">{{ initials }}</span>
            <span class="pf-profile-text">
              <strong>{{ displayName }}</strong>
              <small>Super Administrator</small>
            </span>
            <span class="pf-profile-caret">⌄</span>
          </button>
          <div v-if="profileOpen" class="pf-profile-menu">
            <button @click="toggleTheme">
              <i v-html="pfIcon(themeMode === 'dark' ? 'moon' : themeMode === 'light' ? 'sun' : 'monitor', 15)" />
              {{ themeTitle.split('—')[0].trim() }}
            </button>
            <button @click="logout()">
              <i v-html="pfIcon('logout', 15)" />
              Sign out
            </button>
          </div>
        </div>
      </div>
    </aside>

    <div class="pf-main">
      <header class="pf-topbar">
        <button class="pf-hamburger" aria-label="Open menu" @click="menuOpen = true" v-html="pfIcon('menu')" />

        <label class="pf-search">
          <i v-html="pfIcon('search', 15)" />
          <input
            ref="searchInput"
            v-model="search"
            placeholder="Search organizations…"
            @keydown.enter="submitSearch"
          />
          <kbd>⌘K</kbd>
        </label>

        <div class="pf-top-actions">
          <button :title="themeTitle" :aria-label="themeTitle" @click="toggleTheme"
            v-html="pfIcon(themeMode === 'dark' ? 'moon' : themeMode === 'light' ? 'sun' : 'monitor', 16)" />
          <span class="pf-divider" />
          <div class="pf-mini-profile">
            <span class="pf-avatar">{{ initials }}</span>
            <span>
              <strong>{{ displayName.split(' ')[0] }}</strong>
              <small>Super Admin</small>
            </span>
          </div>
        </div>
      </header>

      <RouterView />
    </div>
  </div>
</template>

<style>
@import '@/assets/styles/platform.css';
/* After ours, deliberately: where both define a shared class the reference wins,
   which is the point of the port. Our own Pf* primitives use names the reference
   does not have, so they are untouched by the ordering. */
@import '@/assets/styles/platform-reference.css';
</style>

<style scoped>
.pf-profile-wrap { position: relative; }

.pf-profile-caret { color: var(--muted2); font-size: 13px; flex: 0 0 auto; }
.pf-shell.pf-collapsed .pf-profile-caret { display: none; }

.pf-profile-menu {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  right: 0;
  min-width: 180px;
  background: var(--bg-elevated);
  border: 1px solid var(--o12);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: 5px;
  display: flex;
  flex-direction: column;
  z-index: 10;
}

.pf-profile-menu button {
  display: flex;
  align-items: center;
  gap: 9px;
  border: 0;
  background: transparent;
  color: var(--text2);
  font-size: var(--text-xs);
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  text-align: left;
  cursor: pointer;
}

.pf-profile-menu button:hover { background: var(--o07); }
.pf-profile-menu i { display: grid; place-items: center; color: var(--muted2); }
</style>
