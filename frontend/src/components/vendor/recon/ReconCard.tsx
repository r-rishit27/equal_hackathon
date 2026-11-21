import { useCallback, useRef, useState } from 'react'
import { useFocusTrap, useScrollLock, useToast } from '../../../ui'
import { clickOrigin } from '../../../utils/clickOrigin'
import ReconCaseView from './ReconCaseView'
import './recon.css'

/**
 * The reconciliation card: one invoice checked against its PO, site audit and
 * delivery proof, opened over any page by `?open=recon:<case_id>` — the same
 * way bill and vendor cards open (components/records/RecordCardHost). Almost
 * full screen, growing out of whatever was clicked; Escape, the scrim and ✕
 * close it, and Back does too.
 */
export default function ReconCard({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const toast = useToast()
  const layer = useRef<HTMLDivElement>(null)
  useFocusTrap(layer, true, onClose)
  useScrollLock(true)
  // Taken once, at open: the card grows out of the row or link that opened it.
  const [origin] = useState(() => clickOrigin() ?? '0px 0px')
  const [dx, dy] = origin.split(' ')
  const notify = useCallback((msg: string, type?: 'error' | 'info') => {
    if (type === 'error') toast.error(msg)
    else toast.success(msg)
  }, [toast])

  return (
    <div className="rk__overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={layer} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Reconciliation" className="rk__frame"
        style={{ '--rk-dx': dx, '--rk-dy': dy } as React.CSSProperties}>
        <ReconCaseView caseId={caseId} notify={notify} onClose={onClose} />
      </div>
    </div>
  )
}
