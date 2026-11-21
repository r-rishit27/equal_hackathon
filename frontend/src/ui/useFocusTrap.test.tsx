import { describe, it, expect, vi } from 'vitest'
import { useRef } from 'react'
import { createPortal } from 'react-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useFocusTrap } from './useFocusTrap'

function Layer({ name, onEscape, portal, children }: { name: string; onEscape: () => void; portal?: boolean; children?: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useFocusTrap(ref, true, onEscape)
  const box = <div ref={ref} role="dialog" aria-label={name}><button>{name} first</button><button>{name} last</button>{children}</div>
  return portal ? createPortal(box, document.body) : box
}

describe('useFocusTrap with a dialog opened from a dialog', () => {
  it('lets only the newest one handle Escape and Tab, even when it is portalled out', async () => {
    const outer = vi.fn(), inner = vi.fn()
    // Opened the way it happens in the app: the viewer after the card, on a click.
    const { rerender } = render(<Layer name="card" onEscape={outer} />)
    rerender(<Layer name="card" onEscape={outer}><Layer name="viewer" portal onEscape={inner} /></Layer>)
    // Tab cycles inside the viewer, not pulled back into the card.
    expect(screen.getByRole('button', { name: 'viewer first' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'viewer last' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'viewer first' })).toHaveFocus()
    // Escape closes the viewer only.
    await userEvent.keyboard('{Escape}')
    expect(inner).toHaveBeenCalledTimes(1)
    expect(outer).not.toHaveBeenCalled()
  })

  it('hands the keys back to the one beneath when the newest closes', async () => {
    const outer = vi.fn()
    const { rerender } = render(<Layer name="card" onEscape={outer} />)
    rerender(<Layer name="card" onEscape={outer}><Layer name="viewer" portal onEscape={() => {}} /></Layer>)
    rerender(<Layer name="card" onEscape={outer} />)
    await userEvent.keyboard('{Escape}')
    expect(outer).toHaveBeenCalledTimes(1)
  })
})
