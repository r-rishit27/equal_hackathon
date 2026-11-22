"use client";
import { useState } from "react";
import { Archive, Inbox, PenSquare, Reply, Send, Star } from "lucide-react";
import { Avatar, cn, Page, PrimaryButton, Toolbar } from "@/components/ui";
import { customerById, emails, fmtRelative, ME } from "@/lib/data";
import { AgentFlower } from "@/components/agents/AgentFlower";

export default function EmailsPage() {
  const [tab, setTab] = useState("inbox");
  const [sel, setSel] = useState(emails[0].id);
  const [draft, setDraft] = useState("");
  const [writing, setWriting] = useState(false);
  const e = emails.find((x) => x.id === sel)!;
  const c = customerById(e.customerId);
  const aiDraft = () => {
    setWriting(true); setDraft("");
    const text = `Hi ${e.from.split(" ")[0]},\n\nThanks for your note about "${e.subject.toLowerCase()}". I'll look into it with the team and come back to you by Thursday with next steps.\n\nBest,\n${ME.name.split(" ")[0]}`;
    let i = 0;
    const t = setInterval(() => { i += 3; setDraft(text.slice(0, i)); if (i >= text.length) { clearInterval(t); setWriting(false); } }, 16);
  };
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "inbox", label: "Inbox", icon: Inbox, count: emails.filter((x) => x.unread).length }, { id: "starred", label: "Starred", icon: Star }, { id: "sent", label: "Sent", icon: Send }, { id: "archive", label: "Archive", icon: Archive }]}>
        <PrimaryButton icon={PenSquare}>New email</PrimaryButton>
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <ul className="min-h-0 w-full overflow-y-auto border-r border-borderDark md:w-[400px]">
          {emails.map((m) => (
            <li key={m.id}>
              <button onClick={() => { setSel(m.id); setDraft(""); }} className={cn("flex w-full flex-col gap-0.5 border-b border-borderDark px-4 py-3 text-left hover:bg-sidebarBg", sel === m.id && "bg-panelBg")}>
                <div className="flex items-center gap-2"><Avatar name={m.from} /><span className={cn("truncate text-label", m.unread && "font-medium")}>{m.from}</span><span className="ml-auto text-caption text-textMuted">{fmtRelative(m.at)}</span></div>
                <div className={cn("truncate text-label", m.unread ? "text-textPrimary" : "text-textSecondary")}>{m.subject}</div>
                <div className="truncate text-caption text-textMuted">{m.preview}</div>
              </button>
            </li>
          ))}
        </ul>
        <div className="hidden min-h-0 flex-1 flex-col overflow-y-auto md:flex">
          <div className="border-b border-borderDark px-6 py-4">
            <h2 className="text-heading">{e.subject}</h2>
            <div className="mt-2 flex items-center gap-2 text-label text-textMuted"><Avatar name={e.from} size={20} />{e.from} · {c.name}<span className="ml-auto">{fmtRelative(e.at)}</span></div>
          </div>
          <p className="px-6 py-5 text-body leading-7 text-textSecondary">Hi Jane,<br /><br />{e.preview}<br /><br />Thanks,<br />{e.from.split(" ")[0]}</p>
          <div className="mx-6 mb-6 rounded-xl border border-borderDark">
            <textarea value={draft} onChange={(x) => setDraft(x.target.value)} rows={7} placeholder={`Reply to ${e.from}…`} className="w-full resize-none bg-transparent p-3 text-body outline-none placeholder:text-textMuted" />
            <div className="flex items-center gap-2 border-t border-borderDark p-2">
              <PrimaryButton icon={Reply}>Send</PrimaryButton>
              <button onClick={aiDraft} disabled={writing} className="flex h-control items-center gap-1.5 rounded-md border border-borderDark px-2.5 text-label hover:bg-panelBg disabled:opacity-50"><AgentFlower size={14} spinning={writing} />{writing ? "Writing…" : "Draft with AI"}</button>
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
