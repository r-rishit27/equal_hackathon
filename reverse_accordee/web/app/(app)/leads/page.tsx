"use client";
import { useState } from "react";
import { Building2, CalendarDays, CircleDot, Download, Hash, Kanban, Percent, Plus, Radio, Table2, User, ArrowRight } from "lucide-react";
import { Avatar, Chip, DataTable, GhostButton, Page, PrimaryButton, StatStrip, Text, Toolbar, WithAvatar, type Column, type Tone } from "@/components/ui";
import { fmtDate, fmtMoney, fmtRelative, LEAD_STAGES, leads, metrics, type Lead, type LeadStage } from "@/lib/data";

const TONE: Record<LeadStage, Tone> = { New: "gray", Qualified: "blue", Demo: "violet", Proposal: "amber", Negotiation: "amber", Won: "green", Lost: "red" };
const columns: Column<Lead>[] = [
  { key: "co", label: "Company", width: 260, icon: Building2, render: (l) => <div className="flex min-w-0 items-center gap-2"><WithAvatar name={l.company} square />{l.kind === "Upsell" && <Chip tone="violet">Upsell</Chip>}</div>, sort: (l) => l.company },
  { key: "stage", label: "Stage", width: 150, icon: CircleDot, render: (l) => <Chip tone={TONE[l.stage]}>{l.stage}</Chip>, sort: (l) => LEAD_STAGES.indexOf(l.stage) },
  { key: "value", label: "Value", width: 140, icon: Hash, render: (l) => <Text>{fmtMoney(l.value)} <span className="text-textMuted">/ yr</span></Text>, sort: (l) => l.value },
  { key: "p", label: "Probability", width: 140, icon: Percent, render: (l) => <div className="flex items-center gap-2"><div className="h-1 w-12 overflow-hidden rounded-full bg-panelBg"><div className="h-full bg-brand" style={{ width: `${l.probability}%` }} /></div><Text muted>{l.probability}%</Text></div>, sort: (l) => l.probability },
  { key: "close", label: "Expected close", width: 150, icon: CalendarDays, render: (l) => <Text muted>{fmtDate(l.expectedClose)}</Text>, sort: (l) => l.expectedClose },
  { key: "contact", label: "Contact", width: 260, icon: User, render: (l) => <WithAvatar name={l.contact} /> },
  { key: "next", label: "Next step", width: 240, icon: ArrowRight, render: (l) => <Text muted>{l.nextStep}</Text> },
  { key: "src", label: "Source", width: 140, icon: Radio, render: (l) => <Text muted>{l.source}</Text> },
  { key: "owner", label: "Owner", width: 190, icon: User, render: (l) => <WithAvatar name={l.owner} /> },
  { key: "act", label: "Last activity", width: 150, icon: CalendarDays, render: (l) => <Text muted>{fmtRelative(l.lastActivity)}</Text>, sort: (l) => l.lastActivity },
];

export default function LeadsPage() {
  const [view, setView] = useState<"table" | "board">("table");
  const closedDays = 43;
  return (
    <Page>
      <Toolbar value={view} onChange={setView} tabs={[{ id: "table", label: "Table", icon: Table2 }, { id: "board", label: "Pipeline", icon: Kanban }]}>
        <GhostButton icon={Download}>Export</GhostButton>
        <PrimaryButton icon={Plus}>New lead</PrimaryButton>
      </Toolbar>
      <StatStrip stats={[
        { label: "Open pipeline", value: fmtMoney(metrics.pipeline), sub: `${metrics.openLeads.length} open leads` },
        { label: "Weighted", value: fmtMoney(metrics.weighted), sub: "Value × probability" },
        { label: "Win rate", value: `${metrics.winRate}%`, sub: "Won ÷ closed" },
        { label: "Days to close", value: String(closedDays), sub: "Average for won leads" },
      ]} />
      {view === "table" ? <DataTable rows={leads} columns={columns} label="Leads" /> : (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-4">
          {LEAD_STAGES.map((s) => {
            const col = leads.filter((l) => l.stage === s);
            return (
              <div key={s} className="flex w-64 shrink-0 flex-col rounded-xl bg-panelBg p-2">
                <div className="flex items-center justify-between px-1.5 pb-2"><span className="flex items-center gap-2"><Chip tone={TONE[s]}>{s}</Chip><span className="text-caption text-textMuted">{col.length}</span></span><span className="text-caption text-textMuted tabular-nums">{fmtMoney(col.reduce((x, l) => x + l.value, 0))}</span></div>
                <div className="flex min-h-0 flex-col gap-2 overflow-y-auto">
                  {col.map((l) => (
                    <div key={l.id} className="rounded-lg border border-borderDark bg-appBg p-3 shadow-xs">
                      <div className="flex items-center gap-2"><Avatar name={l.company} square /><span className="truncate text-label font-medium">{l.company}</span></div>
                      <div className="mt-1.5 truncate text-caption text-textMuted">{l.nextStep}</div>
                      <div className="mt-2 flex justify-between text-caption"><span className="text-textMuted">{l.owner}</span><span className="tabular-nums">{fmtMoney(l.value)}</span></div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Page>
  );
}
