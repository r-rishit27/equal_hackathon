# Accordee demo: reverse-engineering report

Target: https://demo.accordee.app/ (captured 2026-11-21)
Method: REA (Reverse Engineer Anything, github.com/morluto/rea) `analyze-javascript-application` run over all 76 shipped JS bundles (78 files, 3.5 MB), plus manual reading of the bundles and the prerendered HTML of all 29 routes.

REA evidence id: `ev_65b169b1ec07f041f867f38959254c7c42580ffed9d72925aa4dc240da909af0`. All 76 files parsed with 0 failures: 911 app-graph nodes, 51,211 semantic nodes, 29 routes. REA marks coverage as "partial", and a static pass can't prove what happens at runtime.

---

## 1. TL;DR

- **It's a front-end-only demo.** It uses Next.js (App Router, Turbopack build) on Vercel. Every route is prerendered, and REA found **no real network endpoints**. The only `fetch` is Next's own router. The 9 "endpoint candidates" REA reported are false positives (`["candidate","customer"]` and similar).
- **All data is seed data in the bundle.** It's held in about 20 React Context stores and saved to `localStorage` under ~60 keys that start with `accordion:` (the internal codename) or `accordee:`.
- **The "AI" (Rune and 5 other agents) is not an LLM.** It's a deterministic engine of regex intents and string templates that runs over the in-memory records. A `setTimeout` loop reveals the text two words every 34 ms so it looks like streaming. The model picker (Claude Opus/Sonnet, GPT-6, Gemini Ultra, Llama 5, Mistral Large) is cosmetic.
- **"Today" is frozen** at about **2026-10-26/27**, so overdue counts, renewals and "Today" labels are always the same.
- The demo is sold as a template: a "Get the code" promo banner, a "Themes" link, and the pricing page at accordee.app/pricing.

## 2. Tech stack

| Layer | Finding | Evidence |
|---|---|---|
| Framework | Next.js App Router, React Server Components, Turbopack | `globalThis.TURBOPACK` chunks, `x-nextjs-prerender: 1`, `/_next/static/immutable/` |
| Hosting | Vercel edge (bom1), static HIT | `server: Vercel`, `x-vercel-cache: HIT` |
| Styling | Tailwind CSS v4 plus shadcn-style semantic tokens | `--tw-*`, `--color-*` OKLCH palette, `--background/--primary/--ring` |
| Motion | `motion` (Framer Motion successor) and custom keyframes | 262 refs; `nw-rise`, `nw-spin`, `nw-word` |
| Command palette | `cmdk` | `s.f.Item value="ask-rune"` |
| Icons | Lucide, 253 distinct icons | `{name:"notebook-pen",size:24,node:[…]}` |
| Analytics | `@vercel/analytics` | `va.vercel-scripts.com` |
| Fonts | Geist, Inter, Hedvig Letters Serif (display), Literata, Caveat (sticky notes), JetBrains Mono, Geist Mono | CSS `font-family` |
| Charts | Hand-written SVG (no chart library found) | `--series-1..4`, `--age-1..5` |
| State | React Context per domain plus `localStorage` | see §4 |

## 3. Information architecture (29 routes)

**Shell:** a collapsible sidebar (order can be changed under Settings → Sidebar), a ⌘K palette, ⌘Y for Agents, a "Quick Chat" button on every page, resizable drawers (each width is saved), and a workspace switcher ("Locally inc.", user "Jane Moore, Admin").

| Group | Route | What it shows (seed numbers) |
|---|---|---|
| Agents | `/` | "Ask Rune" chat landing with suggested prompts and an agent switcher |
| | `/memory` | Past agent conversations grouped by agent (15) |
| Top | `/home` | Dashboard with tabs (Overview, Revenue, Renewals, Pipeline, Relationships) and editable cards: ARR $3,215,520, owed $186,250 |
| | `/inbox` | Notifications: renewals, overdue invoices, leads, tasks (34 unread) |
| | `/messages` | Chat-style customer messages (68) |
| Your Space | `/emails` | Mail client (Inbox, Starred, Sent, Drafts, Archive, plus "Suggested records" pulled from email) |
| | `/meetings` | Week/month calendar; Meet, Zoom and Teams; Rune notetaker |
| | `/tasks` | Open, due, upcoming and done tasks (41 open) |
| | `/notes` | Notes (27), including AI notes and meeting notes |
| | `/whiteboards` | Sticky-note boards made from templates (for example a QBR board) |
| Company | `/leads` | Pipeline (88): stage, probability, weighted value, win rate |
| | `/customers` | 50 companies; Table, List and Kanban views |
| | `/contracts` | 65 contracts (CT-1001…): Active, Expiring, Awaiting signature, Draft |
| | `/network` | 140 people with relationship strength, "going cold", known-by |
| | `/documents` | 23 files (PDF, Doc, Sheet, Slides) |
| | `/workflows` | 27 automations: trigger, schedule, steps |
| Finance | `/invoices` | 236 invoices (INV-00001…), plus an editor and a customize panel |
| | `/balances` | Receivables by age (current, 1–30, 31–60, 61–90, 90+) |
| | `/transactions` | 178 transactions (TX-00001…), shown as "Stripe synced" |
| Other | `/apps` | App library: 64 integrations, 7 shown as connected (Stripe MCP, Slack, Notion…) |
| Settings | `/settings/{profile,preferences,notifications,general,ai-agents,ai-usage,sidebar,email,plans,custom-fields}` | Admin console. More pages are listed in the nav but not routed (People, Billing, Security, Audit Log, Trash, Tags, Pipeline, Contract Stages, Integrations, Imports/Exports, API) |
| Auth | `/login`, `/register`, `/forgot` | Email plus 6-digit code, Google, "Try out the demo" |

