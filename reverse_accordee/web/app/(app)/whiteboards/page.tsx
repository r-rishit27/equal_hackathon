"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { Page, PrimaryButton, Toolbar } from "@/components/ui";

const COLORS = ["#fdf0a6", "#fed7aa", "#fbcfe8", "#ddd6fe", "#bfdbfe", "#a7f3d0", "#d9f99d"];
type Sticky = { id: number; x: number; y: number; text: string; color: string };
const SEED: Sticky[] = [
  { id: 1, x: 40, y: 60, text: "Lead with their results, not our features", color: COLORS[0] },
  { id: 2, x: 260, y: 40, text: "Renewals tracked: 100%", color: COLORS[4] },
  { id: 3, x: 480, y: 90, text: "Love the AI summaries", color: COLORS[5] },
  { id: 4, x: 700, y: 50, text: "Want better reports", color: COLORS[2] },
  { id: 5, x: 120, y: 260, text: "Agree next quarter's goals before leaving", color: COLORS[3] },
  { id: 6, x: 420, y: 300, text: "Roll out to support team", color: COLORS[1] },
];

export default function WhiteboardsPage() {
  const [tab, setTab] = useState("qbr");
  const [notes, setNotes] = useState(SEED);
  const [drag, setDrag] = useState<{ id: number; dx: number; dy: number } | null>(null);
  return (
    <Page>
      <Toolbar value={tab} onChange={setTab} tabs={[{ id: "qbr", label: "Quarterly business review" }, { id: "templates", label: "Templates" }]}>
        <PrimaryButton icon={Plus} onClick={() => setNotes((n) => [...n, { id: Date.now(), x: 80 + Math.random() * 400, y: 80 + Math.random() * 200, text: "New note", color: COLORS[n.length % COLORS.length] }])}>Add sticky</PrimaryButton>
      </Toolbar>
      <div className="relative min-h-0 flex-1 overflow-auto bg-[radial-gradient(var(--ac-border)_1px,transparent_1px)] [background-size:20px_20px]"
        onPointerMove={(e) => { if (!drag) return; const r = e.currentTarget.getBoundingClientRect(); setNotes((ns) => ns.map((n) => (n.id === drag.id ? { ...n, x: e.clientX - r.left - drag.dx, y: e.clientY - r.top - drag.dy } : n))); }}
        onPointerUp={() => setDrag(null)}>
        {notes.map((n) => (
          <div key={n.id} onPointerDown={(e) => { const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setDrag({ id: n.id, dx: e.clientX - r.left, dy: e.clientY - r.top }); }}
            className="absolute flex size-40 cursor-grab touch-none p-3 text-[17px] leading-snug text-[#1c1c1e] shadow-md active:cursor-grabbing"
            style={{ left: n.x, top: n.y, background: n.color, fontFamily: "'Comic Sans MS', 'Bradley Hand', cursive", transform: `rotate(${(n.id % 5) - 2}deg)` }}>
            <span contentEditable suppressContentEditableWarning className="outline-none" onPointerDown={(e) => e.stopPropagation()}>{n.text}</span>
          </div>
        ))}
      </div>
    </Page>
  );
}
