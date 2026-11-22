import {
  LayoutDashboard, Upload, FileText, Users, Package, BarChart2, Database,
  Zap, Settings, ShieldAlert, ListChecks, Workflow, Bot, Banknote, HandCoins, Receipt, LineChart,
} from 'lucide-react'
import { can, type Permission, type Role } from '../auth/permissions'
import type { ServiceKey } from '../auth/services'
import type { Ledger, NavPage } from '../routes/paths'

export interface NavItem {
  icon: React.ElementType
  label: string
  page: NavPage
  requiredPermission?: Permission | Permission[]
  /** Hidden unless the tenant is licensed for this service. Orthogonal to role:
   *  permission answers "may this user", licence answers "did this company buy it". */
  requiredService?: ServiceKey
  requiredRoles?: readonly Role[]
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
export const COPILOT_ROLES: readonly Role[] = ['admin', 'finance_controller', 'accountant', 'approver', 'auditor']

const NOVA: NavItem = {
  icon: ShieldAlert, label: 'Nova', page: 'nova',
  requiredPermission: 'payables.view', requiredService: 'nova_billing',
}

const NAV: NavGroup[] = [
  {
    title: 'Overview',
    items: [
      { icon: LayoutDashboard, label: 'Dashboard', page: 'dashboard', requiredPermission: 'payables.view', requiredService: 'reports' },
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
      { icon: FileText, label: 'Bills', page: 'bills', requiredPermission: ['payables.view', 'payables.approve'], requiredService: 'bills' },
      { icon: Upload, label: 'Upload Invoices', page: 'upload', requiredPermission: 'payables.initiate', requiredService: 'upload_ocr' },
      { icon: Users, label: 'Vendors', page: 'vendors', requiredPermission: 'payables.view', requiredService: 'vendors' },
      {
        icon: Banknote, label: 'Payment Hub', page: 'payments',
        requiredPermission: ['payables.view', 'payables.approve'], requiredService: 'disbursement',
      },
    ],
  },
  {
    title: 'Insights',
    items: [
      { icon: Bot, label: 'Reckon Copilot', page: 'copilot', requiredService: 'fact_graph', requiredRoles: COPILOT_ROLES },
      { icon: Package, label: 'Inventory planning', page: 'inventory', requiredPermission: 'payables.view', requiredService: 'reports' },
      { icon: LineChart, label: 'Cash flow forecast', page: 'cash-forecast', requiredPermission: 'accounting.view',
        requiredService: 'cash_forecast', requiredRoles: ['admin', 'finance_controller', 'accountant', 'auditor'] },
      { icon: BarChart2, label: 'Reports', page: 'reports', requiredPermission: 'payables.view', requiredService: 'reports' },
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
      { icon: Workflow, label: 'CFO Orchestrator', page: 'cfo-orchestrator',
        requiredService: 'agent_hub', requiredRoles: ['admin', 'finance_controller'] },
      NOVA,
    ],
  },
  {
    title: 'Administration',
    items: [
      { icon: Zap, label: 'Integrations', page: 'integrations', requiredRoles: ['admin'] },
      { icon: Settings, label: 'Settings', page: 'settings', requiredRoles: ['admin'], requiredService: 'settings' },
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
      { icon: Receipt, label: 'Sales Invoices', page: 'ar-invoices', requiredPermission: 'payables.view', requiredService: 'receivables' },
      { icon: Upload, label: 'Upload Sales Invoices', page: 'ar-upload', requiredPermission: 'payables.initiate', requiredService: 'receivables' },
      { icon: Users, label: 'Customers', page: 'ar-customers', requiredPermission: 'payables.view', requiredService: 'receivables' },
    ],
  },
  { title: 'Automation', items: [NOVA] },
  NAV[NAV.length - 1], // Administration is shared
]

export function workspaceNavigation(role: Role | undefined, has: (service: ServiceKey) => boolean, ledger?: Ledger) {
  if (!role) return []
  const groups = ledger === 'payable' ? NAV : ledger === 'receivable'
    ? RECEIVABLE_NAV : [...NAV.slice(0, -1), RECEIVABLE_NAV[0], NAV[NAV.length - 1]]
  return groups.map(group => ({
    ...group,
    items: group.items.filter(item => {
      if (item.requiredService && !has(item.requiredService)) return false
      if (item.requiredRoles && !item.requiredRoles.includes(role)) return false
      const permission = item.requiredPermission
      return !permission || (Array.isArray(permission) ? permission : [permission]).some(key => can(role, key))
    }),
  })).filter(group => group.items.length > 0)
}
