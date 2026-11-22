"use client";
import { Monitor, Moon, Sun } from "lucide-react";
import { Avatar, cn, Page } from "@/components/ui";
import { ACCENTS, useShell, type Theme } from "@/components/shell/ShellProvider";
import { AGENTS, AgentFlower } from "@/components/agents/AgentFlower";
import { ME, TEAM } from "@/lib/data";

function Section({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-4 border-b border-borderDark py-6 md:grid-cols-[240px_1fr]">
      <div><h2 className="text-label font-medium">{title}</h2><p className="mt-1 text-caption text-textMuted">{desc}</p></div>
      <div>{children}</div>
    </section>
  );
}

export default function SettingsPage() {
  const { theme, setTheme, accent, setAccent } = useShell();
  return (
    <Page>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-8">
          <h1 className="font-serif text-display-sm">Settings</h1>
          <Section title="Profile" desc="How you appear to your team and customers.">
            <div className="flex items-center gap-3"><Avatar name={ME.name} hue={ME.hue} size={40} /><div><div className="text-label font-medium">{ME.name}</div><div className="text-caption text-textMuted">{ME.email} · {ME.role}</div></div></div>
          </Section>
          <Section title="Theme" desc="System follows your device's light or dark setting.">
            <div className="flex gap-2">
              {([["light", Sun], ["dark", Moon], ["system", Monitor]] as [Theme, typeof Sun][]).map(([t, I]) => (
                <button key={t} onClick={() => setTheme(t)} className={cn("flex h-control-lg items-center gap-2 rounded-md border px-3 text-label capitalize", theme === t ? "border-textMuted/50 bg-panelBg" : "border-borderDark text-textSecondary hover:bg-panelBg")}><I className="size-4" />{t}</button>
              ))}
            </div>
          </Section>
          <Section title="Theme colour" desc="Colours primary buttons, selection, highlights and charts.">
            <div className="flex flex-wrap gap-2">
              {ACCENTS.map((a) => (
                <button key={a.id} onClick={() => setAccent(a.id)} className={cn("flex h-control-lg items-center gap-2 rounded-md border px-3 text-label", accent === a.id ? "border-textMuted/50 bg-panelBg" : "border-borderDark text-textSecondary hover:bg-panelBg")}>
                  <span className="size-3 rounded-full" style={{ background: a.swatch }} />{a.label}
                </button>
              ))}
            </div>
          </Section>
          <Section title="AI agents" desc="Agents answer from your records. Atlas is the default and stays on.">
            <ul className="flex flex-col gap-2">{AGENTS.map((a, i) => (
              <li key={a.id} className="flex items-center gap-3 rounded-lg border border-borderDark p-3"><AgentFlower agent={a.id} size={24} /><div className="flex-1"><div className="text-label font-medium">{a.name}{i === 0 && <span className="ml-2 text-caption text-textMuted">Default</span>}</div><div className="text-caption text-textMuted">{a.note}</div></div></li>
            ))}</ul>
          </Section>
          <Section title="People" desc="Everyone in this workspace.">
            <ul className="flex flex-col">{TEAM.map((m) => <li key={m.id} className="flex items-center gap-3 border-b border-borderDark py-2.5 last:border-0"><Avatar name={m.name} hue={m.hue} size={24} /><span className="flex-1 text-label">{m.name}</span><span className="text-caption text-textMuted">{m.role}</span></li>)}</ul>
          </Section>
        </div>
      </div>
    </Page>
  );
}
