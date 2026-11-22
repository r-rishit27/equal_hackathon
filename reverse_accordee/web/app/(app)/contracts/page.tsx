"use client";
import { useState } from "react";
import { Building2, CalendarDays, Download, FileSignature, Hash, Plus, Repeat, User, CircleDot } from "lucide-react";
import { Chip, DataTable, GhostButton, Page, PrimaryButton, StatStrip, Text, Toolbar, WithAvatar, type Column, type Tone } from "@/components/ui";
import { contracts, customerById, daysBetween, fmtDate, fmtMoney, isLive, metrics, NOW, type Contract, type ContractStatus } from "@/lib/data";

const CONTRACT_TONE: Record<ContractStatus, Tone> = { Active: "green", Expiring: "amber", "Awaiting signature": "violet", Draft: "gray" };
const columns: Column<Contract>[] = [
  { key: "name", label: "Contract", width: 300, icon: FileSignature, render: (c) => <div className="flex min-w-0 items-center gap-2"><span className="truncate text-label">{c.plan} plan subscription</span><span className="text-caption text-textMuted">{c.id}</span></div>, sort: (c) => c.id },
  { key: "cust", label: "Customer", width: 240, icon: Building2, render: (c) => { const x = customerById(c.customerId); return <WithAvatar name={x.name} hue={x.hue} square />; }, sort: (c) => customerById(c.customerId).name },
  { key: "status", label: "Status", width: 170, icon: CircleDot, render: (c) => <Chip tone={CONTRACT_TONE[c.status]}>{c.status}</Chip>, sort: (c) => c.status },
  { key: "value", label: "Annual value", width: 160, icon: Hash, render: (c) => <Text>{fmtMoney(c.annualValue)}</Text>, sort: (c) => c.annualValue, value: (c) => c.annualValue, money: true },
  { key: "seats", label: "Seats", width: 90, icon: Hash, render: (c) => <Text>{c.seats}</Text>, sort: (c) => c.seats, value: (c) => c.seats },
  { key: "start", label: "Start", width: 150, icon: CalendarDays, render: (c) => <Text muted>{fmtDate(c.start)}</Text>, sort: (c) => c.start },
  { key: "renewal", label: "Renewal", width: 230, icon: Repeat, render: (c) => <span className="text-label text-textSecondary tabular-nums">{fmtDate(c.renewal)} <span className="text-textMuted">· {daysBetween(NOW, c.renewal)}d</span></span>, sort: (c) => c.renewal },
  { key: "billing", label: "Billing", width: 140, icon: CalendarDays, render: (c) => <Text muted>{c.billing}</Text> },
  { key: "owner", label: "Owner", width: 200, icon: User, render: (c) => <WithAvatar name={c.owner} /> },
];

type Tab = "all" | ContractStatus;
export default function ContractsPage() {
  const [tab, setTab] = useState<Tab>("all");
  const rows = tab === "all" ? contracts : contracts.filter((c) => c.status === tab);
  const awaiting = contracts.filter((c) => c.status === "Awaiting signature");
  const live = contracts.filter(isLive);
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All contracts", count: contracts.length }, ...(["Active", "Expiring", "Awaiting signature", "Draft"] as const).map((s) => ({ id: s, label: s, count: contracts.filter((c) => c.status === s).length }))]}>
        <GhostButton icon={Download}>Export</GhostButton>
        <PrimaryButton icon={Plus}>New contract</PrimaryButton>
      </Toolbar>
      <StatStrip stats={[
        { label: "Live contracts", value: String(live.length), sub: `${fmtMoney(metrics.arr)} a year` },
        { label: "Renewing in 60 days", value: fmtMoney(metrics.renewing60.reduce((s, c) => s + c.annualValue, 0)), sub: `${metrics.renewing60.length} contracts` },
        { label: "Awaiting signature", value: String(awaiting.length), sub: `${fmtMoney(awaiting.reduce((s, c) => s + c.annualValue, 0))} a year` },
        { label: "Average contract", value: fmtMoney(Math.round(metrics.arr / live.length)), sub: "Per year, live contracts" },
      ]} />
      <DataTable rows={rows} columns={columns} label="Contracts" />
    </Page>
  );
}
