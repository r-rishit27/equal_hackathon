import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  FileText,
  Users,
  Package,
  BarChart2,
  Database,
  Zap,
  Settings,
  HelpCircle,
  LogOut,
  ShieldAlert,
  ListChecks,
  Bot,
  Banknote,
  PanelLeftClose,
  PanelLeftOpen,
  ArrowUpRight,
  ArrowDownLeft,
  HandCoins,
  Receipt,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useReviewCounts } from '../pages/review/useReviewStore'
import { can, ROLE_LABELS } from '../auth/permissions'
import { useEntitlements } from '../auth/EntitlementsContext'
import type { ServiceKey } from '../auth/services'
import { PATHS, pageForPath, ledgerForPath, type Ledger, type NavPage } from '../routes/paths'
import { IconButton } from '../ui'
import './sidebar.css'

interface NavItem {
  icon: React.ElementType
  label: string
  page: NavPage
  requiredPermission?: string | string[]
  /** Hidden unless the tenant is licensed for this service. Orthogonal to role:
   *  permission answers "may this user", licence answers "did this company buy it". */
  requiredService?: ServiceKey
}

interface NavGroup {
  title: string
  items: NavItem[]
}

/**
 * Grouped navigation.
 *
 * The audit found a flat list of ten equal-weight items with Dashboard buried
 * third and no grouping, so daily work, analysis, master data, automation and
 * admin all looked identical. Grouping them also makes the collapsed rail
 * legible: the dividers give the icons positional meaning.
 */
