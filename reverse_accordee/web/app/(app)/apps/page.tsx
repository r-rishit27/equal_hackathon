"use client";
import { useState } from "react";
import { Avatar, cn, Page, Toolbar } from "@/components/ui";

const APPS = [
  ["Stripe", "Finance", "Import payments and refunds into Transactions", true], ["Slack", "Communication", "Post workflow updates and alerts to channels", true],
  ["Notion", "Collaboration", "Link pages to customers and contracts", false], ["Gmail", "Emails", "Sync email threads to customer timelines", true],
  ["Google Calendar", "Collaboration", "Log meetings with customer contacts", true], ["Zoom", "Communication", "Record calls and get AI notes", false],
  ["HubSpot", "CRM", "Import contacts and deals", false], ["QuickBooks", "Finance", "Sync invoices and payments", false],
  ["GitHub", "Development", "Link issues to customer feedback", false], ["Linear", "Development", "Turn feature requests into issues", true],
  ["Intercom", "Communication", "Bring support chats into Messages", false], ["DocuSign", "Others", "Send contracts for signature", true],
] as const;

export default function AppsPage() {
  const [tab, setTab] = useState("all");
  const [on, setOn] = useState<Record<string, boolean>>(Object.fromEntries(APPS.map((a) => [a[0], a[3]])));
  const cats = [...new Set(APPS.map((a) => a[1]))];
  const rows = APPS.filter((a) => tab === "all" || (tab === "connected" ? on[a[0]] : a[1] === tab));
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All apps", count: APPS.length }, { id: "connected", label: "Connected", count: Object.values(on).filter(Boolean).length }, ...cats.map((c) => ({ id: c, label: c }))]} />
      <div className="grid min-h-0 flex-1 auto-rows-min grid-cols-1 gap-3 overflow-y-auto p-4 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map(([name, cat, desc]) => (
          <div key={name} className="flex animate-rise flex-col gap-3 rounded-xl border border-borderDark bg-card p-4">
            <div className="flex items-center gap-3"><Avatar name={name} size={32} square /><div><div className="text-label font-medium">{name}</div><div className="text-caption text-textMuted">{cat}</div></div>
              <button onClick={() => setOn((o) => ({ ...o, [name]: !o[name] }))} className={cn("ml-auto h-control rounded-md border px-2.5 text-label", on[name] ? "border-borderDark text-textSecondary hover:bg-panelBg" : "border-transparent bg-brand text-brandFg")}>{on[name] ? "Disconnect" : "Connect"}</button>
            </div>
            <p className="text-label text-textSecondary">{desc}</p>
          </div>
        ))}
      </div>
    </Page>
  );
}
