import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { HelpCircle, LogOut, PanelLeftClose, PanelLeftOpen, ArrowUpRight, ArrowDownLeft, Search } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useReviewCounts } from '../pages/review/useReviewStore'
import { ROLE_LABELS } from '../auth/permissions'
import { useEntitlements } from '../auth/EntitlementsContext'
import { workspaceNavigation } from './workspaceNavigation'
import { PATHS, pageForPath, ledgerForPath, type Ledger } from '../routes/paths'
import { IconButton } from '../ui'
import './sidebar.css'

const LEDGER_KEY = 'onsum_ledger'
const LEDGER_HOME: Record<Ledger, string> = { payable: PATHS.bills, receivable: PATHS['ar-cash'] }

function rememberedLedger(): Ledger {
  try {
    return localStorage.getItem(LEDGER_KEY) === 'receivable' ? 'receivable' : 'payable'
  } catch {
    return 'payable'
  }
}

const SIDEBAR_KEY = 'reckon_sidebar_expanded'
const SUPPORT_URL = 'mailto:support@onsumm.ai?subject=Reckon.ai%20support%20request'

export interface SidebarProps {
  /** Count shown against Bills — how many need this user's action. */
  pendingCount?: number
}

export default function Sidebar({ pendingCount = 0 }: SidebarProps) {
  // Straight from the review store rather than a prop: the badge has to tick
  // down the moment a finding is resolved in the drawer, and prop-drilling
  // that from App.tsx would rebuild the whole shell on every update.
  const reviewCounts = useReviewCounts()
  const { user, logout } = useAuth()
  const { has } = useEntitlements()
  const navigate = useNavigate()
  const location = useLocation()
  const activePage = pageForPath(location.pathname)

  const [open, setOpen] = useState(() => localStorage.getItem(SIDEBAR_KEY) !== '0')
  const [query, setQuery] = useState('')

  useEffect(() => {
    localStorage.setItem(SIDEBAR_KEY, open ? '1' : '0')
  }, [open])

  // The side of the books follows the URL; shared pages (settings) keep the last one.
  const arLicensed = has('receivables')
  const ledger: Ledger = !arLicensed ? 'payable' : (ledgerForPath(location.pathname) ?? rememberedLedger())
  useEffect(() => {
    try { localStorage.setItem(LEDGER_KEY, ledger) } catch { /* private mode */ }
  }, [ledger])

  const nav = workspaceNavigation(user?.role, has, ledger)
  const search = query.trim().toLowerCase()
  const groups = nav.map(group => ({
    ...group,
    items: group.items.filter(item => item.label.toLowerCase().includes(search)),
  })).filter(group => group.items.length > 0)

  return (
    <aside
      className={`sb${open ? ' sb--open' : ''}`}
      aria-label="Main"
    >
      <div className="sb__logo">
        <span className="sb__logo-mark" aria-hidden="true">
          <img src="/brand/reckon-mark.svg" alt="" />
        </span>
        <span className="sb__logo-word">
          <img src="/brand/reckon-wordmark-dark.svg" alt="Reckon.ai" />
        </span>
        <div className="sb__pin">
          <IconButton
            label={open ? 'Collapse navigation' : 'Expand navigation'}
            icon={open ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
            size="sm"
            onClick={() => { setOpen(!open); setQuery('') }}
          />
        </div>
      </div>

      {arLicensed && (
        <div className="sb__ledger" role="group" aria-label="Side of the books">
          {(['payable', 'receivable'] as const).map(l => {
            const Icon = l === 'payable' ? ArrowUpRight : ArrowDownLeft
            const on = ledger === l
            return (
              <button
                key={l}
                type="button"
                className={`sb__ledger-btn${on ? ' sb__ledger-btn--on' : ''}`}
                aria-pressed={on}
                title={l === 'payable' ? 'Payables — money we pay' : 'Receivables — money we collect'}
                onClick={() => { if (!on) navigate(LEDGER_HOME[l]) }}
              >
                <Icon size={14} aria-hidden="true" />
                <span className="sb__ledger-label">{l === 'payable' ? 'Payables' : 'Receivables'}</span>
              </button>
            )
          })}
        </div>
      )}

      {open && (
        <label className="sb__search">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            aria-label="Filter workspace pages"
            placeholder="Find a page"
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        </label>
      )}
      <nav className="sb__nav" aria-label="Workspace pages">
        {groups.length === 0 && search && <p className="sb__no-results" role="status">No matching pages</p>}
        {groups.map(group => (
          <div className="sb__group" key={group.title}>
            <div className="sb__group-title" aria-hidden="true">
              {group.title}
            </div>
            <ul className="sb__list" aria-label={group.title}>
              {group.items.map(({ icon: Icon, label, page }) => {
                const active = page === activePage
                // Bills counts what is waiting on you; Review counts what is wrong.
                // Deliberately two signals, not one.
                const badge =
                  page === 'bills' ? (pendingCount > 0 ? pendingCount : 0)
                  : page === 'review' ? (reviewCounts?.total_actionable ?? 0)
                  : 0
                return (
                  <li key={page}>
                    <button
                      className={`sb__item${active ? ' sb__item--active' : ''}`}
                      onClick={() => { setQuery(''); navigate(PATHS[page]) }}
                      title={open ? undefined : label}
                      aria-current={active ? 'page' : undefined}
                    >
                      <span className="sb__item-icon">
                        <Icon size={17} strokeWidth={active ? 2.2 : 1.8} aria-hidden="true" />
                        {badge > 0 && !open && <span className="sb__dot" aria-hidden="true" />}
                      </span>
                      <span className="sb__item-label">{label}</span>
                      {badge > 0 && (
                        <span className="sb__count">
                          {badge > 99 ? '99+' : badge}
                          <span className="sr-only"> items need your action</span>
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="sb__footer">
        <a className="sb__help" href={SUPPORT_URL}>
          <span className="sb__item-icon">
            <HelpCircle size={16} aria-hidden="true" />
          </span>
          <span className="sb__item-label">Contact support</span>
        </a>

        {user && (
          <div className="sb__user">
            <div className="sb__avatar" aria-hidden="true">
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div className="sb__user-meta">
              <div className="sb__user-name">{user.name}</div>
              <div className="sb__user-role">{ROLE_LABELS[user.role]}</div>
            </div>
            {open && <IconButton label="Sign out" icon={<LogOut size={14} />} size="sm" tone="danger" onClick={logout} />}
          </div>
        )}

      </div>
    </aside>
  )
}
