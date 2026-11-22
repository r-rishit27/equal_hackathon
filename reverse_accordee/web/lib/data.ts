// Deterministic seed data. Same seed → same numbers on every load.
export const NOW = new Date("2026-10-26T09:00:00Z");
const DAY = 864e5;

function mulberry32(a: number) {
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(20261026);
const pick = <T,>(xs: readonly T[]) => xs[Math.floor(rand() * xs.length)];
const int = (lo: number, hi: number) => lo + Math.floor(rand() * (hi - lo + 1));
export const addDays = (d: Date, n: number) => new Date(d.getTime() + n * DAY);
export const iso = (d: Date) => d.toISOString().slice(0, 10);
export const daysBetween = (a: string | Date, b: string | Date) =>
  Math.round((new Date(b).getTime() - new Date(a).getTime()) / DAY);

// ---------- Team ----------
export type Member = { id: string; name: string; email: string; role: string; hue: number };
export const ME: Member = { id: "u1", name: "Jane Moore", email: "jane@northstar.dev", role: "Owner", hue: 262 };
export const TEAM: Member[] = [
  ME,
  { id: "u2", name: "Omar Haddad", email: "omar@northstar.dev", role: "Admin", hue: 20 },
  { id: "u3", name: "Priya Nair", email: "priya@northstar.dev", role: "Member", hue: 150 },
  { id: "u4", name: "Lucas Moreau", email: "lucas@northstar.dev", role: "Member", hue: 200 },
  { id: "u5", name: "Hana Sato", email: "hana@northstar.dev", role: "Member", hue: 330 },
];

// ---------- Customers ----------
const PREFIX = ["Blue", "Iron", "Cedar", "Nova", "Polar", "Amber", "Silver", "Orbit", "Granite", "Lumen", "Harbor", "Echo", "Atlas", "Willow", "Crimson", "Delta", "Kite", "Maple", "Quartz", "Riverstone", "Solace", "Tidal", "Vantage", "Zenith", "Copper"];
const SUFFIX = ["Labs", "Logistics", "Robotics", "Health", "Analytics", "Foods", "Systems", "Studio", "Energy", "Capital", "Software", "Networks", "Bio", "Freight", "Media"];
const CITIES: [string, string][] = [["Berlin", "Germany"], ["San Francisco", "United States"], ["Paris", "France"], ["Tokyo", "Japan"], ["New York", "United States"], ["Sydney", "Australia"], ["Toronto", "Canada"], ["Cape Town", "South Africa"], ["São Paulo", "Brazil"], ["Amsterdam", "Netherlands"], ["Bengaluru", "India"], ["Stockholm", "Sweden"], ["Singapore", "Singapore"], ["Madrid", "Spain"], ["London", "United Kingdom"]];
const FIRST = ["Ava", "Noah", "Mia", "Leo", "Zara", "Ethan", "Isla", "Kai", "Nina", "Ravi", "Elena", "Tom", "Yuki", "Sofia", "Diego", "Amara", "Felix", "Lena", "Arjun", "Chloe", "Mateo", "Ines", "Oscar", "Maya"];
const LAST = ["Brooks", "Kim", "Okafor", "Silva", "Novak", "Patel", "Larsen", "Chen", "Garcia", "Moretti", "Schmidt", "Nakamura", "Reyes", "Dubois", "Haas", "Singh", "Walsh", "Ito", "Costa", "Berg"];
const INDUSTRY = ["Fintech", "Healthcare", "Logistics", "Retail", "Education", "Manufacturing", "Media", "Energy", "SaaS"];
const SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"];
const STAGE = ["Pre-seed", "Seed", "Series A", "Series B", "Growth", "Public"];

export type Customer = {
  id: string; name: string; domain: string; city: string; country: string; founder: string;
  employees: string; industry: string; tags: string[]; founded: string; stage: string;
  owner: string; contact: string; email: string; lastInteraction: string; hue: number; health: Health;
};
export type Health = "Excellent" | "Good" | "Normal" | "At risk";
const personName = () => `${pick(FIRST)} ${pick(LAST)}`;

const usedNames = new Set<string>();
export const customers: Customer[] = Array.from({ length: 50 }, (_, i) => {
  let name = "";
  do name = `${pick(PREFIX)} ${pick(SUFFIX)}`; while (usedNames.has(name));
  usedNames.add(name);
  const [city, country] = pick(CITIES);
  const domain = name.toLowerCase().replace(/[^a-z]/g, "") + ".com";
  const contact = personName();
  return {
    id: `c${i + 1}`, name, domain, city, country, founder: personName(),
    employees: pick(SIZES), industry: pick(INDUSTRY),
    tags: [pick(["B2B", "B2C"]), pick(INDUSTRY)], founded: `${pick(["Jan", "Mar", "May", "Jul", "Sep", "Nov"])} ${int(2008, 2023)}`,
    stage: pick(STAGE), owner: pick(TEAM).name, contact,
    email: `${contact.split(" ")[0].toLowerCase()}@${domain}`,
    lastInteraction: addDays(NOW, -int(0, 30)).toISOString(), hue: int(0, 359),
    health: pick(["Excellent", "Good", "Normal", "Normal", "At risk"] as const),
  };
});
export const customerById = (id: string) => customers.find((c) => c.id === id)!;

// ---------- Contracts ----------
export const PLANS = { Starter: 39, Growth: 78, Scale: 132 } as const;
export type Plan = keyof typeof PLANS;
export type ContractStatus = "Active" | "Expiring" | "Awaiting signature" | "Draft";
export type Contract = {
  id: string; customerId: string; plan: Plan; seats: number; annualValue: number;
  start: string; renewal: string; status: ContractStatus; billing: "Monthly" | "Annual"; owner: string;
};
export const contracts: Contract[] = Array.from({ length: 65 }, (_, i) => {
  const customerId = customers[i % customers.length].id;
  const plan = pick(Object.keys(PLANS) as Plan[]);
  const seats = pick([5, 10, 15, 20, 25, 30, 40, 50]);
  const start = addDays(NOW, -int(30, 600));
  let renewal = addDays(start, 365);
  while (renewal < NOW) renewal = addDays(renewal, 365);
  const daysToRenew = daysBetween(NOW, renewal);
  const r = rand();
  const status: ContractStatus = r < 0.05 ? "Draft" : r < 0.22 ? "Awaiting signature" : daysToRenew <= 60 ? "Expiring" : "Active";
  return {
    id: `CT-${1001 + i}`, customerId, plan, seats, annualValue: seats * PLANS[plan] * 12,
    start: iso(start), renewal: iso(renewal), status, billing: rand() < 0.6 ? "Monthly" : "Annual",
    owner: customerById(customerId).owner,
  };
});
export const isLive = (c: Contract) => c.status === "Active" || c.status === "Expiring";

// ---------- Invoices + transactions ----------
export type InvoiceStatus = "Paid" | "Sent" | "Overdue" | "Upcoming";
export type Invoice = {
  id: string; customerId: string; contractId: string; amount: number; issued: string; due: string;
  paid: string | null; status: InvoiceStatus; method: string | null;
};
export const invoices: Invoice[] = [];
let invN = 1;
for (const ct of contracts.filter(isLive)) {
  const monthly = ct.billing === "Monthly";
  const amount = monthly ? Math.round(ct.annualValue / 12) : ct.annualValue;
  const step = monthly ? 30 : 365;
  const horizon = addDays(NOW, -365);
  for (let d = new Date(ct.start); d < addDays(NOW, 45); d = addDays(d, step)) {
    if (d < horizon) continue; // only keep the last 12 months of billing
    const issued = d, due = addDays(d, 30);
    let status: InvoiceStatus, paid: string | null = null;
    if (issued > NOW) status = "Upcoming";
    else if (due > NOW) status = rand() < 0.4 ? "Paid" : "Sent";
    else if (daysBetween(due, NOW) > 120) status = "Paid"; // old debt gets settled
    else status = rand() < 0.88 ? "Paid" : "Overdue";
    if (status === "Paid") {
      const p = addDays(issued, int(3, 28));
      if (p > NOW) status = "Sent"; // payment can't land after "today"
      else paid = iso(p);
    }
    invoices.push({
      id: `INV-${String(invN++).padStart(5, "0")}`, customerId: ct.customerId, contractId: ct.id, amount,
      issued: iso(issued), due: iso(due), paid, status,
      method: paid ? paymentMethod() : null,
    });
  }
}
invoices.sort((a, b) => (a.issued < b.issued ? 1 : -1));

function paymentMethod() {
  const r = rand();
  if (r < 0.45) return "ACH via Stripe";
  if (r < 0.6) return "Bank transfer";
  if (r < 0.75) return `Visa •••• ${int(1000, 9999)}`;
  if (r < 0.9) return `Mastercard •••• ${int(1000, 9999)}`;
  return "Apple Pay";
}

export type Transaction = { id: string; date: string; customerId: string; invoiceId: string; type: "Payment" | "Refund"; method: string; status: "Succeeded" | "Pending"; amount: number };
const slowRail = (m: string) => m === "ACH via Stripe" || m === "Bank transfer";
const rawTx: Omit<Transaction, "id">[] = invoices.filter((i) => i.paid).map((inv) => ({
  date: inv.paid!, customerId: inv.customerId, invoiceId: inv.id, type: "Payment", method: inv.method!,
  // only bank rails take days to clear
  status: slowRail(inv.method!) && daysBetween(inv.paid!, NOW) <= 7 ? "Pending" : "Succeeded", amount: inv.amount,
}));
// a handful of refunds against older payments
for (const p of rawTx.filter((t) => daysBetween(t.date, NOW) > 30).filter((_, k) => k % 23 === 5).slice(0, 7)) {
  const d = addDays(new Date(p.date), int(2, 20));
  rawTx.push({ ...p, type: "Refund", status: "Succeeded", date: iso(d > NOW ? NOW : d), amount: -Math.round(p.amount * pick([0.25, 0.5, 1])) });
}
export const transactions: Transaction[] = rawTx
  .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  .map((t, i) => ({ ...t, id: `TX-${String(i + 1).padStart(5, "0")}` }))
  .reverse();

// ---------- Leads ----------
export const LEAD_STAGES = ["New", "Qualified", "Demo", "Proposal", "Negotiation", "Won", "Lost"] as const;
export type LeadStage = (typeof LEAD_STAGES)[number];
const STAGE_P: Record<LeadStage, number> = { New: 10, Qualified: 25, Demo: 40, Proposal: 60, Negotiation: 80, Won: 100, Lost: 0 };
export type Lead = { id: string; company: string; kind: "New" | "Upsell"; stage: LeadStage; value: number; probability: number; expectedClose: string; contact: string; nextStep: string; source: string; owner: string; lastActivity: string };
export const leads: Lead[] = Array.from({ length: 88 }, (_, i) => {
  const upsell = rand() < 0.35;
  const stage = pick(LEAD_STAGES);
  const plan = pick(Object.keys(PLANS) as Plan[]);
  return {
    id: `L-${200 + i}`, company: upsell ? pick(customers).name : `${pick(PREFIX)} ${pick(SUFFIX)}`,
    kind: upsell ? "Upsell" : "New", stage, value: pick([10, 20, 30, 50]) * PLANS[plan] * 12,
    probability: STAGE_P[stage], expectedClose: iso(addDays(NOW, int(-20, 90))), contact: personName(),
    nextStep: pick(["Book discovery call", "Send proposal", "Security review", "Pricing follow-up", "Intro to finance", "Demo for the team"]),
    source: pick(["Inbound", "Outbound", "Referral", "Event", "Partner"]), owner: pick(TEAM).name,
    lastActivity: addDays(NOW, -int(0, 25)).toISOString(),
  };
});

// ---------- People (network) ----------
export type Person = { id: string; name: string; title: string; customerId: string; strength: "Strong" | "Good" | "Weak" | "Going cold"; lastContact: string; email: string; owner: string; hue: number };
export const people: Person[] = Array.from({ length: 140 }, (_, i) => {
  const c = customers[i % customers.length];
  const name = i < 50 ? c.contact : personName();
  return {
    id: `p${i + 1}`, name, title: pick(["Founder & CEO", "CFO", "Head of Ops", "VP Sales", "CTO", "Procurement lead", "Product manager"]),
    customerId: c.id, strength: pick(["Strong", "Good", "Good", "Weak", "Going cold"] as const),
    lastContact: addDays(NOW, -int(0, 40)).toISOString(), email: `${name.split(" ")[0].toLowerCase()}@${c.domain}`,
    owner: c.owner, hue: int(0, 359),
  };
});

// ---------- Tasks ----------
export type Task = { id: string; title: string; record: string; customerId: string; owner: string; due: string; priority: "High" | "Medium" | "Low"; done: boolean };
export const tasks: Task[] = [
  ...invoices.filter((i) => i.status === "Overdue").map((inv, k) => ({
    id: `t${k + 1}`, title: `Chase payment for ${inv.id}`, record: `Invoice ${inv.id}`, customerId: inv.customerId,
    owner: customerById(inv.customerId).owner, due: iso(addDays(NOW, -int(0, 4))), priority: "High" as const, done: false,
  })),
  ...contracts.filter((c) => c.status === "Expiring").map((ct, k) => ({
    id: `tr${k + 1}`, title: `Prepare renewal for ${customerById(ct.customerId).name}`, record: `Contract ${ct.id}`,
    customerId: ct.customerId, owner: ct.owner, due: iso(addDays(new Date(ct.renewal), -21)), priority: "Medium" as const, done: false,
  })),
  ...Array.from({ length: 14 }, (_, k) => {
    const c = pick(customers);
    return {
      id: `tg${k + 1}`, title: pick(["Send QBR deck", "Share onboarding checklist", "Confirm SSO setup", "Follow up on feature request", "Schedule exec check-in"]) + ` · ${c.name}`,
      record: "Customer", customerId: c.id, owner: pick(TEAM).name, due: iso(addDays(NOW, int(-3, 20))),
      priority: pick(["High", "Medium", "Low"] as const), done: rand() < 0.25,
    };
  }),
];

// ---------- Workflows ----------
export type Workflow = { id: string; name: string; on: boolean; trigger: string; schedule: string; steps: number; lastRun: string | null; owner: string };
export const workflows: Workflow[] = [
  ["Renewal reminders", "Renewal within 60 days", "Daily 09:00"],
  ["Chase overdue invoices", "Invoice becomes overdue", "Daily 08:00"],
  ["Welcome new customers", "Contract is signed", "When it happens"],
  ["Weekly pipeline digest", "Every week", "Mon 08:00"],
  ["Revive quiet leads", "Lead quiet for 7 days", "Daily 10:00"],
  ["Warm up cold relationships", "No contact for 14 days", "Daily 11:00"],
  ["Post payments to Slack", "Payment received", "When it happens"],
  ["Summarise meetings", "Meeting ends", "When it happens"],
  ["Upgrade nudges", "Seat usage above 90%", "Weekly"],
  ["Enrich new companies", "Customer is created", "When it happens"],
].map(([name, trigger, schedule], i) => ({
  id: `w${i + 1}`, name, trigger, schedule, on: i % 4 !== 3, steps: int(2, 6),
  lastRun: i % 4 === 3 ? null : addDays(NOW, -int(0, 2)).toISOString(), owner: TEAM[i % TEAM.length].name,
}));

// ---------- Emails / inbox ----------
export type Email = { id: string; from: string; customerId: string; subject: string; preview: string; at: string; unread: boolean };
const SUBJECTS: [string, string][] = [
  ["Contract extension: two options for 2027", "We reviewed the terms and are happy with them. Let's agree on seats and a signing date on tomorrow's call."],
  ["Renewal before November 1", "Our plan ends soon and I haven't seen the renewal paperwork. Can you check the August invoice first?"],
  ["SSO setup before the kickoff", "Our IT team wants SSO live before onboarding. Could you share the SAML metadata?"],
  ["Question about the last invoice", "Finance flagged a different PO number on the invoice. Could you resend with the right reference?"],
  ["Intro: evaluating CRMs", "We're comparing a few tools this quarter and would love a 30-minute demo next week."],
  ["Feedback on the reports", "The team loves the summaries but wants to export reports to Sheets. Is that on the roadmap?"],
];
export const emails: Email[] = SUBJECTS.map(([subject, preview], i) => {
  const c = customers[i * 3];
  return { id: `e${i + 1}`, from: c.contact, customerId: c.id, subject, preview, at: addDays(NOW, -i * 0.4).toISOString(), unread: i < 4 };
});

export type InboxItem = { id: string; kind: "Money" | "Contracts" | "Leads" | "Tasks" | "Messages"; title: string; body: string; customerId: string; at: string; unread: boolean };
export const inbox: InboxItem[] = [
  ...contracts.filter((c) => c.status === "Expiring").map((c, i) => ({
    id: `n-c${i}`, kind: "Contracts" as const, title: `${c.id} renews in ${daysBetween(NOW, c.renewal)} days`,
    body: `${c.plan} plan with ${customerById(c.customerId).name} – ${fmtMoney(c.annualValue)} a year.`, customerId: c.customerId, at: NOW.toISOString(), unread: true,
  })),
  ...invoices.filter((i) => i.status === "Overdue").map((inv, i) => ({
    id: `n-i${i}`, kind: "Money" as const, title: `${inv.id} is ${daysBetween(inv.due, NOW)} days overdue`,
    body: `${customerById(inv.customerId).name} owes ${fmtMoney(inv.amount)} on this invoice.`, customerId: inv.customerId, at: addDays(NOW, -0.05).toISOString(), unread: true,
  })),
  ...emails.map((e) => ({ id: `n-${e.id}`, kind: "Messages" as const, title: `${e.from} replied`, body: e.subject, customerId: e.customerId, at: e.at, unread: e.unread })),
];

// ---------- Documents / notes / meetings ----------
export const documents = Array.from({ length: 18 }, (_, i) => {
  const c = customers[(i * 7) % customers.length];
  const [name, type, desc] = pick([
    ["Master services agreement", "PDF", "Signed MSA covering scope, liability caps and a 30-day termination notice."],
    ["Usage export", "CSV", "Daily active users and API calls for the last 90 days."],
    ["Meeting notes", "DOCX", "Quarterly check-in: priorities for next quarter and open questions."],
    ["Pricing proposal", "PDF", "Three-tier proposal with volume discount for 50+ seats."],
    ["QBR deck", "PPTX", "Results, adoption metrics and next-quarter goals."],
    ["Security questionnaire", "XLSX", "Completed vendor security review, SOC 2 references included."],
  ] as const);
  return { id: `d${i + 1}`, name, type, desc, customerId: c.id, by: pick(TEAM).name, at: addDays(NOW, -int(0, 60)).toISOString(), size: `${(rand() * 3 + 0.2).toFixed(1)} MB` };
});

export const notes = Array.from({ length: 14 }, (_, i) => {
  const c = customers[(i * 5) % customers.length];
  const kind = pick(["Onboarding kickoff", "Product demo", "Quarterly business review", "Renewal call"]);
  return {
    id: `nt${i + 1}`, title: `${kind} · notes`, customerId: c.id, by: pick([...TEAM.map((t) => t.name), "AI notetaker"]),
    body: `${c.name} confirmed their priorities for next quarter. Agreed to send a revised proposal and loop in finance before the renewal date.`,
    at: addDays(NOW, -int(0, 20)).toISOString(),
  };
});

export const meetings = Array.from({ length: 12 }, (_, i) => {
  const c = customers[(i * 4) % customers.length];
  const day = i % 5, hour = 9 + ((i * 3) % 8);
  return {
    id: `m${i + 1}`, title: pick(["Product demo", "Implementation sync", "Quarterly business review", "Onboarding kickoff", "Renewal call"]),
    customerId: c.id, day, start: hour, length: pick([0.5, 0.75, 1]), provider: pick(["Meet", "Zoom", "Teams"]),
  };
});

// ---------- Formatting + metrics ----------
export function fmtMoney(n: number, cents = false) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: cents ? 2 : 0, minimumFractionDigits: cents ? 2 : 0 });
}
export function fmtDate(s: string) {
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}
export function fmtRelative(s: string) {
  const d = daysBetween(s, NOW);
  if (d <= 0) return new Date(s).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "UTC" });
  if (d === 1) return "Yesterday";
  return fmtDate(s).replace(/, \d{4}$/, "");
}

