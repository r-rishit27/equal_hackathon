"use client";
import { useState } from "react";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, Building2, CalendarDays, CircleDollarSign, CircleDot, CreditCard, Download, Hash, ReceiptText, RefreshCw, SlidersHorizontal } from "lucide-react";
import { Chip, DataTable, GhostButton, MethodBadge, Page, RecordPill, StatStrip, Text, Toolbar, WithAvatar, type Column } from "@/components/ui";
import { customerById, daysBetween, fmtDate, fmtMoney, NOW, transactions, type Transaction } from "@/lib/data";

const columns: Column<Transaction>[] = [
  {
    key: "id", label: "Transaction", width: 170, icon: Hash, sort: (t) => t.id,
    render: (t) => (
      <div className="flex items-center gap-2.5">
        {t.type === "Refund" ? <ArrowUpRight className="size-4 text-textMuted" strokeWidth={1.5} /> : <ArrowDownLeft className="size-4 text-textMuted" strokeWidth={1.5} />}
        <Text>{t.id}</Text>
      </div>
    ),
  },
  { key: "date", label: "Date", width: 140, icon: CalendarDays, render: (t) => <Text>{fmtDate(t.date)}</Text>, sort: (t) => t.date },
  { key: "c", label: "Customer", width: 240, icon: Building2, render: (t) => { const c = customerById(t.customerId); return <WithAvatar name={c.name} hue={c.hue} square />; }, sort: (t) => customerById(t.customerId).name },
  { key: "inv", label: "Invoice", width: 150, icon: ReceiptText, render: (t) => <RecordPill>{t.invoiceId}</RecordPill>, sort: (t) => t.invoiceId },
  { key: "type", label: "Type", width: 130, icon: ArrowLeftRight, render: (t) => <Text>{t.type}</Text>, sort: (t) => t.type },
  { key: "method", label: "Method", width: 210, icon: CreditCard, render: (t) => <MethodBadge method={t.method} />, sort: (t) => t.method },
  { key: "status", label: "Status", width: 140, icon: CircleDot, render: (t) => <Chip tone={t.status === "Pending" ? "gray" : "green"}>{t.status}</Chip>, sort: (t) => t.status },
  {
    key: "amt", label: "Amount", width: 150, icon: CircleDollarSign, sort: (t) => t.amount, value: (t) => t.amount, money: true,
    render: (t) => <Text>{t.amount < 0 ? `−${fmtMoney(-t.amount)}` : fmtMoney(t.amount)}</Text>,
  },
];

type Tab = "all" | "payments" | "refunds" | "pending";
export default function TransactionsPage() {
  const [tab, setTab] = useState<Tab>("all");
  const payments = transactions.filter((t) => t.type === "Payment");
  const refunds = transactions.filter((t) => t.type === "Refund");
  const pending = transactions.filter((t) => t.status === "Pending");
  const rows = { all: transactions, payments, refunds, pending }[tab];

  const in30 = (t: Transaction) => daysBetween(t.date, NOW) <= 30;
  const paid30 = payments.filter(in30), ref30 = refunds.filter(in30);
  const ytd = transactions.filter((t) => t.date.startsWith("2026"));
  const ytdPayments = ytd.filter((t) => t.type === "Payment").length;

  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[
        { id: "all", label: "All transactions", count: transactions.length },
        { id: "payments", label: "Payments", count: payments.length },
        { id: "refunds", label: "Refunds", count: refunds.length },
        { id: "pending", label: "Pending", count: pending.length },
      ]}>
        <div className="mr-1 hidden items-center gap-2 lg:flex">
          <span className="flex size-5 items-center justify-center rounded-[5px] bg-[#635bff] text-[11px] font-bold text-white">S</span>
          <span className="size-1.5 rounded-full bg-green-500" />
          <span className="text-label text-textSecondary">Synced 12 min ago</span>
          <button aria-label="Sync now" className="flex size-control items-center justify-center rounded-md hover:bg-panelBg"><RefreshCw className="size-4 text-textMuted" strokeWidth={1.5} /></button>
        </div>
        <GhostButton icon={SlidersHorizontal}>Edit View</GhostButton>
        <GhostButton icon={Download}>Export</GhostButton>
      </Toolbar>
      <StatStrip stats={[
        { label: "Collected, last 30 days", value: fmtMoney(paid30.reduce((s, t) => s + t.amount, 0)), sub: `${paid30.length} payments` },
        { label: "Refunded, last 30 days", value: fmtMoney(-ref30.reduce((s, t) => s + t.amount, 0)), sub: `${ref30.length} ${ref30.length === 1 ? "refund" : "refunds"}` },
        { label: "Pending", value: fmtMoney(pending.reduce((s, t) => s + t.amount, 0)), sub: "Bank transfers still clearing" },
        { label: "Net collected, 2026 to date", value: fmtMoney(ytd.reduce((s, t) => s + t.amount, 0)), sub: `${ytdPayments} payments, net of refunds` },
      ]} />
      <DataTable rows={rows} columns={columns} label="Transactions" selectable={false} />
    </Page>
  );
}
