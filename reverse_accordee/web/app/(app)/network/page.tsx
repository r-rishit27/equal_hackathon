"use client";
import { useState } from "react";
import { Briefcase, Building2, CalendarDays, Heart, Mail, Plus, User } from "lucide-react";
import { Chip, DataTable, Page, PrimaryButton, StatStrip, Text, Toolbar, WithAvatar, type Column, type Tone } from "@/components/ui";
import { customerById, fmtRelative, people, type Person } from "@/lib/data";

const TONE: Record<Person["strength"], Tone> = { Strong: "green", Good: "blue", Weak: "gray", "Going cold": "amber" };
const columns: Column<Person>[] = [
  { key: "n", label: "Person", width: 260, icon: User, render: (p) => <WithAvatar name={p.name} hue={p.hue} />, sort: (p) => p.name },
  { key: "t", label: "Title", width: 170, icon: Briefcase, render: (p) => <Text muted>{p.title}</Text> },
  { key: "c", label: "Company", width: 200, icon: Building2, render: (p) => { const c = customerById(p.customerId); return <WithAvatar name={c.name} hue={c.hue} square />; } },
  { key: "s", label: "Strength", width: 130, icon: Heart, render: (p) => <Chip tone={TONE[p.strength]}>{p.strength}</Chip>, sort: (p) => p.strength },
  { key: "l", label: "Last contact", width: 140, icon: CalendarDays, render: (p) => <Text muted>{fmtRelative(p.lastContact)}</Text>, sort: (p) => p.lastContact },
  { key: "o", label: "Owner", width: 180, icon: User, render: (p) => <WithAvatar name={p.owner} /> },
  { key: "e", label: "Email", width: 240, icon: Mail, render: (p) => <a href={`mailto:${p.email}`} className="truncate text-label text-blue-600 hover:underline dark:text-blue-400">{p.email}</a> },
];
export default function NetworkPage() {
  const [tab, setTab] = useState<"all" | Person["strength"]>("all");
  const rows = tab === "all" ? people : people.filter((p) => p.strength === tab);
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all" as const, label: "All", count: people.length }, ...(["Strong", "Going cold"] as const).map((s) => ({ id: s, label: s, count: people.filter((p) => p.strength === s).length }))]}>
        <PrimaryButton icon={Plus}>Add person</PrimaryButton>
      </Toolbar>
      <StatStrip stats={[
        { label: "People", value: String(people.length), sub: "Across 50 customers" },
        { label: "Strong relationships", value: String(people.filter((p) => p.strength === "Strong").length), sub: "Talk every week" },
        { label: "Going cold", value: String(people.filter((p) => p.strength === "Going cold").length), sub: "Quiet for 2+ weeks" },
        { label: "Meetings booked", value: "12", sub: "This week" },
      ]} />
      <DataTable rows={rows} columns={columns} label="People" />
    </Page>
  );
}
