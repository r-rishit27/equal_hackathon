import { describe, expect, it } from 'vitest'
import type { Role } from '../auth/permissions'
import type { ServiceKey } from '../auth/services'
import { workspaceNavigation } from './workspaceNavigation'

function pages(role: Role, enabled: ServiceKey[]) {
  return workspaceNavigation(role, service => enabled.includes(service))
    .flatMap(group => group.items.map(item => item.page))
}

describe('tenant workspace navigation', () => {
  it('shows core workflows for a core-only tenant', () => {
    const result = pages('admin', ['bills', 'upload_ocr', 'vendors', 'reports', 'settings'])
    expect(result).toEqual([
      'dashboard', 'bills', 'upload', 'vendors', 'inventory', 'reports', 'integrations', 'settings',
    ])
  })

  it('includes purchased modules once across both ledgers', () => {
    const result = pages('admin', ['review_hub', 'disbursement', 'receivables', 'fact_graph', 'agent_hub', 'nova_billing'])
    expect(result).toEqual([
      'review', 'payments', 'copilot', 'agent-hub', 'cfo-orchestrator', 'nova',
      'ar-cash', 'ar-invoices', 'ar-upload', 'ar-customers', 'integrations',
    ])
    const receivables = workspaceNavigation('admin', () => true, 'receivable')
      .flatMap(group => group.items.map(item => item.page))
    expect(receivables).toEqual(['ar-cash', 'ar-invoices', 'ar-upload', 'ar-customers', 'nova', 'integrations', 'settings'])
  })

  it('also respects role capabilities within a licensed tenant', () => {
    expect(pages('member', ['bills', 'fact_graph', 'settings'])).toEqual(['bills'])
    expect(pages('approver', ['bills', 'upload_ocr', 'fact_graph', 'disbursement']))
      .toEqual(['bills', 'upload', 'payments', 'copilot'])
  })

  it('keeps tenant modules hidden before a user or licence is known', () => {
    expect(workspaceNavigation(undefined, () => true)).toEqual([])
    expect(pages('auditor', [])).toEqual([])
  })
})
