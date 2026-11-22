import {
  Bot, LayoutDashboard, Inbox, MessageSquare, Mail, CalendarDays, CheckSquare, NotebookPen, Presentation,
  Target, Building2, FileSignature, Network, FileText, Workflow, Receipt, Scale, ArrowLeftRight, LayoutGrid,
  Settings, Palette, Ellipsis, type LucideIcon,
} from "lucide-react";
import { emails, inbox, invoices, leads, tasks } from "@/lib/data";

export const APP_NAME = "Northstar";
export const WORKSPACE = "Lumen Works";

export type NavItem = { href: string; label: string; icon: LucideIcon; count?: number };
export type NavGroup = { id: string; label: string | null; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    id: "top", label: null, items: [
      { href: "/home", label: "Dashboard", icon: LayoutDashboard },
      { href: "/inbox", label: "Inbox", icon: Inbox, count: inbox.filter((i) => i.unread).length },
      { href: "/messages", label: "Messages", icon: MessageSquare, count: 7 },
    ],
  },
  {
    id: "space", label: "Your Space", items: [
      { href: "/emails", label: "Emails", icon: Mail, count: emails.filter((e) => e.unread).length },
      { href: "/meetings", label: "Meetings", icon: CalendarDays },
      { href: "/tasks", label: "Tasks", icon: CheckSquare, count: tasks.filter((t) => !t.done && t.due <= "2026-10-26").length },
      { href: "/notes", label: "Notes", icon: NotebookPen },
      { href: "/whiteboards", label: "Whiteboards", icon: Presentation },
    ],
  },
  {
    id: "company", label: "Company", items: [
      { href: "/leads", label: "Leads", icon: Target, count: leads.filter((l) => l.stage === "New").length },
      { href: "/customers", label: "Customers", icon: Building2 },
      { href: "/contracts", label: "Contracts", icon: FileSignature },
      { href: "/network", label: "Network", icon: Network },
      { href: "/documents", label: "Documents", icon: FileText },
      { href: "/workflows", label: "Workflows", icon: Workflow },
    ],
  },
  {
    id: "finance", label: "Finance", items: [
      { href: "/invoices", label: "Invoices", icon: Receipt, count: invoices.filter((i) => i.status === "Overdue").length },
      { href: "/balances", label: "Balances", icon: Scale },
      { href: "/transactions", label: "Transactions", icon: ArrowLeftRight },
    ],
  },
  {
    id: "more", label: null, items: [
      { href: "/apps", label: "App Library", icon: LayoutGrid },
      { href: "/settings#theme", label: "Themes", icon: Palette },
      { href: "/settings", label: "Settings", icon: Settings },
      { href: "/settings#more", label: "More", icon: Ellipsis },
    ],
  },
];

export const AGENTS_ITEM: NavItem = { href: "/", label: "Agents", icon: Bot };
export const ALL_NAV = [AGENTS_ITEM, ...NAV.flatMap((g) => g.items)];
