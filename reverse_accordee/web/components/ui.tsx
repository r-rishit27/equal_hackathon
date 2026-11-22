"use client";
import { clsx } from "clsx";
import { ArrowDown, ArrowUp, ChevronDown, Link2, ReceiptText, type LucideIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

export const cn = clsx;

export function Avatar({ name, hue, size = 16, square = false }: { name: string; hue?: number; size?: number; square?: boolean }) {
  const h = hue ?? [...name].reduce((s, c) => s + c.charCodeAt(0), 0) % 360;
  // Companies get a soft multi-hue mesh; people get a warmer two-stop gradient.
  const background = square
    ? `radial-gradient(circle at 20% 20%, hsl(${h} 95% 72%) 0%, transparent 60%), radial-gradient(circle at 85% 30%, hsl(${(h + 60) % 360} 95% 70%) 0%, transparent 55%), radial-gradient(circle at 50% 95%, hsl(${(h + 200) % 360} 90% 68%) 0%, transparent 60%), hsl(${(h + 30) % 360} 90% 82%)`
    : `linear-gradient(135deg, hsl(${h} 80% 72%), hsl(${(h + 35) % 360} 75% 55%))`;
  return (
    <span
      aria-hidden
      className={cn("inline-flex shrink-0 items-center justify-center font-medium text-white", square ? "rounded-[4px]" : "rounded-full")}
      style={{ width: size, height: size, fontSize: Math.max(7, size * 0.42), background }}
    >
      {size >= 20 ? name.split(" ").map((p) => p[0]).slice(0, 2).join("") : null}
    </span>
  );
}

const TONES = {
  gray: "border-borderDark text-textSecondary bg-panelBg",
  green: "border-green-300 text-green-700 bg-green-50 dark:border-green-500/40 dark:text-green-400 dark:bg-green-500/10",
  blue: "border-blue-200 text-blue-600 bg-blue-50 dark:border-blue-500/30 dark:text-blue-400 dark:bg-blue-500/10",
  red: "border-red-200 text-red-600 bg-red-50 dark:border-red-500/30 dark:text-red-400 dark:bg-red-500/10",
  amber: "border-amber-200 text-amber-700 bg-amber-50 dark:border-amber-500/30 dark:text-amber-400 dark:bg-amber-500/10",
  violet: "border-violet-200 text-violet-600 bg-violet-50 dark:border-violet-500/30 dark:text-violet-400 dark:bg-violet-500/10",
} as const;
export type Tone = keyof typeof TONES;

export function Chip({ children, tone = "gray" }: { children: ReactNode; tone?: Tone }) {
  return <span className={cn("inline-flex h-[18px] items-center rounded-chip border px-1.5 text-micro leading-none whitespace-nowrap", TONES[tone])}>{children}</span>;
}

export function Kbd({ children, outline }: { children: ReactNode; outline?: boolean }) {
  return (
    <span className={cn("box-border flex size-4 items-center justify-center rounded text-micro leading-none font-medium text-textMuted", outline ? "border border-borderDark bg-appBg" : "bg-kbdBg")}>
      {children}
    </span>
  );
}

export function Count({ n }: { n: number }) {
  return <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-kbdBg px-1 text-micro leading-none font-medium text-textSecondary tabular-nums">{n}</span>;
}

export function GhostButton({ icon: Icon, children, onClick, active }: { icon?: LucideIcon; children?: ReactNode; onClick?: () => void; active?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={cn("flex h-control shrink-0 items-center gap-1.5 rounded-md py-1 pr-2.5 pl-2 transition-colors hover:bg-panelBg", active && "bg-panelBg")}>
      {Icon && <Icon className="size-4 text-textMuted" strokeWidth={1.5} />}
      {children && <span className="text-label leading-5 whitespace-nowrap text-textSecondary">{children}</span>}
    </button>
  );
}

export function PrimaryButton({ icon: Icon, children, onClick }: { icon?: LucideIcon; children: ReactNode; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className="flex h-control shrink-0 items-center gap-1.5 rounded-md bg-brand pr-3 pl-2.5 text-label font-medium whitespace-nowrap text-brandFg shadow-xs transition-opacity hover:opacity-90">
      {Icon && <Icon className="size-4" strokeWidth={2} />}
      {children}
    </button>
  );
}

export const Divider = () => <div className="mx-1 h-4 w-hairline shrink-0 bg-borderDark" />;

/** Second toolbar row: tabs on the left, actions on the right. */
export function Toolbar<T extends string>({ tabs, value, onChange, children }: {
  tabs: { id: T; label: string; count?: number; icon?: LucideIcon }[]; value: T; onChange: (v: T) => void; children?: ReactNode;
}) {
  return (
    <div className="box-border flex h-toolbar w-full shrink-0 items-center justify-between gap-4 border-b border-borderDark bg-appBg px-2">
      <div role="tablist" className="flex min-w-0 items-center gap-2 overflow-x-auto py-1">
        {tabs.map((t) => {
          const on = t.id === value;
          return (
            <button key={t.id} role="tab" aria-selected={on} onClick={() => onChange(t.id)}
              className={cn("flex h-control shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 transition-colors",
                on ? "border-borderDark bg-panelBg text-textPrimary" : "border-transparent text-textSecondary hover:bg-panelBg")}>
              {t.icon && <t.icon className="size-4 text-textMuted" strokeWidth={1.5} />}
              <span className="text-label leading-5 whitespace-nowrap">{t.label}</span>
              {t.count !== undefined && <span className="text-label text-textMuted tabular-nums">{t.count}</span>}
            </button>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-1">{children}</div>
    </div>
  );
}

export type Stat = { label: string; value: string; sub?: ReactNode };
export function StatStrip({ stats }: { stats: Stat[] }) {
  return (
    <section className="shrink-0 border-b border-borderDark">
      <div className="grid grid-cols-2 md:grid-cols-4">
        {stats.map((s, i) => (
          <div key={s.label} className="flex min-w-0 animate-fade-in flex-col gap-1 border-borderDark px-5 py-3.5 not-last:border-r max-md:[&:nth-child(-n+2)]:border-b max-md:[&:nth-child(2)]:border-r-0" style={{ animationDelay: `${i * 50}ms` }}>
            <span className="truncate text-caption text-textMuted">{s.label}</span>
            <span className="truncate text-heading-sm leading-6 tabular-nums text-textPrimary">{s.value}</span>
            {s.sub && <span className="truncate text-caption text-textMuted">{s.sub}</span>}
          </div>
        ))}
      </div>
    </section>
  );
}

export type Column<R> = {
  key: string; label: string; width: number; icon?: LucideIcon;
  render: (r: R) => ReactNode; sort?: (r: R) => string | number;
  /** Numeric value for the footer's Sum / Average. */
  value?: (r: R) => number; money?: boolean;
};

type Calc = "count" | "unique" | "sum" | "avg" | "min" | "max";
const CALC_LABEL: Record<Calc, string> = { count: "Count", unique: "Unique", sum: "Sum", avg: "Average", min: "Min", max: "Max" };

function CalcCell<R>({ col, rows }: { col: Column<R>; rows: R[] }) {
  const [calc, setCalc] = useState<Calc | null>(null);
  const [menu, setMenu] = useState<{ left: number; bottom: number } | null>(null);
  const open = menu !== null;
  const opts: Calc[] = col.value ? ["count", "sum", "avg", "min", "max"] : ["count", "unique"];
  let out = "";
  if (calc) {
    const nums = col.value ? rows.map(col.value) : [];
    const fmt = (n: number) => (col.money ? n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }) : n.toLocaleString("en-US", { maximumFractionDigits: 1 }));
    if (calc === "count") out = String(rows.length);
    else if (calc === "unique") out = String(new Set(rows.map((r) => String(col.sort?.(r) ?? JSON.stringify(r)))).size);
    else if (calc === "sum") out = fmt(nums.reduce((s, n) => s + n, 0));
    else if (calc === "avg") out = fmt(nums.reduce((s, n) => s + n, 0) / (nums.length || 1));
    else if (calc === "min") out = fmt(Math.min(...nums));
    else out = fmt(Math.max(...nums));
  }
  return (
    <>
      <button
        onClick={(e) => {
          if (open) return setMenu(null);
          const r = e.currentTarget.getBoundingClientRect();
          setMenu({ left: r.left, bottom: window.innerHeight - r.top + 6 });
        }}
        className="flex w-full items-center gap-2 text-label text-textMuted hover:text-textSecondary">
        <ChevronDown className="size-3.5 shrink-0" />
        {calc ? <span className="truncate"><span className="text-textMuted">{CALC_LABEL[calc]}</span> <span className="text-textPrimary tabular-nums">{out}</span></span> : "Calculate"}
      </button>
      {menu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
          <div className="fixed z-50 w-36 animate-fade-in rounded-lg border border-borderDark bg-appBg p-1 shadow-lg" style={{ left: menu.left, bottom: menu.bottom }}>
          {[null, ...opts].map((o) => (
            <button key={o ?? "none"} onClick={() => { setCalc(o); setMenu(null); }} className="flex w-full items-center rounded-md px-2 py-1.5 text-left text-label hover:bg-panelBg">
              {o ? CALC_LABEL[o] : "None"}
            </button>
          ))}
          </div>
        </>
      )}
    </>
  );
}

export function DataTable<R extends { id: string }>({ rows, columns, label, onRowClick, selectable = true }: { rows: R[]; columns: Column<R>[]; label: string; onRowClick?: (r: R) => void; selectable?: boolean }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const lead = selectable ? 84 : 44; // checkbox (40) + row number (44)
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sort) return rows;
    return [...rows].sort((a, b) => (col.sort!(a) > col.sort!(b) ? sort.dir : col.sort!(a) < col.sort!(b) ? -sort.dir : 0));
  }, [rows, sort, columns]);
  const total = lead + columns.reduce((s, c) => s + c.width, 0);
  const numLeft = selectable ? 40 : 0;
  const allOn = rows.length > 0 && selected.size === rows.length;
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="min-h-0 flex-1 animate-fade-in overflow-auto overscroll-x-none">
      <table className="crm-table h-full w-full" style={{ minWidth: total }} aria-label={label}>
        <colgroup>
          {selectable && <col style={{ width: 40 }} />}<col style={{ width: 44 }} />
          {columns.map((c) => <col key={c.key} style={{ width: c.width }} />)}
        </colgroup>
        <thead>
          <tr>
            {selectable && (
              <th className="stick" style={{ left: 0 }}>
                <input type="checkbox" className="crm-check" aria-label="Select all rows" checked={allOn} onChange={() => setSelected(allOn ? new Set() : new Set(rows.map((r) => r.id)))} />
              </th>
            )}
            <th className="stick" style={{ left: numLeft }}><span className="sr-only">Row number</span></th>
            {columns.map((c, i) => (
              <th key={c.key} className={cn("cursor-pointer select-none", i === 0 && "stick stick-edge")} style={i === 0 ? { left: lead } : undefined}
                onClick={() => c.sort && setSort((s) => (s?.key === c.key ? (s.dir === 1 ? { key: c.key, dir: -1 } : null) : { key: c.key, dir: 1 }))}>
                <div className="flex items-center gap-2.5">
                  {c.icon && <c.icon className="size-4 shrink-0 text-textMuted" strokeWidth={1.5} />}
                  <span className="truncate text-label leading-5 text-textMuted">{c.label}</span>
                  {sort?.key === c.key && (sort.dir === 1 ? <ArrowUp className="size-3 text-textMuted" /> : <ArrowDown className="size-3 text-textMuted" />)}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, idx) => (
            <tr key={r.id} data-selected={selected.has(r.id)} onClick={() => onRowClick?.(r)} className={onRowClick ? "cursor-pointer" : undefined}>
              {selectable && (
                <td className="stick" style={{ left: 0 }} onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" className="crm-check" aria-label={`Select row ${idx + 1}`} checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                </td>
              )}
              <td className="stick text-center text-label font-light text-textMuted tabular-nums" style={{ left: numLeft }}>{idx + 1}</td>
              {columns.map((c, i) => (
                <td key={c.key} className={cn(i === 0 && "stick stick-edge")} style={i === 0 ? { left: lead } : undefined}>{c.render(r)}</td>
              ))}
            </tr>
          ))}
          {/* filler so the footer sits at the bottom on short tables */}
          <tr aria-hidden className="h-full"><td colSpan={columns.length + (selectable ? 2 : 1)} className="!h-auto !border-0 !bg-transparent" /></tr>
        </tbody>
        <tfoot>
          <tr>
            {selectable && <td className="stick" style={{ left: 0 }} />}
            <td className="stick" style={{ left: numLeft }} />
            {columns.map((c, i) => (
              <td key={c.key} className={cn(i === 0 && "stick stick-edge")} style={i === 0 ? { left: lead } : undefined}><CalcCell col={c} rows={sorted} /></td>
            ))}
          </tr>
        </tfoot>
      </table>
      {selected.size > 0 && (
        <div className="pointer-events-none sticky bottom-4 flex justify-center">
          <div className="pointer-events-auto flex animate-rise items-center gap-3 rounded-lg border border-borderDark bg-appBg px-3 py-1.5 text-label shadow-lg">
            <span className="tabular-nums">{selected.size} selected</span>
            <Divider />
            <button className="text-textSecondary hover:text-textPrimary" onClick={() => setSelected(new Set())}>Clear</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Cell helpers */
export const Text = ({ children, muted }: { children: ReactNode; muted?: boolean }) => (
  <span className={cn("truncate text-label tabular-nums", muted ? "text-textSecondary" : "text-textPrimary")}>{children}</span>
);
export const WithAvatar = ({ name, hue, square }: { name: string; hue?: number; square?: boolean }) => (
  <div className="flex min-w-0 items-center gap-2.5"><Avatar name={name} hue={hue} square={square} /><span className="truncate text-label text-textPrimary">{name}</span></div>
);

export function Page({ children }: { children: ReactNode }) {
  return <div className="flex min-h-0 w-full flex-1 animate-fade-in flex-col">{children}</div>;
}

// ---------- Rich cell renderers ----------
const FLAGS: Record<string, string> = {
  Germany: "🇩🇪", "United States": "🇺🇸", France: "🇫🇷", Japan: "🇯🇵", Australia: "🇦🇺", Canada: "🇨🇦",
  "South Africa": "🇿🇦", Brazil: "🇧🇷", Netherlands: "🇳🇱", India: "🇮🇳", Sweden: "🇸🇪", Singapore: "🇸🇬",
  Spain: "🇪🇸", "United Kingdom": "🇬🇧",
};
/** Round flag, like the original's circular flag SVGs. */
export function Flag({ country }: { country: string }) {
  return (
    <span aria-hidden className="relative inline-flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full ring-[0.5px] ring-black/10 dark:ring-white/15">
      <span className="text-[22px] leading-none">{FLAGS[country] ?? "🏳️"}</span>
    </span>
  );
}
export const WithFlag = ({ country, children }: { country: string; children: ReactNode }) => (
  <div className="flex min-w-0 items-center gap-2.5"><Flag country={country} /><span className="truncate text-label text-textPrimary">{children}</span></div>
);

export const WebsiteLink = ({ domain }: { domain: string }) => (
  <a href={`https://${domain}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="flex min-w-0 items-center gap-2.5 text-textMuted transition-colors hover:text-textPrimary">
    <Link2 className="size-4 shrink-0 -rotate-45" strokeWidth={1.5} /><span className="truncate text-label">{domain}</span>
  </a>
);

export const RecordPill = ({ children }: { children: ReactNode }) => (
  <span className="inline-flex h-6 items-center gap-1.5 rounded-md border border-borderDark bg-appBg px-1.5 text-label tabular-nums text-textPrimary shadow-xs">
    <ReceiptText className="size-3.5 text-textMuted" strokeWidth={1.5} />{children}
  </span>
);

/** Payment method with a small brand-coloured badge (generic marks, not logos). */
export function MethodBadge({ method }: { method: string }) {
  let badge: ReactNode;
  if (method.includes("Stripe")) badge = <span className="flex h-5 w-6 items-center justify-center rounded bg-[#635bff] text-[7px] font-bold tracking-tight text-white">stripe</span>;
  else if (method.startsWith("Visa")) badge = <span className="flex h-5 w-6 items-center justify-center rounded bg-[#1a1f71] text-[7px] font-extrabold italic text-white">VISA</span>;
  else if (method.startsWith("Mastercard")) badge = (
    <span className="relative flex h-5 w-6 items-center justify-center rounded bg-[#141414]">
      <span className="absolute left-[5px] size-2.5 rounded-full bg-[#eb001b]" /><span className="absolute right-[5px] size-2.5 rounded-full bg-[#f79e1b] mix-blend-screen" />
    </span>
  );
  else if (method === "Apple Pay") badge = <span className="flex h-5 w-6 items-center justify-center rounded bg-black text-[7px] font-semibold text-white">Pay</span>;
  else badge = <span className="flex h-5 w-6 items-center justify-center rounded border border-borderDark bg-panelBg text-[8px] font-semibold text-textSecondary">BANK</span>;
  return <div className="flex min-w-0 items-center gap-2">{badge}<span className="truncate text-label text-textPrimary">{method}</span></div>;
}
