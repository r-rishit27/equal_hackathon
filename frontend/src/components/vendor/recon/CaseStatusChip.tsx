/**
 * A case's status as a chip.
 *
 * Its own file because it is the smallest thing in Recon and the most widely
 * used: the folder, the dashboard's invoice list and the case card all show
 * it. Living in `ReconFolder` meant importing it pulled in the document
 * viewer, and with it react-pdf and pdfjs — enough to break a test that only
 * wanted a coloured label, and enough to drag a PDF renderer into any bundle
 * that showed one.
 */
const CASE_STATUS: Record<string, { label: string; tone: string }> = {
  AWAITING_INVOICE: { label: 'Waiting for invoice', tone: 'plain' },
  AWAITING_PO: { label: 'Waiting for PO', tone: 'plain' },
  IN_PROGRESS: { label: 'Reading', tone: 'info' },
  NEEDS_REVIEW: { label: 'Needs review', tone: 'warn' },
  // Waiting on someone else, not on us. Deliberately not 'warn': the vendor owes
  // a credit note, or the audit report has not arrived yet, and showing those as
  // problems turns an ordinary stage of the process into noise in the queue.
  AWAITING_CREDIT_NOTE: { label: 'Waiting for credit note', tone: 'info' },
  AWAITING_RECEIPT: { label: 'Waiting for audit report', tone: 'plain' },
  RECONCILED: { label: 'Reconciled', tone: 'ok' },
  ACKNOWLEDGED: { label: 'Acknowledged', tone: 'ok' },
}

export function CaseStatusChip({ status, billDeleted }: { status: string; billDeleted?: boolean }) {
  // No case status covers "the bill is gone" — it is not a stage of the
  // reconciliation, it is the thing the reconciliation was about being
  // withdrawn. It outranks whatever the engine last concluded.
  if (billDeleted) {
    return (
      <span className="vc__chip vc__chip--plain vc__chip--xs"
        title="The bill was deleted. The reconciliation and its documents are kept, but there is nothing to pay.">
        Bill deleted
      </span>
    )
  }
  const s = CASE_STATUS[status] ?? { label: status, tone: 'plain' }
  return <span className={`vc__chip vc__chip--${s.tone} vc__chip--xs`}>{s.label}</span>
}
