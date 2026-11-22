// Rule-based agent: regex intents over the seed data. Swap `answer()` for an LLM call
// with tool-calling later; keep the Reply shape so the UI doesn't change.
import {
  NOW, contracts, customers, customerById, daysBetween, emails, fmtDate, fmtMoney, invoices, isLive, leads, metrics, tasks,
} from "./data";

export type Reply = { text: string; toolsUsed: number; links?: { label: string; href: string }[] };

const findCustomer = (q: string) => {
  const s = q.toLowerCase();
  return [...customers].sort((a, b) => b.name.length - a.name.length).find((c) => s.includes(c.name.toLowerCase()) || s.includes(c.name.split(" ")[0].toLowerCase() + " "));
};

export function answer(q: string): Reply {
  const s = q.toLowerCase();
  const c = findCustomer(q);
  const ct = q.match(/CT-\d+/i)?.[0].toUpperCase();
  const inv = q.match(/INV-\d+/i)?.[0].toUpperCase();

  if (inv) {
    const i = invoices.find((x) => x.id === inv);
    if (!i) return { text: `I couldn't find ${inv}.`, toolsUsed: 1 };
    const cust = customerById(i.customerId);
    const late = daysBetween(i.due, NOW);
    return {
      text: `## ${i.id} · ${cust.name}\n${fmtMoney(i.amount)}, issued ${fmtDate(i.issued)}, due ${fmtDate(i.due)}.\n\n**Status:** ${i.status}${i.status === "Overdue" ? ` — ${late} days late` : ""}${i.paid ? `, paid ${fmtDate(i.paid)} by ${i.method}` : ""}.`,
      toolsUsed: 1, links: [{ label: "Open invoices", href: "/invoices" }],
    };
  }

  if (ct) {
    const k = contracts.find((x) => x.id === ct);
    if (!k) return { text: `I couldn't find ${ct}.`, toolsUsed: 1 };
    return {
      text: `## ${k.id} · ${customerById(k.customerId).name}\n${k.plan} plan, ${k.seats} seats — ${fmtMoney(k.annualValue)} a year, billed ${k.billing.toLowerCase()}.\n\n**Renews** ${fmtDate(k.renewal)} (in ${daysBetween(NOW, k.renewal)} days). Status: ${k.status}.`,
      toolsUsed: 1, links: [{ label: "Open contracts", href: "/contracts" }],
    };
  }

  if (/^\s*(please\s+)?(add|create|make)\s+(a\s+)?(task|to-?do|follow[- ]?up)\b|^\s*remind me to\b/i.test(q)) {
    const title = (q.includes(":") ? q.slice(q.indexOf(":") + 1) : q.replace(/^.*?\bto\b/i, "")).trim().replace(/[.!]+$/, "");
    if (!c) return { text: `I can add that, but which company is it for? Try "Add a task for <company>: ${title || "follow up"}".`, toolsUsed: 0 };
    return { text: `Done – I added "${title[0]?.toUpperCase()}${title.slice(1)}" for ${c.name}, due tomorrow. It's on the Tasks page.`, toolsUsed: 1, links: [{ label: "Open tasks", href: "/tasks" }] };
  }

  if (/overdue|owe|unpaid|late/.test(s)) {
    const od = invoices.filter((i) => i.status === "Overdue" && (!c || i.customerId === c.id)).sort((a, b) => b.amount - a.amount);
    if (!od.length) return { text: `Nothing overdue${c ? ` for ${c.name}` : ""}. 🎉`, toolsUsed: 1 };
    return {
      text: `## Overdue invoices${c ? ` · ${c.name}` : ""}\n${od.length} invoices, ${fmtMoney(od.reduce((x, i) => x + i.amount, 0))} in total.\n\n${od.slice(0, 6).map((i) => `- **${i.id}** · ${customerById(i.customerId).name} — ${fmtMoney(i.amount)}, ${daysBetween(i.due, NOW)} days late`).join("\n")}\n\nWant me to draft reminder emails for these?`,
      toolsUsed: 2, links: [{ label: "Open balances", href: "/balances" }],
    };
  }

  if (/renew|expir/.test(s)) {
    const r = contracts.filter((k) => isLive(k) && daysBetween(NOW, k.renewal) <= 90).sort((a, b) => (a.renewal < b.renewal ? -1 : 1));
    return {
      text: `## Renewals in the next 90 days\n${r.length} contracts worth ${fmtMoney(r.reduce((x, k) => x + k.annualValue, 0))} a year.\n\n${r.slice(0, 6).map((k) => `- **${customerById(k.customerId).name}** · ${k.id} — ${fmtMoney(k.annualValue)}, renews ${fmtDate(k.renewal)}`).join("\n")}`,
      toolsUsed: 2, links: [{ label: "Open contracts", href: "/contracts" }],
    };
  }

  if (/pipeline|lead|deal|forecast/.test(s)) {
    const top = [...metrics.openLeads].sort((a, b) => b.value * b.probability - a.value * a.probability).slice(0, 5);
    return {
      text: `## Pipeline\n${metrics.openLeads.length} open leads — ${fmtMoney(metrics.pipeline)} total, ${fmtMoney(metrics.weighted)} weighted. Win rate ${metrics.winRate}%.\n\n**Most likely to close**\n${top.map((l) => `- **${l.company}** · ${l.stage} — ${fmtMoney(l.value)} at ${l.probability}%`).join("\n")}`,
      toolsUsed: 2, links: [{ label: "Open leads", href: "/leads" }],
    };
  }

  if (/draft|write|email|reply/.test(s)) {
    const e = c ? emails.find((x) => x.customerId === c.id) : emails[0];
    const to = c?.contact ?? e?.from ?? "there";
    return {
      text: `Here's a draft${c ? ` for ${c.name}` : ""}:\n\n> Hi ${to.split(" ")[0]},\n>\n> I wanted to follow up on ${e ? `“${e.subject}”` : "our last conversation"} and make sure you have everything you need from us. Would a short call this week help?\n>\n> Best,\n> Jane\n\nNothing is sent until you press Send.`,
      toolsUsed: 2, links: [{ label: "Open emails", href: "/emails" }],
    };
  }

  if (c) {
    const ks = contracts.filter((k) => k.customerId === c.id);
    const od = invoices.filter((i) => i.customerId === c.id && i.status === "Overdue");
    const open = tasks.filter((t) => t.customerId === c.id && !t.done);
    return {
      text: `## ${c.name}\n${c.industry} · ${c.city}, ${c.country} · ${c.employees} employees. Owner: ${c.owner}. Health: **${c.health}**.\n\n- **Contracts:** ${ks.map((k) => `${k.id} (${k.plan}, ${fmtMoney(k.annualValue)}/yr, ${k.status.toLowerCase()})`).join(", ") || "none"}\n- **Overdue:** ${od.length ? fmtMoney(od.reduce((x, i) => x + i.amount, 0)) : "nothing"}\n- **Open tasks:** ${open.length}\n\n**Suggested next step:** ${od.length ? "chase the overdue balance before the next check-in." : "book a check-in to confirm next quarter's priorities."}`,
      toolsUsed: 3, links: [{ label: "Open customers", href: "/customers" }],
    };
  }

  if (/revenue|arr|mrr|how are we|summary|overview/.test(s)) {
    return {
      text: `## Business at a glance\n- **ARR:** ${fmtMoney(metrics.arr)} across ${metrics.liveCount} live contracts\n- **Owed to you:** ${fmtMoney(metrics.owed)} (${fmtMoney(metrics.overdueAmt)} overdue)\n- **Collected this month:** ${fmtMoney(metrics.collectedMonth)}\n- **Pipeline:** ${fmtMoney(metrics.pipeline)} open, ${fmtMoney(metrics.weighted)} weighted`,
      toolsUsed: 3, links: [{ label: "Open dashboard", href: "/home" }],
    };
  }

  return {
    text: `I answer from your records. Try:\n- "Which invoices are overdue?"\n- "What renews in the next 90 days?"\n- "Summarise ${customers[0].name}"\n- "Add a task for ${customers[1].name}: send the QBR deck"\n- "How is the pipeline looking?"\n\n${leads.length} leads, ${customers.length} customers and ${invoices.length} invoices are loaded.`,
    toolsUsed: 0,
  };
}

export const SUGGESTIONS = [
  "Which invoices are overdue?",
  "What renews in the next 90 days?",
  `Summarise ${customers[0].name}`,
  "How is the pipeline looking?",
];
