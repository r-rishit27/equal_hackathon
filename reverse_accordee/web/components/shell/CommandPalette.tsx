"use client";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { Building2, FileSignature, Receipt, Search } from "lucide-react";
import { useState } from "react";
import { contracts, customerById, customers, invoices } from "@/lib/data";
import { AgentFlower } from "@/components/agents/AgentFlower";
import { ALL_NAV } from "./nav";
import { useShell } from "./ShellProvider";

const itemCls = "flex h-10 cursor-pointer items-center gap-3 rounded-lg px-2.5 text-label select-none data-[selected=true]:bg-panelBg";

export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, askAgent } = useShell();
  const router = useRouter();
  const [q, setQ] = useState("");
  if (!paletteOpen) return null;
  const go = (href: string) => { setPaletteOpen(false); setQ(""); router.push(href); };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/20 pt-[12vh]" onClick={() => setPaletteOpen(false)}>
      <Command label="Search" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.key === "Escape" && setPaletteOpen(false)}
        className="w-[min(640px,calc(100vw-32px))] animate-rise overflow-hidden rounded-2xl border border-borderDark bg-appBg shadow-2xl">
        <div className="flex h-14 items-center gap-3 border-b border-borderDark px-4">
          <Search className="size-4 text-textMuted" />
          <Command.Input autoFocus value={q} onValueChange={setQ} placeholder="Search records, or ask a question…" className="h-full flex-1 bg-transparent text-body outline-none placeholder:text-textMuted" />
        </div>
        <Command.List className="max-h-[420px] overflow-y-auto p-2">
          <Command.Empty className="px-3 py-6 text-center text-label text-textMuted">No records match.</Command.Empty>
          {q.trim().length > 2 && (
            <Command.Item value={`ask ${q}`} onSelect={() => { setPaletteOpen(false); askAgent(q); setQ(""); }} className={itemCls}>
              <AgentFlower size={18} />
              <span className="truncate">Ask Atlas: “{q}”</span>
              <span className="ml-auto text-caption text-textMuted">Agent</span>
            </Command.Item>
          )}
          <Command.Group heading="Pages" className="text-caption text-textMuted [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
            {ALL_NAV.map((n) => (
              <Command.Item key={n.href} value={`page ${n.label}`} onSelect={() => go(n.href)} className={itemCls}>
                <n.icon className="size-4 text-textMuted" strokeWidth={1.5} /><span className="text-textPrimary">{n.label}</span>
              </Command.Item>
            ))}
          </Command.Group>
          {q && (
            <>
              <Command.Group heading="Customers" className="text-caption text-textMuted [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
                {customers.map((c) => (
                  <Command.Item key={c.id} value={`customer ${c.name} ${c.domain}`} onSelect={() => go("/customers")} className={itemCls}>
                    <Building2 className="size-4 text-textMuted" /><span className="text-textPrimary">{c.name}</span><span className="ml-auto">{c.city}</span>
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Contracts & invoices" className="text-caption text-textMuted [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
                {contracts.slice(0, 40).map((k) => (
                  <Command.Item key={k.id} value={`${k.id} ${customerById(k.customerId).name}`} onSelect={() => go("/contracts")} className={itemCls}>
                    <FileSignature className="size-4 text-textMuted" /><span className="text-textPrimary">{k.id}</span><span>{customerById(k.customerId).name}</span>
                  </Command.Item>
                ))}
                {invoices.slice(0, 60).map((i) => (
                  <Command.Item key={i.id} value={`${i.id} ${customerById(i.customerId).name}`} onSelect={() => go("/invoices")} className={itemCls}>
                    <Receipt className="size-4 text-textMuted" /><span className="text-textPrimary">{i.id}</span><span>{customerById(i.customerId).name}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            </>
          )}
        </Command.List>
      </Command>
    </div>
  );
}
