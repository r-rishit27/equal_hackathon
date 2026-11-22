"use client";
import { useState } from "react";
import { Plus, Pencil } from "lucide-react";
import { Avatar, GhostButton, Page, Toolbar } from "@/components/ui";
import { contracts, customerById, daysBetween, fmtDate, fmtMoney, invoices, isLive, leads, LEAD_STAGES, metrics, NOW } from "@/lib/data";

function Card({ title, sub, children, className = "" }: { title: string; sub?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`flex min-w-0 animate-rise flex-col rounded-xl border border-borderDark bg-card p-4 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-2"><h2 className="text-label font-medium">{title}</h2>{sub && <span className="text-caption text-textMuted">{sub}</span>}</div>
      {children}
    </section>
  );
}

function Sparkline({ values, color = "var(--series-1)" }: { values: number[]; color?: string }) {
  const max = Math.max(...values, 1), min = Math.min(...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 70},${22 - ((v - min) / (max - min || 1)) * 18}`);
  const last = pts[pts.length - 1].split(",");
  return (
    <svg viewBox="-2 0 76 26" className="h-7 w-[72px] shrink-0" aria-hidden>
      <polyline points={pts.join(" ")} fill="none" stroke="var(--ac-text-muted)" strokeWidth="1" opacity="0.7" />
      <circle cx={last[0]} cy={last[1]} r="2" fill={color} />
    </svg>
  );
}

function KpiCard({ label, value, sub, spark, danger, delay }: { label: string; value: string; sub: React.ReactNode; spark: number[]; danger?: boolean; delay: number }) {
  return (
    <div className="flex animate-rise flex-col gap-2 rounded-xl border border-borderDark bg-card p-4" style={{ animationDelay: `${delay}ms` }}>
      <span className="text-label text-textSecondary">{label}</span>
      <div className="flex items-end justify-between gap-2">
        <span className="text-display-sm leading-8 tabular-nums">{value}</span>
        <Sparkline values={spark} />
      </div>
      <span className={danger ? "text-caption text-red-500" : "text-caption text-textMuted"}>{sub}</span>
    </div>
  );
}

const RANGES = { "3M": 3, "6M": 6, "12M": 12 } as const;
function LineChart() {
  const [range, setRange] = useState<keyof typeof RANGES>("12M");
  const [hover, setHover] = useState<number | null>(null);
  const data = metrics.monthly.slice(-RANGES[range]);
  const max = Math.max(...data.flatMap((d) => [d.invoiced, d.collected]), 1) * 1.1;
  const W = 640, H = 170, L = 44;
  const x = (i: number) => L + (i / Math.max(data.length - 1, 1)) * (W - L - 8);
  const y = (v: number) => H - (v / max) * (H - 10);
  const path = (k: "invoiced" | "collected") => data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d[k])}`).join("");
  const short = (v: number) => (v >= 1000 ? `$${Math.round(v / 1000)}K` : `$${v}`);
  return (
    <div>
      <div className="mb-2 flex items-center gap-4 text-caption text-textMuted">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 rounded" style={{ background: "var(--series-1)" }} />Collected</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 rounded" style={{ background: "var(--series-2)" }} />Invoiced</span>
        {hover !== null && <span className="text-textPrimary tabular-nums">{data[hover].label}: {fmtMoney(data[hover].collected)} of {fmtMoney(data[hover].invoiced)}</span>}
        <div className="ml-auto flex rounded-md border border-borderDark p-0.5">
          {(Object.keys(RANGES) as (keyof typeof RANGES)[]).map((r) => (
            <button key={r} onClick={() => setRange(r)} className={`rounded px-2 py-0.5 text-caption ${r === range ? "bg-panelBg text-textPrimary" : "text-textMuted"}`}>{r}</button>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H + 20}`} className="h-48 w-full" onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line x1={L} x2={W} y1={y(max * t / 1.1)} y2={y(max * t / 1.1)} stroke="var(--ac-border)" />
            <text x={L - 6} y={y(max * t / 1.1) + 3} textAnchor="end" fontSize="10" fill="var(--ac-text-muted)">{short(Math.round(max * t / 1.1))}</text>
          </g>
        ))}
        <path d={path("invoiced")} fill="none" stroke="var(--series-2)" strokeWidth="1.75" strokeLinejoin="round" />
        <path d={path("collected")} fill="none" stroke="var(--series-1)" strokeWidth="1.75" strokeLinejoin="round" />
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} stroke="var(--ac-text-muted)" strokeDasharray="2 3" />}
        {data.map((d, i) => (
          <g key={i}>
            <text x={x(i)} y={H + 16} textAnchor="middle" fontSize="10" fill="var(--ac-text-muted)">{d.label}</text>
            {hover === i && <><circle cx={x(i)} cy={y(d.collected)} r="3" fill="var(--series-1)" /><circle cx={x(i)} cy={y(d.invoiced)} r="3" fill="var(--series-2)" /></>}
            <rect x={x(i) - (W - L) / data.length / 2} y="0" width={(W - L) / data.length} height={H} fill="transparent" onMouseEnter={() => setHover(i)} />
          </g>
        ))}
      </svg>
    </div>
  );
}

