"use client";
import { useState } from "react";
import { Plus, Video } from "lucide-react";
import { Page, PrimaryButton, Toolbar } from "@/components/ui";
import { customerById, meetings } from "@/lib/data";

const DAYS = ["Mon 26", "Tue 27", "Wed 28", "Thu 29", "Fri 30"];
const HOURS = Array.from({ length: 11 }, (_, i) => 8 + i);
const PROVIDER = { Meet: "border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-500/10 dark:text-emerald-100", Zoom: "border-blue-500 bg-blue-50 text-blue-900 dark:bg-blue-500/10 dark:text-blue-100", Teams: "border-violet-500 bg-violet-50 text-violet-900 dark:bg-violet-500/10 dark:text-violet-100" } as Record<string, string>;

export default function MeetingsPage() {
  const [tab, setTab] = useState("week");
  const H = 56;
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "week", label: "Week" }, { id: "month", label: "Month" }]}>
        <span className="mr-2 text-label text-textSecondary">October 26 – 30, 2026</span>
        <PrimaryButton icon={Plus}>New meeting</PrimaryButton>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="grid min-w-[720px]" style={{ gridTemplateColumns: `56px repeat(${DAYS.length}, 1fr)` }}>
          <div className="sticky top-0 z-10 border-b border-borderDark bg-appBg" />
          {DAYS.map((d, i) => <div key={d} className={`sticky top-0 z-10 flex h-10 items-center justify-center border-b border-l border-borderDark bg-appBg text-label ${i === 0 ? "font-medium" : "text-textSecondary"}`}>{d}</div>)}
          <div>{HOURS.map((h) => <div key={h} className="pr-2 text-right text-caption text-textMuted" style={{ height: H }}>{h > 12 ? h - 12 : h} {h >= 12 ? "PM" : "AM"}</div>)}</div>
          {DAYS.map((d, day) => (
            <div key={d} className="relative border-l border-borderDark" style={{ height: HOURS.length * H }}>
              {HOURS.map((h) => <div key={h} className="border-b border-borderDark/60" style={{ height: H }} />)}
              {meetings.filter((m) => m.day === day).map((m) => (
                <div key={m.id} className={`absolute inset-x-1 overflow-hidden rounded-md border-l-2 px-2 py-1 ${PROVIDER[m.provider]}`} style={{ top: (m.start - 8) * H + 2, height: m.length * H - 4 }}>
                  <div className="truncate text-caption font-medium">{m.title}</div>
                  <div className="flex items-center gap-1 truncate text-micro opacity-80"><Video className="size-3" />{customerById(m.customerId).name}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </Page>
  );
}
