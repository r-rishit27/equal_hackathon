"use client";
import { useState } from "react";
import { CalendarClock, CircleDot, Hash, Plus, User, Workflow as WIcon, Zap } from "lucide-react";
import { cn, DataTable, Page, PrimaryButton, Text, Toolbar, WithAvatar, type Column } from "@/components/ui";
import { fmtRelative, workflows as seed, type Workflow } from "@/lib/data";

export default function WorkflowsPage() {
  const [rows, setRows] = useState(seed);
  const [tab, setTab] = useState("all");
  const toggle = (id: string) => setRows((r) => r.map((w) => (w.id === id ? { ...w, on: !w.on } : w)));
  const columns: Column<Workflow>[] = [
    { key: "n", label: "Workflow", width: 300, icon: WIcon, render: (w) => <Text>{w.name}</Text>, sort: (w) => w.name },
    { key: "s", label: "Status", width: 130, icon: CircleDot, render: (w) => (
      <button onClick={(e) => { e.stopPropagation(); toggle(w.id); }} className="flex items-center gap-2" aria-pressed={w.on}>
        <span className={cn("relative h-4 w-7 rounded-full transition-colors", w.on ? "bg-green-500" : "bg-kbdBg")}><span className={cn("absolute top-0.5 size-3 rounded-full bg-white shadow transition-[left]", w.on ? "left-3.5" : "left-0.5")} /></span>
        <span className="text-label text-textSecondary">{w.on ? "On" : "Paused"}</span>
      </button>) },
    { key: "t", label: "Trigger", width: 260, icon: Zap, render: (w) => <Text muted>{w.trigger}</Text> },
    { key: "sc", label: "Schedule", width: 190, icon: CalendarClock, render: (w) => <Text muted>{w.schedule}</Text> },
    { key: "st", label: "Steps", width: 200, icon: Hash, render: (w) => <Text>{w.steps}</Text> },
    { key: "l", label: "Last run", width: 170, render: (w) => <Text muted>{w.lastRun ? fmtRelative(w.lastRun) : "Never"}</Text> },
    { key: "o", label: "Owner", width: 200, icon: User, render: (w) => <WithAvatar name={w.owner} /> },
  ];
  const shown = tab === "on" ? rows.filter((w) => w.on) : tab === "paused" ? rows.filter((w) => !w.on) : rows;
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All", count: rows.length }, { id: "on", label: "On", count: rows.filter((w) => w.on).length }, { id: "paused", label: "Paused", count: rows.filter((w) => !w.on).length }]}>
        <PrimaryButton icon={Plus}>New workflow</PrimaryButton>
      </Toolbar>
      <DataTable rows={shown} columns={columns} label="Workflows" selectable={false} />
    </Page>
  );
}