## 4. State and data model

### Context providers (from hook usage counts)
`useCustomers` (68 uses), `useToast` (45), `useComms` (42: tasks and threads), `useContracts` (37), `useLeads` (36), `useAdmin` (36), `usePreferences` (34), `useShell` (29: palette, drawers, help), `useChat` (24), `useInvoices` (19), `useEmails` (18), `useNetwork` (14), `useWorkflows`, `useMeetings`, `useAgents`, `useFavorites`, `useDocuments`, `useTheme`, `useInbox`, `useWhiteboards`.

Pattern: `createContext` → a provider seeded from constants → the state is mirrored into `localStorage` with `setItem(key, JSON.stringify(state))` → `useX()` throws if it's used outside its provider.

### Persisted keys
Domain data: `accordion:customers, contracts, invoices, leads, network, transactions, balances, documents, notes, whiteboards, workflows, apps, dashboards, favorites, admin, preferences, overdue, agent-order, message-extras, palette:recent, views:${table}`.
UI state: about 30 `accordion:*-width` and `*-open` keys (one per resizable drawer or panel), plus `hide-promo-banner` and `hide-get-code-popup`.
Auth and boot: `accordee:auth-email, demo-accounts, new-workspace, ready, theme`.

### Entity shapes (as seen in the UI and code)
- **Customer**: name, location, founder, employees band, website, tags[], founded, growthRate, lead owner, amount, startDate, online presence, email, lastInteraction
- **Contract** `CT-####`: plan name ("Scale plan subscription"), customerId, status (active, expiring, awaiting_signature, draft, ended), annualValue, start, renewal, billing, owner, seats
- **Invoice** `INV-#####`: customerId, contractId, status (draft, sent, overdue, paid, upcoming), amount, issueDate, dueDate, paidDate, method
- **Transaction** `TX-#####`: date, customer, invoice, type (payment or refund), method ("ACH via Stripe"), status (pending or …), amount
- **Lead**: company, type (new or upsell), stage, valueUsd = seats × plan price, probability, expectedClose, contact, nextStep{text,due}, source, owner, lastActivityAt, closedAt
- **Task**: title, record{type: customer|contract|invoice, id}, customerId, owner, dueDate, priority, done
- **Thread/Email**: subject, messages[{from{name,email},body,at}], customerId, unread, starred
- **Workflow**: name, status, trigger{event: renewal_window(60d) | invoice_overdue | contract_signed | lead_quiet(7d) | relationship_cold(14d) | lead_stage_changed{stage}}, schedule, steps[], owner, writing-style prompt
- **Agent**: {id, name, note, petals[8 colours], core}. The agents are Rune (CRM assistant, default, can't be switched off), Aether (research), Syntax (data and reporting), Theo (finance), Clara (customer success)
- **Meeting**: provider (gmeet, zoom, teams), time, customer, attendees, notetaker modes ("Assist live")

Derived metrics are computed on the client: ARR is the sum of live contracts, the overdue share, the ageing buckets, the win rate over 90 days, average days to close, and average days to pay. `r.Y` is the frozen "now" passed to all of them.

## 5. How the "AI" works

Code lives in `12hf3rrkte-57.js` (ChatProvider) and `272i108ey7u1f.js` (email intents).

```
sendAgentMessage(text)
  ├─ append user message
  ├─ reply = route(text)
  │    ├─ /^(please )?(add|create|make|set up) (a )?(task|to-do|follow-up)\b/i  or  /^remind me to\b/i
  │    │     → parse: company (longest name match), CT-\d+, INV-\d+, due ("today|tomorrow|next week|in N days")
  │    │     → createTask(...) for real, then reply "Done – I added "<title>" for <Co>, due <date>…"
  │    ├─ email intents: /draft|write|compose|reply|respond|send/ vs /summari[sz]e|recap|tl;dr|read/
  │    │     → find threads by person, company, domain or date → open the composer with a template body
  │    │       (keyword rules: terms|seat → contract reply, invoice|overdue → billing reply,
  │    │        renew|redline → renewal reply, demo|intro → demo-slot reply, sso|onboard → kickoff reply)
  │    ├─ app-scoped chat (Quick Chat inside an App): per-app answer and suggestion tables
  │    └─ fallback: canned answers with fake PDF attachments ("Q3 Account Churn Risk Assessment.pdf"…)
  └─ setTimeout(append reply, DELAY)            // fake "thinking"; toolsUsed: 1-2 shown as a badge
```

- **Streaming effect:** the text is split into blocks and words. One timer adds 2 words every 34 ms (1 for headings) and waits 1,100 ms for an image block. A violet-to-pink progress bar and a spinning "Rune is writing · <current h2>" header show while it runs.
- **"Draft with AI" in the composer** fills in a fixed template: `Hi ${first},\n\nI hope all is well with the team at ${company}. I wanted to follow up on ${subject}…`.
- **Notes and QBR drafts** are built from the customer's real contracts, invoices, threads and tasks ("1. <task> 2. … Confirm their priorities for next quarter").
- **The ⌘K palette** sends anything that isn't a record ID or name to Rune as a question ("Ask Rune: "…"").

To rebuild this with a real model, replace `route()` with an LLM call that uses tool-calling over the same stores (`createTask`, `searchThreads`, `draftEmail`, `getCustomer`…). The UI contract stays the same: `{role, text, toolsUsed, attachment, draft?, threadIds?}`.

## 6. Design system

```css
:root{
  --ac-app-bg:#fff; --ac-panel-bg:#f4f4f5; --ac-card-bg:#fff; --ac-sidebar-bg:#fafafa; --ac-sidebar-active:#f0f0f1;
  --ac-text-primary:#09090b; --ac-text-secondary:#52525b; --ac-text-muted:#71717a; --ac-border:#0000001a;
  --ac-brand:var(--ac-text-primary); --ac-highlight:#3b82f6; --radius:.625rem; --sidebar-menu-w:180px;
  --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a; --series-4:#eda100;
  --age-1:#86b6ef … --age-5:#104281;                       /* receivables ageing ramp */
  --sticky-yellow:#fdf0a6 … (12 sticky-note colours)
}
.dark{ --ac-app-bg:#0a0a0a; --ac-panel-bg:#171717; --ac-sidebar-bg:#0f0f10; --ac-text-primary:#fafafa; --ac-border:#ffffff1a; … }
html[data-accent=blue|violet|rose|orange|green|teal]{ --ac-brand:<swatch>; --ring/--ac-brand-soft via color-mix(in oklab) }
```

- The theme is set before React hydrates by an inline script: it reads `localStorage.theme`, or `?theme=` when the page is in an iframe, and applies `.dark` and `data-accent`.
- There are 7 accents: neutral `#18181b`, blue `#2563eb`, violet `#7c3aed`, rose `#e11d48`, orange `#ea580c`, green `#16a34a` and teal `#0d9488`. An accent recolours buttons, focus rings, selection and chart series.
- Design tokens: `h-control`, `h-control-lg`, `h-toolbar`, `text-label`, `text-caption`, `text-body`, `--motion-fast`, `--ease-smooth`.
- Each agent's avatar is an 8-petal "flower" in that agent's colours. Avatars elsewhere use mesh gradients (`mesh-g1…g6`).

## 7. Rebuild blueprint

1. `create-next-app` (App Router, TS) with Tailwind v4. Copy the token block from §6 into `globals.css`. Add `cmdk`, `motion` and `lucide-react`.
2. `lib/seed/*.ts`: about 50 customers, 65 contracts, 236 invoices, 178 transactions, 88 leads, 140 people, 27 workflows. Generate them from a fixed seed so the numbers add up, with `NOW = 2026-10-26`.
3. One provider per domain with a `usePersistentState(key, seed)` hook. Compose them in `app/(app)/layout.tsx` together with Shell, Toast and Chat.
4. Shared pieces: `DataTable` (saved views, filter, sort, edit view, export), `StatStrip` (4 KPI tiles), `Drawer` (resizable, width saved), `Composer`, `CommandPalette`, and the `AgentFlower` avatar.
5. Build the pages in this order: customers → contracts → invoices → home dashboard → tasks and inbox → emails → the rest.
6. Agents: start with the regex router for parity, then swap in an LLM with tool-calling. Server actions will need a real API at that point, because the demo has none.

## 8. Reproduce

```bash
# capture
curl -sSL https://demo.accordee.app/<route>      # for every route in §3; collect /_next/static/**/*.js|css
# analyze (REA needs Node >=22.23.4; on macOS with a broken CLT SwiftBridging modulemap, use a swiftc wrapper)
REA_DARWIN_SWIFTC_PATH=/abs/swiftc-wrap SDKROOT=$(xcrun --show-sdk-path) \
  npx -y rea-agents@latest analyze-javascript-application /abs/chunks --json > rea_out.json
```

The raw bundles and the 120 MB REA evidence file are kept outside this repo in the session scratchpad. They are the vendor's shipped code, so they're not committed here.
