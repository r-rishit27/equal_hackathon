import { useEffect, type RefObject } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * Confine Tab focus to a container while it is open, then hand focus back to
 * wherever it came from.
 *
 * The audit found four modal surfaces (bill detail, dashboard drill-down, and
 * two nested reconciliation dialogs) with no focus trap, no focus restoration
 * and — for the nested ones — no Escape handler. A keyboard user tabbing inside
 * an open modal walked straight out into the page behind it.
 */
// Open traps, newest last. Only the newest handles keys: a dialog opened from a
// dialog (often portalled outside it) must not have its Escape close the one
// beneath, or its Tab pulled back into it.
const traps: symbol[] = []

export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, onEscape?: () => void) {
  useEffect(() => {
    if (!active) return
    const node = ref.current
    if (!node) return

    const previouslyFocused = document.activeElement as HTMLElement | null
    const me = Symbol('trap')
    traps.push(me)

    // Focus the first control, or the container itself if there is none.
    const focusables = () => Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
    const controls = focusables()
    const first = controls.find(control => control.hasAttribute('data-autofocus')) ?? controls[0]
    if (first) first.focus()
    else {
      node.setAttribute('tabindex', '-1')
      node.focus()
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (traps[traps.length - 1] !== me) return
      if (e.key === 'Escape' && onEscape) {
        e.stopPropagation()
        e.preventDefault()
        onEscape()
        return
      }
      if (e.key !== 'Tab') return

      const items = focusables()
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const firstItem = items[0]
      const lastItem = items[items.length - 1]

      // Wrap at both ends. Also catches the case where focus has escaped the
      // container entirely (e.g. it was moved programmatically).
      if (!node.contains(document.activeElement)) {
        e.preventDefault()
        firstItem.focus()
      } else if (e.shiftKey && document.activeElement === firstItem) {
        e.preventDefault()
        lastItem.focus()
      } else if (!e.shiftKey && document.activeElement === lastItem) {
        e.preventDefault()
        firstItem.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      const i = traps.lastIndexOf(me)
      if (i >= 0) traps.splice(i, 1)
      // Returning focus is what lets a keyboard user carry on where they were.
      previouslyFocused?.focus?.()
    }
  }, [ref, active, onEscape])
}

/** Prevent the page behind a modal from scrolling. */
export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [active])
}
