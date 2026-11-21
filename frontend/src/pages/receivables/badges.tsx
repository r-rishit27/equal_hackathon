import { Sparkles } from 'lucide-react'
import { Badge, type BadgeTone } from '../../ui'
import type { ArInvoiceStatus, PaymentStatus } from '../../api/receivables'

const PAYMENT: Record<PaymentStatus, [string, BadgeTone]> = {
  unmatched: ['Needs match', 'neutral'],
  needs_review: ['Ready to confirm', 'info'],
  partially_applied: ['Part applied', 'info'],
  applied: ['Applied', 'success'],
  exception: ['Follow-up', 'danger'],
  not_receipt: ['Excluded', 'neutral'],
  reversed: ['Bounced', 'danger'],
}

export function PaymentStatusBadge({ status, auto }: { status: PaymentStatus; auto?: boolean }) {
  const [label, tone] = PAYMENT[status] ?? [status, 'neutral']
  if (status === 'applied' && auto) return <Badge tone="brand" icon={<Sparkles size={11} />}>Auto-applied</Badge>
  return <Badge tone={tone}>{label}</Badge>
}

const INVOICE: Record<ArInvoiceStatus, [string, BadgeTone]> = {
  open: ['Open', 'neutral'],
  partially_paid: ['Part-paid', 'info'],
  paid: ['Paid', 'success'],
  disputed: ['On hold', 'danger'],
  written_off: ['Written off', 'neutral'],
  void: ['Void', 'neutral'],
}

export function InvoiceStatusBadge({ status, overdue }: { status: ArInvoiceStatus; overdue?: number | null }) {
  const [label, tone] = INVOICE[status] ?? [status, 'neutral']
  if (overdue && overdue > 0 && (status === 'open' || status === 'partially_paid'))
    return <Badge tone="warn">{label} · {overdue}d overdue</Badge>
  return <Badge tone={tone}>{label}</Badge>
}
