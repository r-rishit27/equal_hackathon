"use client";
import { useState } from "react";
import { Building2, CalendarDays, CircleDot, CreditCard, Download, FileSignature, Hash, Plus, Receipt } from "lucide-react";
import { Chip, DataTable, GhostButton, Page, PrimaryButton, StatStrip, Text, Toolbar, WithAvatar, MethodBadge, RecordPill, type Column, type Tone } from "@/components/ui";
import { addDays, customerById, daysBetween, fmtDate, fmtMoney, invoices, metrics, NOW, iso, type Invoice, type InvoiceStatus } from "@/lib/data";

const TONE: Record<InvoiceStatus, Tone> = { Paid: "green", Sent: "blue", Overdue: "red", Upcoming: "gray" };
const columns: Column<Invoice>[] = [
  { key: "id", label: "Invoice", width: 170, icon: Receipt, render: (i) => <RecordPill>{i.id}</RecordPill>, sort: (i) => i.id },
  { key: "cust", label: "Customer", width: 220, icon: Building2, render: (i) => { const c = customerById(i.customerId); return <WithAvatar name={c.name} hue={c.hue} square />; }, sort: (i) => customerById(i.customerId).name },
  { key: "status", label: "Status", width: 150, icon: CircleDot, render: (i) => <span className="flex items-center gap-2"><Chip tone={TONE[i.status]}>{i.status}</Chip>{i.status === "Overdue" && <span className="text-caption text-red-500">{daysBetween(i.due, NOW)}d</span>}</span>, sort: (i) => i.status },
  { key: "amount", label: "Amount", width: 140, icon: Hash, render: (i) => <Text>{fmtMoney(i.amount)}</Text>, sort: (i) => i.amount, value: (i) => i.amount, money: true },
  { key: "issued", label: "Issued", width: 140, icon: CalendarDays, render: (i) => <Text muted>{fmtDate(i.issued)}</Text>, sort: (i) => i.issued },
  { key: "due", label: "Due", width: 140, icon: CalendarDays, render: (i) => <Text muted>{fmtDate(i.due)}</Text>, sort: (i) => i.due },
  { key: "ct", label: "Contract", width: 120, icon: FileSignature, render: (i) => <Text muted>{i.contractId}</Text> },
  { key: "paid", label: "Paid", width: 130, icon: CalendarDays, render: (i) => <Text muted>{i.paid ? fmtDate(i.paid) : "—"}</Text> },
  { key: "method", label: "Method", width: 220, icon: CreditCard, render: (i) => (i.method ? <MethodBadge method={i.method} /> : <Text muted>—</Text>) },
];

type Tab = "all" | InvoiceStatus;
export default function InvoicesPage() {
  const [tab, setTab] = useState<Tab>("all");
  const rows = tab === "all" ? invoices : invoices.filter((i) => i.status === tab);
  const next30 = invoices.filter((i) => i.status === "Upcoming" && i.issued <= iso(addDays(NOW, 30)));
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All", count: invoices.length }, ...(["Sent", "Overdue", "Paid", "Upcoming"] as const).map((s) => ({ id: s, label: s, count: invoices.filter((i) => i.status === s).length }))]}>
        <GhostButton icon={Download}>Export</GhostButton>
        <PrimaryButton icon={Plus}>New invoice</PrimaryButton>
      </Toolbar>
      <StatStrip stats={[
        { label: "Outstanding", value: fmtMoney(metrics.owed), sub: `${metrics.openCount} invoices waiting for payment` },
        { label: "Overdue", value: fmtMoney(metrics.overdueAmt), sub: `${metrics.overdueCount} invoices` },
        { label: "Collected this month", value: fmtMoney(metrics.collectedMonth), sub: "Card, ACH and transfer" },
        { label: "Next 30 days", value: fmtMoney(next30.reduce((s, i) => s + i.amount, 0)), sub: `${next30.length} invoices to go out` },
      ]} />
      <DataTable rows={rows} columns={columns} label="Invoices" />
    </Page>
  );
}
