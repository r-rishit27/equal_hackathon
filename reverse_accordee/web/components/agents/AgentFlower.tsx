export const AGENTS = [
  { id: "atlas", name: "Atlas", note: "CRM assistant", petals: ["#F43F5E", "#F97316", "#FACC15", "#22C55E", "#06B6D4", "#3B82F6", "#8B5CF6", "#EC4899"] },
  { id: "iris", name: "Iris", note: "Research & market intel", petals: ["#F472B6", "#E879F9", "#FB7185", "#F9A8D4", "#EC4899", "#F0ABFC", "#FDA4AF", "#DB2777"] },
  { id: "quill", name: "Quill", note: "Data & reporting", petals: ["#5EEAD4", "#A5F3FC", "#86EFAC", "#99F6E4", "#67E8F9", "#BBF7D0", "#5EEAD4", "#A5F3FC"] },
  { id: "ledger", name: "Ledger", note: "Finance & billing", petals: ["#38BDF8", "#2DD4BF", "#60A5FA", "#5EEAD4", "#0EA5E9", "#22D3EE", "#3B82F6", "#34D399"] },
  { id: "sage", name: "Sage", note: "Customer success", petals: ["#A78BFA", "#C084FC", "#818CF8", "#DDD6FE", "#8B5CF6", "#E9D5FF", "#A5B4FC", "#7C3AED"] },
] as const;
export type AgentId = (typeof AGENTS)[number]["id"];

export function AgentFlower({ agent = "atlas", size = 16, spinning = false }: { agent?: AgentId; size?: number; spinning?: boolean }) {
  const a = AGENTS.find((x) => x.id === agent) ?? AGENTS[0];
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={spinning ? "animate-[spin-slow_1.6s_linear_infinite]" : undefined}>
      {a.petals.map((c, i) => (
        <ellipse key={i} cx="16" cy="8" rx="4.6" ry="7.6" fill={c} opacity="0.85" transform={`rotate(${i * 45} 16 16)`} />
      ))}
      <circle cx="16" cy="16" r="3" fill="var(--ac-app-bg)" />
    </svg>
  );
}