export const metrics = (() => {
  const live = contracts.filter(isLive);
  const arr = live.reduce((s, c) => s + c.annualValue, 0);
  const open = invoices.filter((i) => i.status === "Sent" || i.status === "Overdue");
  const overdue = invoices.filter((i) => i.status === "Overdue");
  const owed = open.reduce((s, i) => s + i.amount, 0);
  const overdueAmt = overdue.reduce((s, i) => s + i.amount, 0);
  const monthStart = new Date(Date.UTC(NOW.getUTCFullYear(), NOW.getUTCMonth(), 1));
  const collectedMonth = invoices.filter((i) => i.paid && new Date(i.paid) >= monthStart && new Date(i.paid) <= NOW).reduce((s, i) => s + i.amount, 0);
  const renewing60 = live.filter((c) => daysBetween(NOW, c.renewal) <= 60);
  const openLeads = leads.filter((l) => l.stage !== "Won" && l.stage !== "Lost");
  const closed = leads.filter((l) => l.stage === "Won" || l.stage === "Lost");
  const won = leads.filter((l) => l.stage === "Won");
  const buckets = [0, 0, 0, 0, 0];
  for (const i of open) {
    const late = daysBetween(i.due, NOW);
    buckets[late <= 0 ? 0 : late <= 30 ? 1 : late <= 60 ? 2 : late <= 90 ? 3 : 4] += i.amount;
  }
  const monthly = Array.from({ length: 12 }, (_, k) => {
    const m = new Date(Date.UTC(NOW.getUTCFullYear(), NOW.getUTCMonth() - 11 + k, 1));
    const next = new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1));
    const inMonth = (s: string | null) => !!s && new Date(s) >= m && new Date(s) < next;
    return {
      label: m.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" }),
      invoiced: invoices.filter((i) => inMonth(i.issued)).reduce((s, i) => s + i.amount, 0),
      collected: invoices.filter((i) => inMonth(i.paid)).reduce((s, i) => s + i.amount, 0),
    };
  });
  return {
    arr, liveCount: live.length, owed, openCount: open.length, overdueAmt, overdueCount: overdue.length,
    collectedMonth, renewing60, openLeads, pipeline: openLeads.reduce((s, l) => s + l.value, 0),
    weighted: Math.round(openLeads.reduce((s, l) => s + (l.value * l.probability) / 100, 0)),
    winRate: closed.length ? Math.round((won.length / closed.length) * 100) : 0, buckets, monthly,
  };
})();