function Donut() {
  const parts = [
    { label: "Active", n: contracts.filter((c) => c.status === "Active").length, color: "var(--series-3)" },
    { label: "Expiring", n: contracts.filter((c) => c.status === "Expiring").length, color: "var(--series-4)" },
    { label: "Awaiting signature", n: contracts.filter((c) => c.status === "Awaiting signature").length, color: "var(--series-1)" },
    { label: "Draft", n: contracts.filter((c) => c.status === "Draft").length, color: "var(--ac-text-muted)" },
  ];
  const total = parts.reduce((s, p) => s + p.n, 0);
  let acc = 0;
  const C = 2 * Math.PI * 40;
  return (
    <div className="flex items-center gap-5">
      <div className="relative size-32 shrink-0">
        <svg viewBox="0 0 100 100" className="size-32 -rotate-90">
          {parts.map((p) => { const len = (p.n / total) * C; const el = <circle key={p.label} cx="50" cy="50" r="40" fill="none" stroke={p.color} strokeWidth="12" strokeDasharray={`${Math.max(len - 1.5, 0)} ${C - len + 1.5}`} strokeDashoffset={-acc} />; acc += len; return el; })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center"><span className="text-heading tabular-nums">{total}</span><span className="text-caption text-textMuted">Contracts</span></div>
      </div>
      <div className="flex flex-1 flex-col gap-2">
        {parts.map((p) => (
          <div key={p.label} className="flex items-center gap-2 text-label"><span className="size-2 rounded-full" style={{ background: p.color }} /><span className="flex-1 text-textSecondary">{p.label}</span><span className="tabular-nums">{p.n}</span><span className="w-9 text-right text-caption text-textMuted">{Math.round((p.n / total) * 100)}%</span></div>
        ))}
      </div>
    </div>
  );
}

function Ageing() {
  const labels = ["Current", "1–30", "31–60", "61–90", "90+"];
  const total = metrics.buckets.reduce((s, b) => s + b, 0) || 1;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full">
        {metrics.buckets.map((b, i) => <div key={i} style={{ width: `${(b / total) * 100}%`, background: `var(--age-${i + 1})` }} />)}
      </div>
      <div className="mt-3 grid grid-cols-5 gap-2">
        {metrics.buckets.map((b, i) => <div key={i}><div className="text-caption text-textMuted">{labels[i]}</div><div className="text-label tabular-nums">{fmtMoney(b)}</div></div>)}
      </div>
    </div>
  );
}

