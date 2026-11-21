/**
 * Full-screen view of a bill's PDF.
 *
 * The page flies out of the side pane it was sitting in and settles in the
 * centre of the screen (a FLIP: it is laid out at its final size, then
 * transformed back onto the pane's rectangle and animated to identity). Only
 * once it has nearly landed does the rest of the screen dim and blur, so the
 * eye follows the document first and the backdrop second. Closing runs the
 * same thing in reverse and puts the page back where it came from.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Page } from 'react-pdf'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { ChevronLeft, ChevronRight, Minimize2, RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react'
import { usePinchZoom } from './usePinchZoom'
import { useFlyPanel } from './useFlyPanel'
import './billPdfFullscreen.css'

export function BillPdfFullscreen({
  pdf, sourceRef, pageNum, numPages, onPage, onClose, label = 'Bill document, full screen', error = false, rotate = 0, actions,
}: {
  /**
   * Already parsed by the side pane, so nothing is loaded again here. Null
   * while a caller is still loading it: the panel flies out anyway with a blank
   * sheet, and the page fades in over it, so the wait is part of the motion.
   */
  pdf: PDFDocumentProxy | null
  /** The pane the PDF normally sits in; the page flies out of, and back to, it. */
  sourceRef: React.RefObject<HTMLElement>
  pageNum: number
  numPages: number
  onPage: (n: number) => void
  onClose: () => void
  /** What the screen reader announces; other documents reuse this viewer. */
  label?: string
  /** The document couldn't be loaded: say so in the panel. */
  error?: boolean
  /** Degrees clockwise, carried over from the side pane. */
  rotate?: number
  /** Extra buttons for the toolbar's right side, before Close (e.g. Parsed info). */
  actions?: ReactNode
}) {
  const { panelRef, backdropRef, close } = useFlyPanel(sourceRef, onClose)
  const bodyRef = useRef<HTMLDivElement>(null)
  const [bodyW, setBodyW] = useState(0)
  const [zoom, setZoom] = useState(0)
  const fitW = bodyW - 64
  const pageW = Math.max(240, fitW + zoom)
  const onRendered = usePinchZoom(bodyRef, pageW, w => setZoom(w - fitW))
  // The page is shown once its canvas has painted, never as an empty box.
  const [painted, setPainted] = useState(false)
  useEffect(() => { setPainted(false) }, [pdf])
  const onPainted = useCallback(() => { onRendered(); setPainted(true) }, [onRendered])


  // Esc closes the full-screen view only, not the bill behind it: the bill
  // modal listens on window in the bubble phase, so stop it here in capture.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // A view opened from this one (Parsed info) closes first.
      if (document.querySelector('[data-parsed-layer]')) return
      e.stopPropagation()
      close()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [close])

  useEffect(() => {
    const el = bodyRef.current; if (!el) return
    const ro = new ResizeObserver(() => setBodyW(el.clientWidth))
    ro.observe(el); setBodyW(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  return createPortal(
    <div className="bpf" role="dialog" aria-modal="true" aria-label={label}>
      <div className="bpf__backdrop" ref={backdropRef} onClick={close} />
      <div className="bpf__panel" ref={panelRef}>
        <div className="bpf__bar">
          <div className="bpf__group">
            <button className="bpf__ctrl" onClick={close} title="Exit full screen" aria-label="Exit full screen">
              <Minimize2 size={15} />
            </button>
            <div className="bpf__sep" />
            <button className="bpf__ctrl" onClick={() => setZoom(z => z + 120)} aria-label="Zoom in"><ZoomIn size={15} /></button>
            <button className="bpf__ctrl" onClick={() => setZoom(z => z - 120)} aria-label="Zoom out"><ZoomOut size={15} /></button>
            <button className="bpf__ctrl" onClick={() => setZoom(0)} aria-label="Reset zoom"><RotateCcw size={15} /></button>
          </div>
          <div className="bpf__group">
            {numPages > 1 && (
              <button className="bpf__ctrl" disabled={pageNum <= 1} onClick={() => onPage(pageNum - 1)} aria-label="Previous page">
                <ChevronLeft size={15} />
              </button>
            )}
            {numPages > 0 && <span className="bpf__page tnum">{`Page ${pageNum} of ${numPages}`}</span>}
            {numPages > 1 && (
              <button className="bpf__ctrl" disabled={pageNum >= numPages} onClick={() => onPage(pageNum + 1)} aria-label="Next page">
                <ChevronRight size={15} />
              </button>
            )}
            {actions && <><div className="bpf__sep" />{actions}</>}
            <div className="bpf__sep" />
            <button className="bpf__ctrl" onClick={close} aria-label="Close"><X size={16} /></button>
          </div>
        </div>
        <div className="bpf__body" ref={bodyRef} aria-busy={!painted && !error}>
          {bodyW > 0 && (
            <div className="bpf__stage" style={{ width: pageW, minHeight: painted ? undefined : Math.round(pageW * 1.414) }}>
              {pdf && !error && (
                <Page
                  className={`bpf__pdfpage${painted ? ' is-in' : ''}`}
                  pdf={pdf}
                  pageNumber={pageNum}
                  rotate={rotate}
                  width={pageW}
                  renderAnnotationLayer={false}
                  renderTextLayer={false}
                  onRenderSuccess={onPainted}
                />
              )}
              {/* Stands in for the page until it paints, then fades out under it. */}
              <div className={`bpf__sheet${painted ? ' is-out' : ''}${error ? ' is-error' : ''}`} aria-hidden={!error}>
                {error
                  ? <span className="bpf__sheet-msg">Couldn’t open this PDF.</span>
                  : <><i /><i /><i /><i /><i /><i /></>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
