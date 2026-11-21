import { CheckCircle2, FileText } from 'lucide-react'
import { Button, Card, CardBody, PageHeader } from '../ui'
import type { IngestResult } from '../api/invoices'

interface Props {
  result: IngestResult
  onNew: () => void
  onGoToBills: () => void
}

export default function DonePage({ result, onNew, onGoToBills }: Props) {
  return (
    <div className="workspace-complete">
      <Card>
        <CardBody>
          <CheckCircle2 className="workspace-complete__mark" size={32} aria-hidden="true" />
          <PageHeader title="Invoice saved" sub="The reviewed invoice is ready in Bills." />
          <dl className="workspace-complete__details">
            <div><dt>Upload ID</dt><dd><code>{result.upload_id}</code></dd></div>
            <div><dt>Bill ID</dt><dd><code>{result.stg_bill_id}</code></dd></div>
            <div><dt>Line items</dt><dd>{result.line_items_count}</dd></div>
          </dl>
          <div className="workspace-complete__actions">
            <Button onClick={onNew}>Process another invoice</Button>
            <Button variant="primary" iconLeft={<FileText size={16} aria-hidden="true" />} onClick={onGoToBills}>
              Go to Bills
            </Button>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}
