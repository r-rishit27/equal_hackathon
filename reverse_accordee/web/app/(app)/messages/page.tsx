"use client";
import { useState } from "react";
import { Send } from "lucide-react";
import { Avatar, cn, Page, Toolbar } from "@/components/ui";
import { customers, fmtRelative, NOW, addDays } from "@/lib/data";

const threads = customers.slice(0, 12).map((c, i) => ({
  id: `th${i}`, customer: c, last: ["Thursday at 2pm is perfect. Thanks!", "Can you resend the invoice?", "We'd like to add five seats.", "Great call today!"][i % 4],
  at: addDays(NOW, -i * 0.7).toISOString(), unread: i < 4,
}));

export default function MessagesPage() {
  const [tab, setTab] = useState("all");
  const [sel, setSel] = useState(threads[0].id);
  const [msgs, setMsgs] = useState<Record<string, string[]>>({});
  const [v, setV] = useState("");
  const t = threads.find((x) => x.id === sel)!;
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All", count: threads.length }, { id: "unread", label: "Unread", count: threads.filter((x) => x.unread).length }]} />
      <div className="flex min-h-0 flex-1">
        <ul className="min-h-0 w-full overflow-y-auto border-r border-borderDark md:w-[360px]">
          {threads.filter((x) => tab === "all" || x.unread).map((x) => (
            <li key={x.id}><button onClick={() => setSel(x.id)} className={cn("flex w-full items-center gap-3 border-b border-borderDark px-4 py-3 text-left hover:bg-sidebarBg", sel === x.id && "bg-panelBg")}>
              <Avatar name={x.customer.contact} size={28} />
              <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className={cn("truncate text-label", x.unread && "font-medium")}>{x.customer.contact}</span><span className="ml-auto text-caption text-textMuted">{fmtRelative(x.at)}</span></div><div className="truncate text-caption text-textMuted">{x.customer.name} · {x.last}</div></div>
            </button></li>
          ))}
        </ul>
        <div className="hidden min-h-0 flex-1 flex-col md:flex">
          <div className="flex h-toolbar items-center gap-2 border-b border-borderDark px-4"><Avatar name={t.customer.contact} size={20} /><span className="text-label font-medium">{t.customer.contact}</span><span className="text-caption text-textMuted">{t.customer.name}</span></div>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-5">
            <div className="max-w-[70%] rounded-2xl rounded-bl-md bg-panelBg px-3.5 py-2 text-body">Hi Jane, are we still on for the quarterly check-in?</div>
            <div className="ml-auto max-w-[70%] rounded-2xl rounded-br-md bg-brand px-3.5 py-2 text-body text-brandFg">Yes! Does Thursday at 2pm work?</div>
            <div className="max-w-[70%] rounded-2xl rounded-bl-md bg-panelBg px-3.5 py-2 text-body">{t.last}</div>
            {(msgs[sel] ?? []).map((m, i) => <div key={i} className="ml-auto max-w-[70%] animate-rise rounded-2xl rounded-br-md bg-brand px-3.5 py-2 text-body text-brandFg">{m}</div>)}
          </div>
          <form className="flex gap-2 border-t border-borderDark p-3" onSubmit={(e) => { e.preventDefault(); if (!v.trim()) return; setMsgs((m) => ({ ...m, [sel]: [...(m[sel] ?? []), v] })); setV(""); }}>
            <input value={v} onChange={(e) => setV(e.target.value)} placeholder="Write a message…" className="h-control-lg flex-1 rounded-md border border-borderDark bg-transparent px-3 text-body outline-none" />
            <button className="flex size-control-lg items-center justify-center rounded-md bg-brand text-brandFg" aria-label="Send"><Send className="size-4" /></button>
          </form>
        </div>
      </div>
    </Page>
  );
}
