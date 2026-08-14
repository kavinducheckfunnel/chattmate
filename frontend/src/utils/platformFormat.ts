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

Formatting shared across the operator console.
*/

/** Thousands separators, and an em dash for "no value" rather than a bare 0. */
export const num = (v: number | null | undefined): string =>
  v === null || v === undefined ? '—' : v.toLocaleString('en-US')

/** Compact form for headline metrics: 68,400 → 68.4K. */
export const compact = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '—'
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return String(v)
}

export const money = (v: number | null | undefined, currency = 'USD'): string =>
  v === null || v === undefined
    ? '—'
    : v.toLocaleString('en-US', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Whole-dollar form for axis labels and plan prices. */
export const money0 = (v: number | null | undefined, currency = 'USD'): string =>
  v === null || v === undefined
    ? '—'
    : v.toLocaleString('en-US', { style: 'currency', currency, minimumFractionDigits: 0, maximumFractionDigits: 0 })

export const date = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

export const dateTime = (iso: string | null | undefined): string =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      })
    : '—'

/**
 * "3 hours ago". Falls back to an absolute date past a week, where a relative
 * label stops being easier to read than the date itself.
 */
export const ago = (iso: string | null | undefined): string => {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const mins = Math.floor((Date.now() - then) / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  return date(iso)
}

/** Up to two letters from a name, for avatar tiles. */
export const initials = (name: string | null | undefined): string =>
  (name || '').trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || '—'

/**
 * Percentage of a limit. `null` means unlimited, which is not 0% and not 100% —
 * callers get null back and must decide how to show "no ceiling".
 */
export const usagePct = (used: number, limit: number | null): number | null =>
  limit === null || limit === undefined ? null : limit <= 0 ? 100 : Math.round((used / limit) * 100)

/** "1,240 / 5,000", or "1,240 / Unlimited". */
export const ofLimit = (used: number, limit: number | null): string =>
  `${num(used)} / ${limit === null || limit === undefined ? 'Unlimited' : num(limit)}`
