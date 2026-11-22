"use client";
import Link from "next/link";
import { ArrowUp, Maximize2, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { answer, SUGGESTIONS, type Reply } from "@/lib/agent";
import { cn } from "@/components/ui";
import { useShell } from "@/components/shell/ShellProvider";
import { AgentFlower, AGENTS, type AgentId } from "./AgentFlower";

type Msg = { id: string; role: "user" | "assistant"; text: string; reply?: Reply };

/** Tiny markdown: ## headings, **bold**, - lists, > quotes. */
function Md({ text }: { text: string }) {
  const inline = (s: string): ReactNode[] => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") ? <strong key={i} className="font-medium">{p.slice(2, -2)}</strong> : p));
  return (
    <div className="flex flex-col gap-1.5 text-body leading-6">
      {text.split("\n").map((l, i) => {
        if (l.startsWith("## ")) return <h3 key={i} className="text-title font-medium">{inline(l.slice(3))}</h3>;
        if (l.startsWith("- ")) return <div key={i} className="flex gap-2 pl-1"><span className="text-textMuted">•</span><span>{inline(l.slice(2))}</span></div>;
        if (l.startsWith(">")) return <div key={i} className="border-l-2 border-borderDark pl-3 text-textSecondary">{inline(l.replace(/^>\s?/, "")) || " "}</div>;
        if (!l.trim()) return <div key={i} className="h-1" />;
        return <p key={i}>{inline(l)}</p>;
      })}
    </div>
  );
}

/** Reveals text a couple of words at a time. */
function Typewriter({ text, onDone }: { text: string; onDone: () => void }) {
  const words = text.split(/(\s+)/);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (n >= words.length) { onDone(); return; }
    const t = setTimeout(() => setN((x) => x + 4), 30);
    return () => clearTimeout(t);
  }, [n, words.length, onDone]);
  return <Md text={words.slice(0, n).join("")} />;
}

export function useConversation() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [thinking, setThinking] = useState(false);
  const [typing, setTyping] = useState<string | null>(null);
  const send = (q: string) => {
    const text = q.trim();
    if (!text || thinking) return;
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text }]);
    setThinking(true);
    setTimeout(() => {
      const reply = answer(text);
      const id = crypto.randomUUID();
      setMessages((m) => [...m, { id, role: "assistant", text: reply.text, reply }]);
      setTyping(id);
      setThinking(false);
    }, 650);
  };
  return { messages, thinking, typing, setTyping, send, reset: () => setMessages([]) };
}

export function Conversation({ conv, agent }: { conv: ReturnType<typeof useConversation>; agent: AgentId }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [conv.messages.length, conv.thinking]);
  return (
    <div className="flex flex-col gap-5">
      {conv.messages.map((m) =>
        m.role === "user" ? (
          <div key={m.id} className="ml-auto max-w-[85%] animate-rise rounded-2xl rounded-br-md bg-panelBg px-3.5 py-2 text-body">{m.text}</div>
        ) : (
          <div key={m.id} className="flex animate-rise gap-3">
            <span className="mt-1"><AgentFlower agent={agent} size={18} /></span>
            <div className="min-w-0 flex-1">
              {m.reply && m.reply.toolsUsed > 0 && <div className="mb-1.5 text-caption text-textMuted">Read {m.reply.toolsUsed} {m.reply.toolsUsed === 1 ? "source" : "sources"}</div>}
              {conv.typing === m.id ? <Typewriter text={m.text} onDone={() => conv.setTyping(null)} /> : <Md text={m.text} />}
              {conv.typing !== m.id && m.reply?.links && (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {m.reply.links.map((l) => <Link key={l.href} href={l.href} className="rounded-md border border-borderDark px-2 py-1 text-caption text-textSecondary hover:bg-panelBg">{l.label} →</Link>)}
                </div>
              )}
            </div>
          </div>
        ),
      )}
      {conv.thinking && (
        <div className="flex items-center gap-3 text-label text-textMuted">
          <AgentFlower agent={agent} size={18} spinning />Looking through your records…
        </div>
      )}
      <div ref={end} />
    </div>
  );
}

export function Composer({ onSend, placeholder, autoFocus }: { onSend: (q: string) => void; placeholder: string; autoFocus?: boolean }) {
  const [v, setV] = useState("");
  const submit = () => { if (v.trim()) { onSend(v); setV(""); } };
  return (
    <div className="rounded-2xl border border-borderDark bg-appBg p-2 shadow-sm focus-within:border-textMuted/40">
      <textarea autoFocus={autoFocus} value={v} onChange={(e) => setV(e.target.value)} rows={2} placeholder={placeholder}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
        className="w-full resize-none bg-transparent px-2 py-1 text-body outline-none placeholder:text-textMuted" />
      <div className="flex items-center justify-between px-1">
        <span className="text-caption text-textMuted">Answers from your records</span>
        <button onClick={submit} disabled={!v.trim()} aria-label="Send" className={cn("flex size-7 items-center justify-center rounded-full transition-colors", v.trim() ? "bg-brand text-brandFg" : "bg-kbdBg text-textMuted")}>
          <ArrowUp className="size-4" />
        </button>
      </div>
    </div>
  );
}

export function ChatPanel() {
  const { chatOpen, setChatOpen, chatSeed } = useShell();
  const conv = useConversation();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (chatSeed && chatSeed !== last.current) { last.current = chatSeed; conv.send(chatSeed.split("\u0000")[0]); }
  }, [chatSeed]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!chatOpen) return null;
  return (
    <div className="fixed right-4 bottom-4 z-40 flex h-[min(680px,calc(100vh-32px))] w-[min(560px,calc(100vw-32px))] animate-rise flex-col overflow-hidden rounded-2xl border border-borderDark bg-appBg shadow-[0_32px_100px_-24px_rgba(0,0,0,0.35)]">
      <div className="flex h-toolbar shrink-0 items-center gap-2 border-b border-borderDark px-3">
        <AgentFlower size={16} />
        <span className="text-label font-medium">{AGENTS[0].name}</span>
        <span className="text-caption text-textMuted">{AGENTS[0].note}</span>
        <span className="ml-auto" />
        <Link href="/" onClick={() => setChatOpen(false)} aria-label="Open full page" className="flex size-control items-center justify-center rounded-md hover:bg-panelBg"><Maximize2 className="size-3.5 text-textMuted" /></Link>
        <button onClick={() => setChatOpen(false)} aria-label="Close" className="flex size-control items-center justify-center rounded-md hover:bg-panelBg"><X className="size-4 text-textMuted" /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {conv.messages.length === 0 ? (
          <div className="flex flex-col gap-2">
            <p className="mb-2 text-label text-textMuted">Ask anything about your customers, contracts or money.</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => conv.send(s)} className="rounded-lg border border-borderDark px-3 py-2 text-left text-label text-textSecondary hover:bg-panelBg">{s}</button>
            ))}
          </div>
        ) : <Conversation conv={conv} agent="atlas" />}
      </div>
      <div className="shrink-0 p-3"><Composer onSend={conv.send} placeholder="Ask Atlas…" autoFocus /></div>
    </div>
  );
}
