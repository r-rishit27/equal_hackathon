import { useEffect, useState } from 'react'
import axios from 'axios'
interface Bill {
  supplier_id?: string | null
  invoice_id: string
  invoice_number: string | null
  vendor_name: string | null
}

export type ControlState = 'ready' | 'review' | 'blocked'

interface Check {
  id: string
  label: string
  state: ControlState
  items?: { label: string; state: ControlState; detail: string }[]
  detail: string
}

const path = '/api/agents/invoice-processing'

export function useInvoiceChecks(brandId?: string, workflow: 'check' | 'cfo' = 'check') {
  const [bills, setBills] = useState<Bill[] | null>(null)
  const [bill, setBill] = useState('')
  const [checks, setChecks] = useState<Check[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    axios.get<Bill[]>(path, { params: { brand_id: brandId }, signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) setBills(data) })
      .catch(() => {
        if (!controller.signal.aborted) setError('Could not load recent invoices.')
      })
    return () => controller.abort()
  }, [brandId])

  async function run() {
    if (!bill || busy) return
    setBusy(true)
    setError('')
    setChecks([])
    try {
      const { data } = await axios.post<{ checks: Check[] }>(
        `${path}/${encodeURIComponent(bill)}/${workflow}`, null, { params: { brand_id: brandId } },
      )
      setChecks(data.checks)
    } catch {
      setError('Could not check this invoice. Try again.')
    } finally {
      setBusy(false)
    }
  }

  function selectBill(id: string) {
    setBill(id)
    setChecks([])
    setError('')
  }
  return { bills, bill, selectBill, checks, busy, error, run }
}
