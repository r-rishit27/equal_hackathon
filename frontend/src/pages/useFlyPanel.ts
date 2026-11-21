/**
 * The full-screen viewers' motion, shared so every document opens the same way.
 *
 * The panel flies out of the element it was opened from and settles in the
 * centre of the screen (a FLIP: it is laid out at its final size, then
 * transformed back onto the source's rectangle and animated to identity). Only
 * once it has nearly landed does the rest of the screen dim and blur, so the
 * eye follows the document first and the backdrop second. Closing runs the
 * same thing in reverse and puts the panel back where it came from.
 */
import { useCallback, useLayoutEffect, useRef } from 'react'

const FLY_MS = 680
const BLUR_MS = 460
const EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)'
const EASE_IN_OUT = 'cubic-bezier(0.65, 0, 0.35, 1)'

function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

type Box = { left: number; top: number; width: number; height: number }

/**
 * Where the panel sits in layout, ignoring any transform on it. Measuring with
 * getBoundingClientRect would include a running animation, so a second
 * measurement mid-flight (React re-running the effect in dev, or closing before
 * the page has landed) would compute a flight from the side pane to itself.
 * The panel's offsetParent is the fixed, full-screen .bpf, so these are
 * viewport coordinates.
 */
function layoutBox(el: HTMLElement): Box {
  return { left: el.offsetLeft, top: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight }
}

/** The transform that lays `to` exactly over `from`. */
function flipTransform(from: Box, to: Box) {
  const s = Math.min(from.width / to.width, from.height / to.height)
  const dx = (from.left + from.width / 2) - (to.left + to.width / 2)
  const dy = (from.top + from.height / 2) - (to.top + to.height / 2)
  return `translate(${dx}px, ${dy}px) scale(${s})`
}

/** Refs for the panel and its backdrop, and a `close` that animates out before calling onClose. */
export function useFlyPanel(sourceRef: React.RefObject<HTMLElement>, onClose: () => void) {
  const panelRef = useRef<HTMLDivElement>(null)
  const backdropRef = useRef<HTMLDivElement>(null)
  const closing = useRef(false)

  // ── Enter ────────────────────────────────────────────────────────────────
  useLayoutEffect(() => {
    const panel = panelRef.current, backdrop = backdropRef.current
    if (!panel || !backdrop) return
    if (prefersReducedMotion()) {
      backdrop.style.opacity = '1'
      return
    }
    const from = sourceRef.current?.getBoundingClientRect()
    const to = layoutBox(panel)
    const fly = panel.animate(
      [
        { transform: from ? flipTransform(from, to) : 'translateX(60vw)', opacity: 0.85, borderRadius: '6px' },
        { transform: 'none', opacity: 1, borderRadius: '16px' },
      ],
      { duration: FLY_MS, easing: EASE_OUT, fill: 'both' },
    )
    // The blur comes in as the page is landing, not alongside its take-off.
    const blur = backdrop.animate(
      [
        { opacity: 0, backdropFilter: 'blur(0px)', WebkitBackdropFilter: 'blur(0px)' },
        { opacity: 1, backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' },
      ],
      { duration: BLUR_MS, delay: FLY_MS * 0.55, easing: EASE_IN_OUT, fill: 'both' },
    )
    // React runs this twice in dev (StrictMode); without the cancel the second
    // run would stack on top of the first.
    return () => { fly.cancel(); blur.cancel() }
  }, [sourceRef])

  // ── Exit ─────────────────────────────────────────────────────────────────
  const close = useCallback(() => {
    if (closing.current) return
    closing.current = true
    const panel = panelRef.current, backdrop = backdropRef.current
    if (!panel || !backdrop || prefersReducedMotion()) { onClose(); return }
    const from = sourceRef.current?.getBoundingClientRect()
    const to = layoutBox(panel)
    // Single end keyframes: each animation picks up from wherever the panel and
    // backdrop are right now, so closing mid-entrance turns around smoothly.
    backdrop.animate(
      [
        { opacity: 0, backdropFilter: 'blur(0px)', WebkitBackdropFilter: 'blur(0px)' },
      ],
      { duration: BLUR_MS * 0.7, easing: EASE_IN_OUT, fill: 'both' },
    )
    panel.animate(
      [
        { transform: from ? flipTransform(from, to) : 'translateX(60vw)', opacity: 0.85, borderRadius: '6px' },
      ],
      { duration: FLY_MS * 0.8, delay: BLUR_MS * 0.25, easing: EASE_IN_OUT, fill: 'both' },
    ).finished.then(onClose, onClose)
  }, [onClose, sourceRef])

  return { panelRef, backdropRef, close }
}
