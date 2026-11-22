"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight, ChevronDown, ChevronsUpDown, Ellipsis, PanelLeft, Search, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Avatar, cn, Count, Kbd } from "@/components/ui";
import { ME } from "@/lib/data";
import { AGENTS_ITEM, NAV, WORKSPACE, type NavItem } from "./nav";
import { useShell } from "./ShellProvider";

function Item({ item, collapsed, active }: { item: NavItem; collapsed: boolean; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} title={collapsed ? item.label : undefined}
      className={cn("flex h-control w-full items-center gap-2 overflow-hidden rounded-md py-1.5 pr-2 pl-1.5 transition-colors hover:bg-sidebarActive", active && "bg-sidebarActive")}>
      <Icon className={cn("size-4 shrink-0", active ? "text-textPrimary" : "text-textMuted")} strokeWidth={1.5} />
      {!collapsed && (
        <>
          <span className={cn("grow truncate text-label leading-5 whitespace-nowrap", active ? "font-medium text-textPrimary" : "text-textSecondary")}>{item.label}</span>
          {item.href === "/" ? <span className="flex gap-0.5"><Kbd outline>⌘</Kbd><Kbd outline>J</Kbd></span> : item.count ? <Count n={item.count} /> : null}
        </>
      )}
    </Link>
  );
}

export function Sidebar() {
  const path = usePathname();
  const { collapsed, setCollapsed, setPaletteOpen, mobileNav, setMobileNav } = useShell();
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const isActive = (href: string) => (href.includes("#") ? false : href === "/" ? path === "/" : path === href || path.startsWith(href + "/"));

  const body = (isCollapsed: boolean) => (
    <>
      <div className="flex h-toolbar shrink-0 items-center gap-1 px-2">
        {!isCollapsed && (
          <button className="flex min-w-0 grow items-center gap-2 rounded-md px-1.5 py-1.5 transition-colors hover:bg-sidebarActive">
            <Avatar name={WORKSPACE} hue={330} size={16} square />
            <span className="grow truncate text-left text-label leading-5 font-medium">{WORKSPACE}</span>
            <ChevronsUpDown className="size-3.5 text-textMuted" />
          </button>
        )}
        <button onClick={() => (mobileNav ? setMobileNav(false) : setCollapsed(!collapsed))} aria-label="Toggle sidebar" className="flex size-control shrink-0 items-center justify-center rounded-md hover:bg-sidebarActive">
          {mobileNav ? <X className="size-4 text-textMuted" /> : <PanelLeft className="size-4 text-textMuted" strokeWidth={1.5} />}
        </button>
      </div>
      <div className="flex min-h-0 grow flex-col gap-4 overflow-y-auto px-2 pt-1.5 pb-2">
        <button onClick={() => setPaletteOpen(true)} title="Search (⌘K)" className="flex h-control w-full cursor-text items-center gap-2 rounded-md border border-borderDark bg-appBg px-1.5">
          <Search className="size-4 shrink-0 text-textMuted" strokeWidth={1.5} />
          {!isCollapsed && <><span className="grow text-left text-label text-textMuted">Search</span><span className="flex gap-0.5"><Kbd>⌘</Kbd><Kbd>K</Kbd></span></>}
        </button>
        <nav className="flex flex-col gap-0.5" aria-label="Main">
          <Item item={AGENTS_ITEM} collapsed={isCollapsed} active={isActive("/")} />
          {NAV[0].items.map((i) => <Item key={i.href} item={i} collapsed={isCollapsed} active={isActive(i.href)} />)}
        </nav>
        {NAV.slice(1).map((g) => (
          <div key={g.id} role="group" aria-label={g.label ?? undefined} className="flex flex-col gap-2">
            {g.label && !isCollapsed && (
              <button onClick={() => setClosed((c) => ({ ...c, [g.id]: !c[g.id] }))} className="group flex items-center px-1.5">
                <span className="text-caption leading-4 text-textMuted group-hover:text-textSecondary">{g.label}</span>
                <ChevronDown className={cn("ml-1 size-3 text-textMuted transition-transform", closed[g.id] && "-rotate-90")} />
              </button>
            )}
            {g.label && isCollapsed && <div className="mx-auto h-px w-4 bg-borderDark" />}
            {!closed[g.id] && (
              <div className="flex flex-col gap-0.5">
                {g.items.map((i) => <Item key={i.href} item={i} collapsed={isCollapsed} active={isActive(i.href)} />)}
              </div>
            )}
          </div>
        ))}
      </div>
      {!isCollapsed && (
        <div className="shrink-0 px-2 pb-2">
          <button className="group mb-2 flex h-control w-full items-center gap-2 rounded-md bg-gradient-to-r from-fuchsia-500 via-violet-500 to-purple-500 px-2 text-label font-medium text-white shadow-sm transition-[filter] hover:brightness-110">
            <Sparkles className="size-4" strokeWidth={1.5} />
            <span className="grow text-left">Upgrade to Pro</span>
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          <div className="flex items-center gap-2 rounded-md px-1.5 py-1.5 hover:bg-sidebarActive">
            <span className="relative"><Avatar name={ME.name} hue={ME.hue} size={18} /><span className="absolute -right-0.5 -bottom-0.5 size-2 rounded-full border-[1.5px] border-sidebarBg bg-green-500" /></span>
            <span className="grow truncate text-label">{ME.name}</span>
            <Ellipsis className="size-4 text-textMuted" />
          </div>
        </div>
      )}
    </>
  );

  return (
    <>
      <aside className="hidden h-full shrink-0 flex-col overflow-hidden bg-sidebarBg transition-[width] duration-300 ease-smooth md:flex" style={{ width: collapsed ? 52 : 196 }}>
        {body(collapsed)}
      </aside>
      {mobileNav && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMobileNav(false)} />
          <aside className="relative flex h-full w-[260px] animate-rise flex-col bg-sidebarBg" onClick={(e) => (e.target as HTMLElement).closest("a") && setMobileNav(false)}>
            {body(false)}
          </aside>
        </div>
      )}
    </>
  );
}
