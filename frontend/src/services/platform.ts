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
import type { Plan, UsageSummary } from '@/services/usage'

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

// ── Client operations ───────────────────────────────────────────────────────

export interface TenantAgent {
  id: string
  name: string
  display_name: string | null
  description: string | null
  agent_type: string | null
  is_active: boolean
  transfer_to_human: boolean
  use_workflow: boolean
  /** Count, not content — the tenant's prompts are their own work. */
  instruction_count: number
}

export interface KnowledgeSource {
  id: number
  source: string
  source_type: string | null
  created_at: string | null
}

export interface TenantIntegrations {
  channels: {
    id: string
    channel_type: string
    display_name: string | null
    is_active: boolean
    created_at: string | null
  }[]
  widgets: { id: string; name: string; agent_id: string | null }[]
}

export interface ConversationRow {
  session_id: string
  status: string | null
  channel: string
  customer: { email: string | null; full_name: string | null } | null
  agent_name: string | null
  message_count: number
  sentiment: string | null
  assigned_at: string | null
  updated_at: string | null
}

export interface TranscriptMessage {
  id: number
  message_type: string
  message: string
  created_at: string | null
  sentiment_label: string | null
}

export interface Transcript {
  session_id: string
  organization_domain: string
  status: string | null
  channel: string
  customer: { email: string | null; full_name: string | null } | null
  messages: TranscriptMessage[]
}

export interface PlatformPlan extends Plan {
  tenant_count: number
}

export interface Operator {
  id: string
  email: string
  full_name: string
  is_active: boolean
  /** null for a standalone operator that belongs to no tenant. */
  tenant: string | null
  created_at: string | null
}

export const getTenantAgents = async (id: string): Promise<TenantAgent[]> =>
  (await api.get<TenantAgent[]>(`/platform/tenants/${id}/agents`)).data

export const getTenantKnowledge = async (
  id: string,
): Promise<{ total: number; sources: KnowledgeSource[] }> =>
  (await api.get(`/platform/tenants/${id}/knowledge`)).data

export const getTenantIntegrations = async (id: string): Promise<TenantIntegrations> =>
  (await api.get<TenantIntegrations>(`/platform/tenants/${id}/integrations`)).data

export const getTenantConversations = async (
  id: string,
  params: { limit?: number; offset?: number } = {},
): Promise<{ total: number; limit: number; offset: number; conversations: ConversationRow[] }> =>
  (await api.get(`/platform/tenants/${id}/conversations`, { params })).data

/**
 * Open one conversation.
 *
 * Every call writes a `conversation.read` row to the platform audit log naming
 * the operator, the tenant and the customer. That is intentional and cannot be
 * skipped — it is the control that makes transcript access accountable rather
 * than merely available.
 */
export const getTranscript = async (id: string, sessionId: string): Promise<Transcript> =>
  (await api.get<Transcript>(`/platform/tenants/${id}/conversations/${sessionId}`)).data

export const updateTenantUser = async (
  userId: string,
  changes: { is_active?: boolean; new_password?: string },
) => (await api.patch(`/platform/users/${userId}`, changes)).data

export const getPlatformPlans = async (): Promise<PlatformPlan[]> =>
  (await api.get<PlatformPlan[]>('/platform/plans')).data

export const updatePlan = async (code: string, changes: Record<string, unknown>) =>
  (await api.patch(`/platform/plans/${code}`, changes)).data

export const getOperators = async (): Promise<Operator[]> =>
  (await api.get<Operator[]>('/platform/operators')).data

// ── Overview, analytics and health ──────────────────────────────────────────

export interface PlanRevenueRow {
  code: string
  name: string
  tenants: number
  price_cents: number
  mrr_cents: number
}

export interface Revenue {
  mrr_cents: number
  currency: string
  active_tenants: number
  paying_tenants: number
  arpa_cents: number
  by_plan: PlanRevenueRow[]
}

export interface RevenuePoint {
  period: string
  mrr_cents: number | null
  active_tenants: number | null
  paying_tenants: number | null
  /** False for months before the platform began recording — draw a gap, not a zero. */
  recorded: boolean
}

export interface UsagePoint {
  period: string
  conversations: number
  ai_messages: number
}

/** Consumption against a ceiling. `uncapped_tenants` counts workspaces on an
 *  unlimited plan, which are excluded from both sides of the ratio — including
 *  them would make the percentage describe a set the denominator does not. */
export interface AllowanceUsage {
  used: number
  limit: number | null
  percent: number | null
  uncapped_tenants: number
}

