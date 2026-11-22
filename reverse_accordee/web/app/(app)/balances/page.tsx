"use client";
import { useState } from "react";
import { Building2, Download, Hash, User } from "lucide-react";
import { DataTable, GhostButton, Page, StatStrip, Text, Toolbar, WithAvatar, type Column } from "@/components/ui";
import { customerById, daysBetween, fmtMoney, invoices, metrics, NOW } from "@/lib/data";

type Row = { id: string; outstanding: number; overdue: number; b: number[]; mostLate: number };
const map = new Map<string, Row>();
for (const i of invoices.filter((x) => x.status === "Sent" || x.status === "Overdue")) {
  const r = map.get(i.customerId) ?? { id: i.customerId, outstanding: 0, overdue: 0, b: [0, 0, 0, 0, 0], mostLate: 0 };
  const late = daysBetween(i.due, NOW);
  r.outstanding += i.amount;
  if (late > 0) r.overdue += i.amount;
  r.b[late <= 0 ? 0 : late <= 30 ? 1 : late <= 60 ? 2 : late <= 90 ? 3 : 4] += i.amount;
  r.mostLate = Math.max(r.mostLate, late);
  map.set(i.customerId, r);
}
const rows = [...map.values()].sort((a, b) => b.outstanding - a.outstanding);
const money = (n: number) => (n ? fmtMoney(n) : "—");
const columns: Column<Row>[] = [
  { key: "c", label: "Customer", width: 250, icon: Building2, render: (r) => { const c = customerById(r.id); return <WithAvatar name={c.name} hue={c.hue} square />; } },
  { key: "o", label: "Outstanding", width: 160, icon: Hash, render: (r) => <Text>{fmtMoney(r.outstanding)}</Text>, sort: (r) => r.outstanding, value: (r) => r.outstanding, money: true },
  { key: "od", label: "Overdue", width: 150, icon: Hash, render: (r) => <span className={r.overdue ? "text-label text-red-500 tabular-nums" : "text-label text-textMuted"}>{money(r.overdue)}</span>, sort: (r) => r.overdue },
  ...["Current", "1–30 days", "31–60 days", "61–90 days", "90+ days"].map((l, k) => ({ key: `b${k}`, label: l, width: 140, render: (r: Row) => <Text muted>{money(r.b[k])}</Text>, sort: (r: Row) => r.b[k] })),
  { key: "late", label: "Most late", width: 140, render: (r) => <Text muted>{r.mostLate > 0 ? `${r.mostLate} days` : "—"}</Text>, sort: (r) => r.mostLate },
  { key: "owner", label: "Owner", width: 190, icon: User, render: (r) => <WithAvatar name={customerById(r.id).owner} /> },
];

export default function BalancesPage() {
  const [tab, setTab] = useState("customer");
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "customer", label: "By customer", count: rows.length }]}><GhostButton icon={Download}>Export</GhostButton></Toolbar>
      <StatStrip stats={[
        { label: "Outstanding", value: fmtMoney(metrics.owed), sub: `${rows.length} customers owe you` },
        { label: "Overdue", value: fmtMoney(metrics.overdueAmt), sub: `${metrics.overdueCount} invoices past due` },
        { label: "Overdue share", value: `${Math.round((metrics.overdueAmt / (metrics.owed || 1)) * 100)}%`, sub: "of everything owed is late" },
        { label: "Over 90 days", value: fmtMoney(metrics.buckets[4]), sub: "Oldest bucket" },
      ]} />
      <DataTable rows={rows} columns={columns} label="Balances" selectable={false} />
    </Page>
  );
}
