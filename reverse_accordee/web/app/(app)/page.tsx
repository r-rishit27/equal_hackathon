"use client";
import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { Composer, Conversation, useConversation } from "@/components/agents/Chat";
import { AgentFlower, AGENTS, type AgentId } from "@/components/agents/AgentFlower";
import { SUGGESTIONS } from "@/lib/agent";
import { cn, Page } from "@/components/ui";
import { ME } from "@/lib/data";

export default function AgentsPage() {
  const conv = useConversation();
  const [agent, setAgent] = useState<AgentId>("atlas");
  const a = AGENTS.find((x) => x.id === agent)!;
  const started = conv.messages.length > 0;

  return (
    <Page>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[720px] px-4">
            {!started ? (
              <div className="flex flex-col items-center pt-[14vh] text-center">
                <AgentFlower agent={agent} size={44} />
                <h1 className="mt-5 font-serif text-display-sm">Good morning, {ME.name.split(" ")[0]}</h1>
                <p className="mt-1.5 text-body text-textMuted">{a.name} · {a.note}. Answers come from your records.</p>
                <div className="mt-6 flex flex-wrap justify-center gap-1.5">
                  {AGENTS.map((x) => (
                    <button key={x.id} onClick={() => setAgent(x.id)} className={cn("flex h-control items-center gap-1.5 rounded-full border px-2.5 text-label transition-colors", x.id === agent ? "border-textMuted/40 bg-panelBg" : "border-borderDark text-textSecondary hover:bg-panelBg")}>
                      <AgentFlower agent={x.id} size={14} />{x.name}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="py-6">
                <div className="mb-4 flex justify-end">
                  <button onClick={conv.reset} className="flex items-center gap-1.5 text-caption text-textMuted hover:text-textPrimary"><RotateCcw className="size-3" />New chat</button>
                </div>
                <Conversation conv={conv} agent={agent} />
              </div>
            )}
          </div>
        </div>
        <div className="mx-auto w-full max-w-[720px] shrink-0 px-4 pb-6">
          {!started && (
            <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => conv.send(s)} className="rounded-xl border border-borderDark px-3.5 py-2.5 text-left text-label text-textSecondary transition-colors hover:bg-panelBg">{s}</button>
              ))}
            </div>
          )}
          <Composer onSend={conv.send} placeholder={`Ask ${a.name} about customers, contracts, invoices…`} autoFocus />
        </div>
      </div>
    </Page>
  );
}