export interface Overview {
  period: string
  organizations: { total: number; active: number; suspended: number; new_this_month: number }
  users: number
  agents: number
  usage: { conversations: number; ai_messages: number }
  /** Consumption against what was actually sold. `limit` and `percent` are
   *  null where a plan has no ceiling — unlimited is not a percentage. */
  allowances?: {
    ai_messages: AllowanceUsage
    image_requests: AllowanceUsage
  }
  revenue: Revenue
  revenue_history: RevenuePoint[]
  usage_history: UsagePoint[]
  recent_organizations: {
    id: string
    name: string
    domain: string
    plan_code: string | null
    is_active: boolean
    created_at: string | null
  }[]
}

export const getOverview = async (): Promise<Overview> =>
  (await api.get<Overview>('/platform/overview')).data

export interface PlanUsageRow {
  plan_code: string
  plan_name: string
  tenants: number
  used: number
  /** null when the plan has no ceiling — unlimited is not the same as unused. */
  allowance: number | null
  percent: number | null
}

export interface PlatformAnalytics {
  range: string
  since: string
  filters: { plan_code: string | null; channel: string | null }
  /** Workspaces that had a conversation in the window, not workspaces that exist. */
  active_organizations: number
  plan_usage: PlanUsageRow[]
  conversations: {
    total: number
    messages: number
    handovers: number
    ai_only: number
    by_status: Record<string, number>
    daily: { date: string; count: number }[]
  }
  channels: { channel: string; count: number }[]
  satisfaction: { average: number | null; responses: number }
  knowledge: { sources: number }
  top_organizations: {
    id: string
    name: string
    domain: string
    plan_code: string | null
    conversations: number
  }[]
}

export const getPlatformAnalytics = async (
  range: '7d' | '30d' | '90d',
  filters: { plan_code?: string; channel?: string } = {},
): Promise<PlatformAnalytics> =>
  (await api.get<PlatformAnalytics>('/platform/analytics', {
    params: { range, ...filters },
  })).data

export interface ServiceProbe {
  name: string
  status: 'operational' | 'down'
  latency_ms: number
  detail: string
}

export interface PlatformHealth {
  status: 'operational' | 'degraded' | 'down'
  checked_at: string
  api_uptime_seconds: number
  services: ServiceProbe[]
  counts: Record<string, number>
}

export const getPlatformHealth = async (): Promise<PlatformHealth> =>
  (await api.get<PlatformHealth>('/platform/health')).data

// ── Tenant and user management ──────────────────────────────────────────────

export interface TenantCreateInput {
  name: string
  domain: string
  admin_name: string
  admin_email: string
  admin_password: string
  plan_code?: string
  timezone?: string
}

export const createTenant = async (input: TenantCreateInput) =>
  (await api.post('/platform/tenants', input)).data

export interface PlatformUser {
  id: string
  email: string
  full_name: string
  is_active: boolean
  is_email_verified: boolean
  /** Operator accounts are listed but not editable here — the UI marks them. */
  is_platform_admin: boolean
  role: string | null
  organization_id: string | null
  organization_domain: string | null
  organization_name: string | null
  created_at: string | null
}

export const listPlatformUsers = async (params: {
  q?: string
  organization_id?: string
  role?: string
  is_active?: boolean
  limit?: number
  offset?: number
} = {}): Promise<{ total: number; limit: number; offset: number; users: PlatformUser[] }> =>
  (await api.get('/platform/users', { params })).data

export interface TenantRole {
  id: string
  name: string
  description: string | null
  is_default: boolean
}

export const listTenantRoles = async (organizationId: string): Promise<TenantRole[]> =>
  (await api.get<TenantRole[]>('/platform/roles', { params: { organization_id: organizationId } })).data

export const createPlatformUser = async (input: {
  organization_id: string
  full_name: string
  email: string
  password: string
  role_id?: string
}) => (await api.post('/platform/users', input)).data

export const updatePlatformUserRole = async (userId: string, roleId: string) =>
  (await api.patch(`/platform/users/${userId}/role`, { role_id: roleId })).data

/** `confirmEmail` must match exactly; the server enforces it, not the UI. */
export const deletePlatformUser = async (userId: string, confirmEmail: string) =>
  (await api.delete(`/platform/users/${userId}`, { data: { confirm_email: confirmEmail } })).data

// ── Feature matrix ──────────────────────────────────────────────────────────

export interface FeatureDef {
  key: string
  label: string
  category: string
  description: string
  /** Where the gate actually runs. Shown so no switch looks more powerful than it is. */
  enforced_at: string
}

