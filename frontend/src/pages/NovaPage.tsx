import { useState } from 'react'
import NovaOwnershipPanel from '../components/NovaOwnershipPanel'
import NovaRawExplorer from '../components/NovaRawExplorer'
import { PageHeader } from '../ui'

// Nova ownership & rate certification (services/nova_reconciliation/,
// docs/nova/NOVA_RECONCILIATION_LOGIC.md). The older invoice-vs-Nova-ledger view that
// used to share this page (pipelines/billing_reconciliation.py, /api/billing/*) has
// been retired — this is the one Nova reconciliation system now.
//
// Two subpages, deliberately separate: Reconciliation is what we concluded about a
// bill; Raw API is what Nova actually said. Keeping them apart is what makes it
// possible to tell a Nova data problem from a reconciliation problem.

type Tab = 'reconciliation' | 'raw'

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'reconciliation', label: 'Reconciliation', hint: 'Ownership & rate certification per bill' },
  { id: 'raw', label: 'Raw Nova API', hint: 'Unreconciled Nova output by brand, vendor and month' },
]

export default function NovaPage() {
  const [tab, setTab] = useState<Tab>('reconciliation')

  return (
    <div className="workspace-scroll-page">
      <div style={{ maxWidth: 1400, margin: '0 auto' }}>
        <PageHeader title="Nova" sub="Verify bill ownership and rates against Nova records." />

        <div className="workspace-view-switch" role="group" aria-label="Nova views">
          {TABS.map(t => {
            const active = tab === t.id
            return (
              <button
                key={t.id}
                type="button"
                aria-pressed={active}
                title={t.hint}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            )
          })}
        </div>

        {tab === 'reconciliation' ? <NovaOwnershipPanel /> : <NovaRawExplorer />}
      </div>
    </div>
  )
}
