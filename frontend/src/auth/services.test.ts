import { describe, expect, it } from 'vitest'
import { ALL_SERVICES, SERVICE_DESCRIPTIONS, SERVICE_LABELS, type ServiceKey } from './services'
import { hasService, normalizeEntitlements } from './entitlements'

describe('service registry', () => {
  // A key with a label but no category is silently dropped by
  // normalizeEntitlements, so its module never shows even when licensed
  // (receivables, 2026-11-17).
  it('lists every labelled service in a category', () => {
    const labelled = Object.keys(SERVICE_LABELS).sort()
    expect([...ALL_SERVICES].sort()).toEqual(labelled)
    expect(Object.keys(SERVICE_DESCRIPTIONS).sort()).toEqual(labelled)
  })

  it('keeps every licensed service through normalisation', () => {
    for (const key of Object.keys(SERVICE_LABELS) as ServiceKey[]) {
      const e = normalizeEntitlements({ company_id: 't', services: { [key]: { enabled: true } } })
      expect(hasService(e, key)).toBe(true)
    }
  })
})