export interface FeatureMatrix {
  features: FeatureDef[]
  plans: {
    code: string
    name: string
    price_cents: number
    /** False when nothing has been set for this plan — which means unrestricted, not empty. */
    configured: boolean
    features: Record<string, boolean>
  }[]
}

export const getFeatureMatrix = async (): Promise<FeatureMatrix> =>
  (await api.get<FeatureMatrix>('/platform/features')).data

export const setPlanFeatures = async (planCode: string, features: Record<string, boolean>) =>
  (await api.put(`/platform/plans/${planCode}/features`, { features })).data

export interface TenantFeature extends FeatureDef {
  plan_default: boolean
  /** null when the tenant simply follows their plan. */
  override: boolean | null
  effective: boolean
}

export const getTenantFeatures = async (
  id: string,
): Promise<{
  organization_id: string
  plan_code: string | null
  plan_configured: boolean
  features: TenantFeature[]
}> => (await api.get(`/platform/tenants/${id}/features`)).data

/** `isEnabled: null` clears the override, returning the tenant to their plan. */
export const setTenantFeature = async (
  id: string,
  featureKey: string,
  isEnabled: boolean | null,
  reason?: string,
) => (await api.put(`/platform/tenants/${id}/features`, {
  feature_key: featureKey, is_enabled: isEnabled, reason,
})).data

// ── AI configuration ────────────────────────────────────────────────────────

export interface TenantAIConfig {
  organization_id: string
  organization_name: string
  domain: string
  plan_code: string | null
  model_type: string | null
  model_name: string
  is_active: boolean
  updated_at: string | null
}

export interface AIConfigOverview {
  platform_default: { model_name: string | null; configured: boolean; note: string }
  by_model: { model: string; workspaces: number }[]
  workspaces: TenantAIConfig[]
  /** Workspaces with no model set — the usual reason an agent never answers. */
  unconfigured: {
    organization_id: string
    organization_name: string
    domain: string
    plan_code: string | null
  }[]
}

export const getAIConfiguration = async (): Promise<AIConfigOverview> =>
  (await api.get<AIConfigOverview>('/platform/ai')).data

// ── Platform AI credentials ─────────────────────────────────────────────────
//
// The provider accounts the operator pays for, which back the managed model a
// tenant can select instead of bringing their own key. API keys are never sent
// back to the browser — `has_api_key` is all the console needs to know.

export interface CatalogModel {
  value: string
  label: string
}

export interface CatalogProvider {
  value: string
  label: string
  requires_api_key: boolean
  custom_allowed: boolean
  api_key_url: string
  models: CatalogModel[]
}

export interface PlatformModelSection {
  provider: string | null
  model: string | null
  has_api_key: boolean
}

export interface PlatformAIConfig {
  text: PlatformModelSection
  image: PlatformModelSection
  fallback: { enabled: boolean; provider: string | null; model: string | null }
  is_configured: boolean
  supports_images: boolean
  updated_at: string | null
}

export interface PlatformAIResponse {
  config: PlatformAIConfig
  providers: CatalogProvider[]
  tenants_using_platform_model: number
}

/** `api_key` omitted means "keep the stored key" — never "clear it". */
export interface PlatformAIPayload {
  text: { provider: string | null; model: string | null; api_key?: string }
  image: { provider: string | null; model: string | null; api_key?: string }
  fallback: { enabled: boolean; provider: string | null; model: string | null }
}

export const getPlatformAIConfig = async (): Promise<PlatformAIResponse> =>
  (await api.get<PlatformAIResponse>('/platform/ai-config')).data

export const savePlatformAIConfig = async (
  payload: PlatformAIPayload,
): Promise<{ config: PlatformAIConfig; tenants_resynced: number; message: string }> =>
  (await api.put('/platform/ai-config', payload)).data

// ── Plan limits ─────────────────────────────────────────────────────────────

/** What happens to organizations already on a plan whose terms just changed. */
export type ApplyPolicy = 'new_subscriptions_only' | 'at_next_renewal' | 'immediately'

export interface PlanTermsPayload {
  price_cents?: number | null
  limits?: Record<string, number | null>
  policies?: Record<string, number | null>
}

export interface PlanLimitsPayload {
  apply_policy: ApplyPolicy
  plans: Record<string, PlanTermsPayload>
}

export const savePlanLimits = async (
  payload: PlanLimitsPayload,
): Promise<{
  message: string
  apply_policy: ApplyPolicy
  tenants_affected: number
  changes: Record<string, Record<string, [number | null, number | null]>>
}> => (await api.put('/platform/plans/limits', payload)).data