export default function HomePage() {
  const [tab, setTab] = useState("overview");
  const renewals = contracts.filter((c) => isLive(c) && daysBetween(NOW, c.renewal) <= 60).sort((a, b) => (a.renewal < b.renewal ? -1 : 1)).slice(0, 6);
  const overdue = invoices.filter((i) => i.status === "Overdue").sort((a, b) => b.amount - a.amount).slice(0, 6);
  const funnel = LEAD_STAGES.slice(0, 5).map((s) => ({ s, n: leads.filter((l) => l.stage === s).length }));
  const fmax = Math.max(...funnel.map((f) => f.n));
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={["Overview", "Revenue", "Renewals", "Pipeline"].map((t) => ({ id: t.toLowerCase(), label: t }))}>
        <GhostButton icon={Pencil}>Edit Cards</GhostButton>
        <GhostButton icon={Plus}>Add Card</GhostButton>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="grid grid-cols-1 gap-4 px-4 pt-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard delay={0} label="Annual recurring revenue" value={fmtMoney(metrics.arr)} sub={`${metrics.liveCount} live contracts`} spark={metrics.monthly.map((_, i) => metrics.arr * (0.7 + i * 0.03))} />
          <KpiCard delay={50} label="Collected this month" value={fmtMoney(metrics.collectedMonth)} sub={`${fmtMoney(metrics.monthly[10].collected)} last month`} spark={metrics.monthly.map((m) => m.collected)} />
          <KpiCard delay={100} label="Open pipeline" value={fmtMoney(metrics.pipeline)} sub={`${fmtMoney(metrics.weighted)} weighted`} spark={metrics.monthly.map((m, i) => m.invoiced * 0.5 + i * 1e4)} />
          <KpiCard delay={150} label="Owed to you" value={fmtMoney(metrics.owed)} sub={`${fmtMoney(metrics.overdueAmt)} overdue`} danger spark={metrics.monthly.map((m) => Math.max(m.invoiced - m.collected, 0))} />
        </div>
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-3">
          {(tab === "overview" || tab === "revenue") && <Card title="Collected vs invoiced" className="lg:col-span-2"><LineChart /></Card>}
          {(tab === "overview" || tab === "renewals") && <Card title="Contracts by status"><Donut /></Card>}
          {(tab === "overview" || tab === "revenue") && <Card title="Receivables by age" sub={fmtMoney(metrics.owed)} className="lg:col-span-2"><Ageing /></Card>}
          {(tab === "overview" || tab === "pipeline") && (
            <Card title="Pipeline by stage" sub={`${metrics.winRate}% win rate`}>
              <div className="flex flex-col gap-2">
                {funnel.map((f) => <div key={f.s} className="flex items-center gap-3 text-label"><span className="w-24 text-textSecondary">{f.s}</span><div className="h-5 flex-1 rounded bg-panelBg"><div className="h-full rounded" style={{ width: `${(f.n / fmax) * 100}%`, background: "var(--series-1)" }} /></div><span className="w-6 text-right tabular-nums">{f.n}</span></div>)}
              </div>
            </Card>
          )}
          {(tab === "overview" || tab === "renewals") && (
            <Card title="Renewing in 60 days" sub={`${metrics.renewing60.length} contracts`}>
              <ul className="flex flex-col">{renewals.map((c) => { const x = customerById(c.customerId); return <li key={c.id} className="flex items-center gap-2.5 border-b border-borderDark py-2 last:border-0"><Avatar name={x.name} hue={x.hue} square /><span className="flex-1 truncate text-label">{x.name}</span><span className="text-caption text-textMuted">{fmtDate(c.renewal)}</span><span className="w-20 text-right text-label tabular-nums">{fmtMoney(c.annualValue)}</span></li>; })}</ul>
            </Card>
          )}
          {(tab === "overview" || tab === "revenue") && (
            <Card title="Largest overdue" sub={`${metrics.overdueCount} invoices`} className="lg:col-span-2">
              <ul className="flex flex-col">{overdue.map((i) => { const x = customerById(i.customerId); return <li key={i.id} className="flex items-center gap-2.5 border-b border-borderDark py-2 last:border-0"><Avatar name={x.name} hue={x.hue} square /><span className="flex-1 truncate text-label">{x.name}</span><span className="text-caption text-textMuted">{i.id}</span><span className="text-caption text-red-500">{daysBetween(i.due, NOW)}d late</span><span className="w-20 text-right text-label tabular-nums">{fmtMoney(i.amount)}</span></li>; })}</ul>
            </Card>
          )}
        </div>
      </div>
    </Page>
  );
}
