/*
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

Client for the platform operator console.

Every route here 404s for anyone without users.is_platform_admin, which is why
`isPlatformAdmin()` probes rather than reads a flag from the session: the server
is the only authority, and the console must disappear the moment access is
revoked rather than at the next login.
*/

import api from '@/services/api'
import type { UsageSummary } from '@/services/usage'

export interface PlatformStats {
  period: string
  organizations: { total: number; active: number; suspended: number }
  users: number
  usage: { conversations: number; ai_messages: number }
  by_plan: Record<string, number>
}

export interface TenantRow {
  id: string
  name: string
  domain: string
  plan_code: string | null
  is_active: boolean
  created_at: string | null
  seats: number
  agents: number
  conversations: number
  ai_messages: number
}

export interface TenantList {
  total: number
  limit: number
  offset: number
  period: string
  tenants: TenantRow[]
}

export interface TenantUser {
  id: string
  email: string
  full_name: string
  is_active: boolean
  is_email_verified: boolean
  role: string | null
  created_at: string | null
}

export interface TenantDetail {
  id: string
  name: string
  domain: string
  timezone: string
  is_active: boolean
  plan_code: string | null
  created_at: string | null
  usage: UsageSummary
  users: TenantUser[]
}

export interface AuditEntry {
  id: string
  actor_email: string
  action: string
  target_organization_id: string | null
  target_organization_domain: string | null
  details: Record<string, unknown>
  ip_address: string | null
  created_at: string | null
}

export const getPlatformStats = async (): Promise<PlatformStats> =>
  (await api.get<PlatformStats>('/platform/stats')).data

export const listTenants = async (params: {
  q?: string
  limit?: number
  offset?: number
} = {}): Promise<TenantList> =>
  (await api.get<TenantList>('/platform/tenants', { params })).data

export const getTenant = async (id: string): Promise<TenantDetail> =>
  (await api.get<TenantDetail>(`/platform/tenants/${id}`)).data

export const updateTenant = async (
  id: string,
  changes: { is_active?: boolean; plan_code?: string },
) => (await api.patch(`/platform/tenants/${id}`, changes)).data

/**
 * Delete a tenant. `confirmDomain` must match exactly or the server refuses —
 * the check is server-side so it cannot be skipped by calling the API directly.
 */
export const deleteTenant = async (id: string, confirmDomain: string) =>
  (await api.delete(`/platform/tenants/${id}`, { data: { confirm_domain: confirmDomain } })).data

export const listAudit = async (organizationId?: string): Promise<AuditEntry[]> =>
  (await api.get<AuditEntry[]>('/platform/audit', {
    params: organizationId ? { organization_id: organizationId } : {},
  })).data

/**
 * Whether this session can reach the console.
 *
 * Asks the server instead of trusting anything client-side. The nav link and
 * the route guard both use this, so a revoked operator loses the link on their
 * next navigation rather than keeping a door that 404s when pushed.
 */
export const isPlatformAdmin = async (): Promise<boolean> => {
  try {
    await api.get('/platform/stats')
    return true
  } catch {
    return false
  }
}
