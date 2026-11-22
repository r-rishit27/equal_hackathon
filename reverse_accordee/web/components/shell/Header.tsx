"use client";
import { usePathname } from "next/navigation";
import { Asterisk, ChevronDown, CircleHelp, Menu, Moon, Search, Sun } from "lucide-react";
import { Avatar, Divider } from "@/components/ui";
import { TEAM } from "@/lib/data";
import { ALL_NAV } from "./nav";
import { useShell } from "./ShellProvider";

export function Header() {
  const path = usePathname();
  const { setChatOpen, setPaletteOpen, setMobileNav, theme, setTheme } = useShell();
  const item = ALL_NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href)));
  const Icon = item?.icon;
  const isDark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");

  return (
    <header className="box-border flex h-toolbar w-full shrink-0 items-center justify-between border-b border-borderDark bg-appBg px-2">
      <div className="flex min-w-0 items-center">
        <button onClick={() => setMobileNav(true)} className="flex size-9 items-center justify-center rounded-md hover:bg-panelBg md:hidden" aria-label="Open menu"><Menu className="size-4" /></button>
        <nav aria-label="Breadcrumb" className="flex min-w-0 animate-fade-in items-center gap-2 px-1.5">
          {Icon && <Icon className="size-4 text-textMuted" strokeWidth={1.5} />}
          <span className="text-label leading-5 font-medium whitespace-nowrap">{item?.label ?? "Settings"}</span>
        </nav>
      </div>
      <div className="flex grow items-center justify-end gap-1.5">
        <div className="hidden h-control items-center rounded-md border border-borderDark bg-appBg shadow-xs sm:flex">
          <button onClick={() => setChatOpen(true)} title="Start a quick chat (⌘J)" className="flex h-full items-center gap-1.5 rounded-l-md pr-2.5 pl-2 transition-colors hover:bg-panelBg">
            <Asterisk className="size-3.5 text-textMuted" strokeWidth={2} />
            <span className="text-label leading-5 whitespace-nowrap text-textSecondary">Quick Chat</span>
          </button>
          <button aria-label="Quick Chat options" onClick={() => setChatOpen(true)} className="flex h-full items-center rounded-r-md border-l border-borderDark px-1.5 transition-colors hover:bg-panelBg">
            <ChevronDown className="size-3.5 text-textMuted" />
          </button>
        </div>
        <span className="hidden sm:block"><Divider /></span>
        <div className="hidden items-center px-1 sm:flex" aria-label="People viewing">
          {TEAM.map((m, i) => (
            <span key={m.id} title={`${m.name}, ${m.role}`} className="rounded-full border-[1.5px] border-appBg" style={{ marginLeft: i ? -6 : 0, zIndex: 10 - i }}>
              <Avatar name={m.name} hue={m.hue} size={16} />
            </span>
          ))}
        </div>
        <span className="hidden sm:block"><Divider /></span>
        <button onClick={() => setTheme(isDark || theme === "dark" ? "light" : "dark")} aria-label="Toggle theme" className="flex size-control items-center justify-center rounded-md hover:bg-panelBg">
          <Sun className="hidden size-4 text-textMuted dark:block" strokeWidth={1.5} />
          <Moon className="size-4 text-textMuted dark:hidden" strokeWidth={1.5} />
        </button>
        <button aria-label="Help" className="hidden size-control items-center justify-center rounded-md hover:bg-panelBg md:flex"><CircleHelp className="size-4 text-textMuted" strokeWidth={1.5} /></button>
        <button onClick={() => setPaletteOpen(true)} aria-label="Search" className="flex size-9 items-center justify-center rounded-md hover:bg-panelBg sm:hidden"><Search className="size-4" /></button>
      </div>
    </header>
  );
}
