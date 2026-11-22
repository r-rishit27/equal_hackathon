"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { Avatar, Chip, cn, Page, PrimaryButton, Toolbar } from "@/components/ui";
import { customerById, daysBetween, fmtDate, NOW, tasks as seed, type Task } from "@/lib/data";

export default function TasksPage() {
  const [tasks, setTasks] = useState(seed);
  const [tab, setTab] = useState("open");
  const today = NOW.toISOString().slice(0, 10);
  const groups: [string, Task[]][] = tab === "done" ? [["Done", tasks.filter((t) => t.done)]] : [
    ["Overdue", tasks.filter((t) => !t.done && t.due < today)],
    ["Today", tasks.filter((t) => !t.done && t.due === today)],
    ["Upcoming", tasks.filter((t) => !t.done && t.due > today).sort((a, b) => (a.due < b.due ? -1 : 1))],
  ];
  const toggle = (id: string) => setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "open", label: "Open", count: tasks.filter((t) => !t.done).length }, { id: "done", label: "Done", count: tasks.filter((t) => t.done).length }]}>
        <PrimaryButton icon={Plus}>New task</PrimaryButton>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {groups.map(([label, list]) => list.length > 0 && (
          <section key={label}>
            <h3 className="sticky top-0 z-10 flex h-9 items-center gap-2 border-b border-borderDark bg-sidebarBg px-4 text-caption text-textMuted">{label}<span className="tabular-nums">{list.length}</span></h3>
            <ul>
              {list.map((t) => {
                const late = daysBetween(t.due, NOW);
                const c = customerById(t.customerId);
                return (
                  <li key={t.id} className="flex h-12 items-center gap-3 border-b border-borderDark px-4 hover:bg-sidebarBg">
                    <input type="checkbox" className="crm-check rounded-full" checked={t.done} onChange={() => toggle(t.id)} aria-label="Done" />
                    <div className="min-w-0 flex-1">
                      <div className={cn("truncate text-label", t.done && "text-textMuted line-through")}>{t.title}</div>
                      <div className="truncate text-caption text-textMuted">{t.record} · {c.name}</div>
                    </div>
                    <span className={cn("hidden text-caption sm:block", late > 0 && !t.done ? "text-red-500" : "text-textMuted")}>{late > 0 && !t.done ? `${late} days late` : fmtDate(t.due)}</span>
                    <Chip tone={t.priority === "High" ? "red" : t.priority === "Medium" ? "amber" : "gray"}>{t.priority}</Chip>
                    <span className="hidden w-32 items-center gap-2 md:flex"><Avatar name={t.owner} /><span className="truncate text-label text-textSecondary">{t.owner}</span></span>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </Page>
  );
}
