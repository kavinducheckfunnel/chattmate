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
*/

import api from '@/services/api'

/** Metric keys the backend meters. Mirrors ALL_METRICS in app/services/usage.py. */
export type UsageMetric =
  | 'conversations'
  | 'ai_messages'
  | 'agents'
  | 'seats'
  | 'knowledge_docs'

export interface MetricUsage {
  used: number
  /** null means unlimited on this plan. */
  limit: number | null
  /** null where unlimited — a bar has nothing to fill against no ceiling. */
  percent: number | null
  exceeded: boolean
}

export interface Plan {
  code: string
  name: string
  description: string | null
  price_cents: number
  currency: string
  sort_order: number
  is_active: boolean
  is_default: boolean
  limits: Record<UsageMetric | 'storage_mb', number | null>
}

export interface UsageSummary {
  /** Billing period as 'YYYY-MM'. */
  period: string
  plan: Plan | null
  metrics: Record<UsageMetric, MetricUsage>
}

export const getUsageSummary = async (): Promise<UsageSummary> => {
  const { data } = await api.get<UsageSummary>('/usage')
  return data
}

export const getPlans = async (): Promise<Plan[]> => {
  const { data } = await api.get<Plan[]>('/usage/plans')
  return data
}

/**
 * Shape of the 402 body raised by the backend's quota check.
 *
 * 402 rather than 403 is the signal that the caller is authorised and simply
 * out of allowance, so the UI offers an upgrade rather than an access error.
 */
export interface QuotaError {
  message: string
  metric: UsageMetric
  used: number
  limit: number
  plan: string
}

/** Reads a quota rejection out of an axios error, or null if it isn't one. */
export function asQuotaError(error: unknown): QuotaError | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  if (response?.status !== 402) return null
  const detail = response?.data?.detail
  // The detail is an object for quota rejections. Guard the shape rather than
  // trusting it: a plain-string 402 from anywhere else must not be rendered as
  // "undefined/undefined used".
  if (detail && typeof detail === 'object' && 'metric' in detail) {
    return detail as QuotaError
  }
  return null
}
