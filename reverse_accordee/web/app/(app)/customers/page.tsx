"use client";
import { useState } from "react";
import { Building2, CalendarDays, Download, Globe, Hash, Kanban, LayoutList, Mail, MapPin, Plus, SlidersHorizontal, Table2, Tag, User, Users, Activity, Pencil } from "lucide-react";
import { Avatar, Chip, DataTable, Divider, GhostButton, Page, PrimaryButton, StatStrip, Text, Toolbar, WithAvatar, WithFlag, WebsiteLink, type Column, type Tone } from "@/components/ui";
import { contracts, customers, fmtMoney, fmtRelative, isLive, metrics, type Customer, type Health } from "@/lib/data";

const HEALTH: Record<Health, Tone> = { Excellent: "green", Good: "blue", Normal: "gray", "At risk": "red" };
const arrOf = (id: string) => contracts.filter((c) => c.customerId === id && isLive(c)).reduce((s, c) => s + c.annualValue, 0);

const columns: Column<Customer>[] = [
  { key: "name", label: "Company", width: 266, icon: Building2, render: (c) => <WithAvatar name={c.name} hue={c.hue} square />, sort: (c) => c.name },
  { key: "loc", label: "Location", width: 293, icon: MapPin, render: (c) => <WithFlag country={c.country}>{c.city}, {c.country}</WithFlag>, sort: (c) => c.country },
  { key: "founder", label: "Founder", width: 221, icon: User, render: (c) => <WithAvatar name={c.founder} /> },
  { key: "emp", label: "Employees", width: 195, icon: Users, render: (c) => <Text>{c.employees}</Text> },
  { key: "web", label: "Website", width: 217, icon: Globe, render: (c) => <WebsiteLink domain={c.domain} /> },
  { key: "tags", label: "Tags", width: 296, icon: Tag, render: (c) => <div className="flex gap-1.5"><Chip tone="green">{c.tags[0]}</Chip><Chip tone="blue">{c.tags[1]}</Chip></div> },
  { key: "health", label: "Health", width: 195, icon: Activity, render: (c) => <Chip tone={HEALTH[c.health]}>{c.health}</Chip>, sort: (c) => c.health },
  { key: "arr", label: "ARR", width: 210, icon: Hash, render: (c) => <Text>{fmtMoney(arrOf(c.id))}</Text>, sort: (c) => arrOf(c.id), value: (c) => arrOf(c.id), money: true },
  { key: "owner", label: "Owner", width: 260, icon: User, render: (c) => <WithAvatar name={c.owner} /> },
  { key: "stage", label: "Funding", width: 180, icon: Tag, render: (c) => <Text muted>{c.stage}</Text> },
  { key: "founded", label: "Founded", width: 180, icon: CalendarDays, render: (c) => <Text>{c.founded}</Text> },
  { key: "email", label: "Email", width: 230, icon: Mail, render: (c) => <a href={`mailto:${c.email}`} className="truncate text-label text-blue-600 hover:underline dark:text-blue-400">{c.email}</a> },
  { key: "last", label: "Last interaction", width: 250, icon: CalendarDays, render: (c) => <Text muted>{fmtRelative(c.lastInteraction)}</Text>, sort: (c) => c.lastInteraction },
];

export default function CustomersPage() {
  const [view, setView] = useState<"table" | "list" | "kanban">("table");
  return (
    <Page>
      <Toolbar value={view} onChange={setView} tabs={[{ id: "table", label: "Table View", icon: Table2 }, { id: "list", label: "List View", icon: LayoutList }, { id: "kanban", label: "Kanban", icon: Kanban }]}>
        <div className="hidden items-center gap-1 md:flex"><GhostButton icon={Download}>Export</GhostButton><Divider /><GhostButton icon={SlidersHorizontal}>Filter & Sort</GhostButton><GhostButton icon={Pencil}>Edit View</GhostButton><Divider /></div>
        <PrimaryButton icon={Plus}>Add Company</PrimaryButton>
      </Toolbar>
      <StatStrip stats={[
        { label: "Customers", value: String(customers.length), sub: `${new Set(contracts.filter(isLive).map((c) => c.customerId)).size} with a live contract` },
        { label: "Annual recurring revenue", value: fmtMoney(metrics.arr), sub: `${metrics.liveCount} live contracts` },
        { label: "At risk", value: String(customers.filter((c) => c.health === "At risk").length), sub: "Health below normal" },
        { label: "Owed to you", value: fmtMoney(metrics.owed), sub: `${fmtMoney(metrics.overdueAmt)} overdue` },
      ]} />
      {view === "table" && <DataTable rows={customers} columns={columns} label="Customers" />}
      {view === "list" && (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {customers.map((c) => (
            <div key={c.id} className="flex h-14 items-center gap-3 border-b border-borderDark px-5 hover:bg-sidebarBg">
              <Avatar name={c.name} hue={c.hue} size={28} square />
              <div className="min-w-0 flex-1"><div className="truncate text-label font-medium">{c.name}</div><div className="truncate text-caption text-textMuted">{c.industry} · {c.city}, {c.country}</div></div>
              <Chip tone={HEALTH[c.health]}>{c.health}</Chip>
              <span className="w-28 text-right text-label tabular-nums">{fmtMoney(arrOf(c.id))}</span>
            </div>
          ))}
        </div>
      )}
      {view === "kanban" && (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-4">
          {(Object.keys(HEALTH) as Health[]).map((h) => {
            const col = customers.filter((c) => c.health === h);
            return (
              <div key={h} className="flex w-72 shrink-0 flex-col rounded-xl bg-panelBg p-2">
                <div className="flex items-center gap-2 px-1.5 pb-2"><Chip tone={HEALTH[h]}>{h}</Chip><span className="text-caption text-textMuted">{col.length}</span></div>
                <div className="flex min-h-0 flex-col gap-2 overflow-y-auto">
                  {col.map((c) => (
                    <div key={c.id} className="rounded-lg border border-borderDark bg-appBg p-3 shadow-xs">
                      <div className="flex items-center gap-2"><Avatar name={c.name} hue={c.hue} square /><span className="truncate text-label font-medium">{c.name}</span></div>
                      <div className="mt-2 flex justify-between text-caption text-textMuted"><span>{c.owner}</span><span className="tabular-nums">{fmtMoney(arrOf(c.id))}</span></div>
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
