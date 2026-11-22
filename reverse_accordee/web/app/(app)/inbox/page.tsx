"use client";
import { useState } from "react";
import { CheckCheck, FileSignature, MessageSquare, Receipt } from "lucide-react";
import { Avatar, cn, GhostButton, Page, Toolbar } from "@/components/ui";
import { customerById, fmtRelative, inbox as seed, type InboxItem } from "@/lib/data";

const ICON = { Money: Receipt, Contracts: FileSignature, Messages: MessageSquare, Leads: MessageSquare, Tasks: CheckCheck } as const;
export default function InboxPage() {
  const [items, setItems] = useState(seed);
  const [tab, setTab] = useState<"all" | "unread" | InboxItem["kind"]>("all");
  const rows = items.filter((i) => tab === "all" || (tab === "unread" ? i.unread : i.kind === tab));
  const [sel, setSel] = useState<string | null>(null);
  const cur = items.find((i) => i.id === sel);
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all" as const, label: "All" }, { id: "unread" as const, label: "Unread", count: items.filter((i) => i.unread).length }, ...(["Messages", "Money", "Contracts"] as const).map((k) => ({ id: k, label: k, count: items.filter((i) => i.kind === k).length }))]}>
        <GhostButton icon={CheckCheck} onClick={() => setItems((xs) => xs.map((x) => ({ ...x, unread: false })))}>Mark all as read</GhostButton>
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <ul className="min-h-0 w-full overflow-y-auto border-r border-borderDark md:w-[440px]">
          {rows.map((i) => {
            const Icon = ICON[i.kind];
            return (
              <li key={i.id}>
                <button onClick={() => { setSel(i.id); setItems((xs) => xs.map((x) => (x.id === i.id ? { ...x, unread: false } : x))); }}
                  className={cn("flex w-full items-start gap-3 border-b border-borderDark px-4 py-3 text-left hover:bg-sidebarBg", sel === i.id && "bg-panelBg")}>
                  <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-panelBg"><Icon className="size-3.5 text-textMuted" /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2"><span className={cn("truncate text-label", i.unread && "font-medium")}>{i.title}</span>{i.unread && <span className="size-1.5 shrink-0 rounded-full bg-blue-500" />}<span className="ml-auto shrink-0 text-caption text-textMuted">{fmtRelative(i.at)}</span></div>
                    <div className="mt-0.5 truncate text-caption text-textMuted">{i.body}</div>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="hidden flex-1 items-center justify-center md:flex">
          {cur ? (
            <div className="max-w-md animate-fade-in p-8">
              <div className="flex items-center gap-2"><Avatar name={customerById(cur.customerId).name} hue={customerById(cur.customerId).hue} size={24} square /><span className="text-label text-textMuted">{customerById(cur.customerId).name}</span></div>
              <h2 className="mt-3 text-heading">{cur.title}</h2>
              <p className="mt-2 text-body text-textSecondary">{cur.body}</p>
            </div>
          ) : <span className="text-label text-textMuted">Select an update</span>}
        </div>
      </div>
    </Page>
  );
}
