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

Reading a plan-limit field back out of its input.

Vue applies the `.number` modifier automatically to `<input type="number">`, so
a draft seeded with strings turns into numbers the moment anyone types. The
parser assumed strings and called .trim(); that threw inside a computed, which
took the whole Plans view down — the page went black on the first keystroke in
a price field, and the Save button could never enable because the same computed
backed its disabled state.

This mirrors the implementation in PlansView.vue. Kept as a unit because the
distinction it protects — blank means unlimited, zero means none allowed — is a
billing decision, not a formatting one.
*/

import { describe, it, expect } from 'vitest'

type TermRow =
  | { kind: 'price'; label: string }
  | { kind: 'limit'; metric: string; label: string }
  | { kind: 'policy'; column: string; label: string; money?: boolean }

const toFieldNumber = (raw: string | number | null | undefined): number | null => {
  if (raw === null || raw === undefined) return null
  const text = String(raw).trim()
  if (text === '') return null
  const value = Number(text)
  return Number.isNaN(value) ? null : value
}

const parseTerm = (raw: string | number | null | undefined, row: TermRow): number | null => {
  const value = toFieldNumber(raw)
  if (value === null) return null
  return row.kind === 'price' || (row.kind === 'policy' && row.money)
    ? Math.round(value * 100)
    : Math.round(value)
}

const price: TermRow = { kind: 'price', label: 'Plan price' }
const agents: TermRow = { kind: 'limit', metric: 'agents', label: 'AI agents' }
const overage: TermRow = { kind: 'policy', column: 'overage', label: 'Additional', money: true }
const retention: TermRow = { kind: 'policy', column: 'retention', label: 'Retention' }

describe('plan term field values', () => {
  it('accepts a number, which is what a number input actually yields', () => {
    // The regression: this used to throw "(raw ?? '').trim is not a function".
    expect(() => parseTerm(7, price)).not.toThrow()
    expect(parseTerm(7, price)).toBe(700)
    expect(parseTerm(3, agents)).toBe(3)
  })

  it('still accepts a string, which is how drafts are seeded', () => {
    expect(parseTerm('7', price)).toBe(700)
    expect(parseTerm('  3  ', agents)).toBe(3)
  })

  it('treats an empty field as unlimited, not as zero', () => {
    for (const empty of ['', '   ', null, undefined]) {
      expect(parseTerm(empty, agents)).toBeNull()
    }
  })

  it('keeps zero distinct from blank', () => {
    // A plan with zero agents cannot create agents; a plan with no ceiling can
    // create any number. Collapsing them would silently change what was sold.
    expect(parseTerm(0, agents)).toBe(0)
    expect(parseTerm('0', agents)).toBe(0)
    expect(parseTerm(0, agents)).not.toBeNull()
  })

  it('converts money fields to minor units', () => {
    expect(parseTerm(0.01, overage)).toBe(1)
    expect(parseTerm('0.01', overage)).toBe(1)
    expect(parseTerm(49, price)).toBe(4900)
  })

  it('leaves non-money policies in their own units', () => {
    expect(parseTerm(90, retention)).toBe(90)
    expect(parseTerm('365', retention)).toBe(365)
  })

  it('rejects junk rather than storing NaN', () => {
    // NaN would serialise as null and read as "unlimited" — a typo must not
    // quietly remove a ceiling.
    expect(parseTerm('abc', agents)).toBeNull()
    expect(parseTerm('12abc', agents)).toBeNull()
  })

  it('detects a change when the input has become a number', () => {
    // What the Save button's disabled state depends on: a draft of 101 against
    // a stored 100 has to read as changed even though the types differ.
    const stored = 100
    expect(parseTerm(101, retention)).not.toBe(stored)
    expect(parseTerm(100, retention)).toBe(stored)
    expect(parseTerm('100', retention)).toBe(stored)
  })
})