const NAV: NavGroup[] = [
  {
    title: 'Overview',
    items: [
      { icon: LayoutDashboard, label: 'Dashboard', page: 'dashboard', requiredPermission: 'payables.view' },
      // Above Bills on purpose: the queue answers "what needs me now", which is
      // the first question of the day, before "show me everything".
      {
        icon: ListChecks, label: 'Review', page: 'review',
        requiredPermission: 'payables.view', requiredService: 'review_hub',
      },
    ],
  },
  {
    title: 'Payables',
    items: [
      { icon: FileText, label: 'Bills', page: 'bills', requiredPermission: ['payables.view', 'payables.approve'] },
      { icon: Upload, label: 'Upload Invoices', page: 'upload', requiredPermission: 'payables.initiate' },
      { icon: Users, label: 'Vendors', page: 'vendors', requiredPermission: 'payables.view' },
      {
        icon: Banknote, label: 'Payment Hub', page: 'payments',
        requiredPermission: ['payables.view', 'payables.approve'], requiredService: 'disbursement',
      },
    ],
  },
  {
    title: 'Insights',
    items: [
      { icon: Bot, label: 'Reckon Copilot', page: 'copilot', requiredService: 'fact_graph' },
      { icon: Package, label: 'Inventory optimization', page: 'inventory', requiredPermission: 'payables.view', requiredService: 'reports' },
      { icon: BarChart2, label: 'Reports', page: 'reports', requiredPermission: 'payables.view' },
      {
        icon: Database, label: 'Data Extraction', page: 'data-extraction',
        requiredPermission: 'payables.view', requiredService: 'data_extraction',
      },
    ],
  },
  {
    title: 'Automation',
    items: [
      {
        icon: Bot, label: 'Agent Hub', page: 'agent-hub',
        requiredPermission: 'payables.view', requiredService: 'agent_hub',
      },
      {
        icon: ShieldAlert, label: 'Nova', page: 'nova',
        requiredPermission: 'payables.view', requiredService: 'nova_billing',
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      { icon: Zap, label: 'Integrations', page: 'integrations', requiredPermission: 'team.edit_permissions' },
      { icon: Settings, label: 'Settings', page: 'settings', requiredPermission: 'team.edit_permissions' },
    ],
  },
]

/**
 * The receivable side. Same shape as payables, reusing the same pages where the
 * work is the same (upload goes through the same Upload page and OCR, with the
 * reading perspective switched). Same roles as payables: receivables share the
 * payables role model and approval chain for now.
 */
const RECEIVABLE_NAV: NavGroup[] = [
  {
    title: 'Receivables',
    items: [
      { icon: HandCoins, label: 'Cash Application', page: 'ar-cash', requiredPermission: 'payables.view', requiredService: 'receivables' },
      { icon: Receipt, label: 'Invoices', page: 'ar-invoices', requiredPermission: 'payables.view', requiredService: 'receivables' },
      { icon: Upload, label: 'Upload Invoices', page: 'ar-upload', requiredPermission: 'payables.initiate', requiredService: 'receivables' },
      { icon: Users, label: 'Customers', page: 'ar-customers', requiredPermission: 'payables.view', requiredService: 'receivables' },
    ],
  },
  NAV[NAV.length - 1], // Administration is shared
]

const LEDGER_KEY = 'onsum_ledger'
const LEDGER_HOME: Record<Ledger, string> = { payable: PATHS.bills, receivable: PATHS['ar-cash'] }

function rememberedLedger(): Ledger {
  try {
    return localStorage.getItem(LEDGER_KEY) === 'receivable' ? 'receivable' : 'payable'
  } catch {
    return 'payable'
  }
}

const PIN_KEY = 'onsum_sidebar_pinned'
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

  // Pinning is remembered. The audit's finding was that hover-only labels leave
  // a fortnightly approver staring at ten unlabelled glyphs, and that hover
  // never fires on touch at all.
  const [pinned, setPinned] = useState(() => localStorage.getItem(PIN_KEY) === '1')
  const [hovered, setHovered] = useState(false)
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const open = pinned || hovered

  useEffect(() => {
    localStorage.setItem(PIN_KEY, pinned ? '1' : '0')
  }, [pinned])

  useEffect(() => () => {
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
  }, [])

  const isVisible = (item: NavItem) => {
    // has() is false while entitlements are still loading, so a licensed-only item
    // never flashes into view and then disappears.
    if (item.page === 'copilot' && (!user || user.role === 'member')) return false
    if (item.requiredService && !has(item.requiredService)) return false
    if (!item.requiredPermission) return true
    if (!user) return false
    const perms = Array.isArray(item.requiredPermission) ? item.requiredPermission : [item.requiredPermission]
    return perms.some(p => can(user.role, p as Parameters<typeof can>[1]))
  }

  // The side of the books follows the URL; shared pages (settings) keep the last one.
  const arLicensed = has('receivables')
  const ledger: Ledger = !arLicensed ? 'payable' : (ledgerForPath(location.pathname) ?? rememberedLedger())
  useEffect(() => {
    try { localStorage.setItem(LEDGER_KEY, ledger) } catch { /* private mode */ }
  }, [ledger])

  const nav = ledger === 'receivable' ? RECEIVABLE_NAV : NAV
  const groups = nav.map(g => ({ ...g, items: g.items.filter(isVisible) })).filter(g => g.items.length > 0)

  const onEnter = () => {
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    setHovered(true)
  }
  const onLeave = () => {
    leaveTimer.current = setTimeout(() => setHovered(false), 120)
  }

  return (
    // The landmark itself is not a control: these handlers only widen the rail.
    // Every actionable item inside is a real <button>, and the rail is fully
    // usable (labels visible) without any pointer interaction once pinned.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- widens the rail only; all controls inside are real buttons
    <aside
      className={`sb${open ? ' sb--open' : ''}`}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      // Expand while anything inside has keyboard focus, so a Tab user can read
      // the labels they are moving through.
      onFocus={() => setHovered(true)}
      onBlur={e => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setHovered(false)
      }}
      aria-label="Main"
    >
      <div className="sb__logo">
        <span className="sb__logo-mark" aria-hidden="true">
          <img src="/brand/reckon-mark.svg" alt="" />
        </span>
        <span className="sb__logo-word">
          <img src="/brand/reckon-wordmark-dark.svg" alt="Reckon.ai" />
        </span>
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

      <nav className="sb__nav">
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
                      onClick={() => navigate(PATHS[page])}
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
            <IconButton label="Sign out" icon={<LogOut size={14} />} size="sm" tone="danger" onClick={logout} />
          </div>
        )}

        <div className="sb__pin">
          <IconButton
            label={pinned ? 'Unpin navigation' : 'Keep navigation open'}
            icon={pinned ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
            size="sm"
            onClick={() => setPinned(p => !p)}
          />
        </div>
      </div>
    </aside>
  )
}
