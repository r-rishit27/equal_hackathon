"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { Avatar, Page, PrimaryButton, Toolbar } from "@/components/ui";
import { customerById, fmtRelative, notes } from "@/lib/data";

export default function NotesPage() {
  const [tab, setTab] = useState("all");
  const rows = tab === "ai" ? notes.filter((n) => n.by === "AI notetaker") : notes;
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All notes", count: notes.length }, { id: "ai", label: "AI notes", count: notes.filter((n) => n.by === "AI notetaker").length }]}>
        <PrimaryButton icon={Plus}>New note</PrimaryButton>
      </Toolbar>
      <div className="grid min-h-0 flex-1 auto-rows-min grid-cols-1 gap-3 overflow-y-auto p-4 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map((n) => {
          const c = customerById(n.customerId);
          return (
            <article key={n.id} className="flex animate-rise flex-col gap-2 rounded-xl border border-borderDark bg-card p-4 transition-shadow hover:shadow-md">
              <div className="flex items-center gap-2 text-caption text-textMuted"><Avatar name={c.name} hue={c.hue} square />{c.name}<span className="ml-auto">{fmtRelative(n.at)}</span></div>
              <h3 className="text-label font-medium">{n.title}</h3>
              <p className="line-clamp-3 text-label text-textSecondary">{n.body}</p>
              <div className="mt-auto flex items-center gap-2 pt-1 text-caption text-textMuted"><Avatar name={n.by} />{n.by}</div>
            </article>
          );
        })}
      </div>
    </Page>
  );
}
