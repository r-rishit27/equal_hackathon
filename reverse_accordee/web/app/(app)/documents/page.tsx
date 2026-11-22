"use client";
import { useState } from "react";
import { Building2, CalendarDays, FileText, HardDrive, Upload, User } from "lucide-react";
import { Chip, DataTable, Page, PrimaryButton, Text, Toolbar, WithAvatar, type Column } from "@/components/ui";
import { customerById, documents, fmtRelative } from "@/lib/data";

type Doc = (typeof documents)[number];
const columns: Column<Doc>[] = [
  { key: "n", label: "Document", width: 280, icon: FileText, render: (d) => <Text>{d.name}</Text>, sort: (d) => d.name },
  { key: "c", label: "Company", width: 220, icon: Building2, render: (d) => { const c = customerById(d.customerId); return <WithAvatar name={c.name} hue={c.hue} square />; } },
  { key: "t", label: "Type", width: 110, render: (d) => <Chip tone={d.type === "PDF" ? "red" : d.type === "XLSX" || d.type === "CSV" ? "green" : d.type === "PPTX" ? "amber" : "blue"}>{d.type}</Chip> },
  { key: "d", label: "Description", width: 360, render: (d) => <Text muted>{d.desc}</Text> },
  { key: "b", label: "Uploaded by", width: 190, icon: User, render: (d) => <WithAvatar name={d.by} /> },
  { key: "u", label: "Uploaded", width: 170, icon: CalendarDays, render: (d) => <Text muted>{fmtRelative(d.at)}</Text>, sort: (d) => d.at },
  { key: "s", label: "Size", width: 110, icon: HardDrive, render: (d) => <Text muted>{d.size}</Text> },
];
export default function DocumentsPage() {
  const [tab, setTab] = useState("all");
  const types = ["PDF", "DOCX", "XLSX", "PPTX"];
  const rows = tab === "all" ? documents : documents.filter((d) => d.type === tab);
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "all", label: "All documents", count: documents.length }, ...types.map((t) => ({ id: t, label: t, count: documents.filter((d) => d.type === t).length }))]}>
        <PrimaryButton icon={Upload}>Upload</PrimaryButton>
      </Toolbar>
      <DataTable rows={rows} columns={columns} label="Documents" selectable={false} />
    </Page>
  );
}
