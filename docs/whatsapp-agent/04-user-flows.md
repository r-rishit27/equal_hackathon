# WhatsApp Agent: user flows

**Status:** Proposed · Screens referenced: Agent Hub ([AgentHubPage.tsx](../../frontend/src/pages/AgentHubPage.tsx)), Bills → Drafts ([BillsPage.tsx](../../frontend/src/pages/BillsPage.tsx)), ReviewPage, Vendor → Contacts, Vendor Conversations.

## 0. Journey overview

```mermaid
journey
    title Vendor invoice on WhatsApp → approved bill
    section Setup (admin, once)
      Connect Twilio sandbox: 3: Admin
      Send test message: 4: Admin
      Watch vendor contacts: 4: Admin, AP analyst
    section Intake (automatic)
      Vendor sends PDF: 5: Vendor
      Agent classifies and drafts: 5: Agent
    section Review (AP)
      Open draft with WhatsApp badge: 5: AP analyst
      Fix fields, submit: 4: AP analyst
    section Approve
      Approve via existing workflow: 5: AP approver
    section Follow-up (R2)
      Reply to vendor in Conversations: 4: AP analyst
```

## 1. Admin: connect WhatsApp

```mermaid
flowchart TD
    A([Admin opens Agent Hub]) --> B{whatsapp_agent<br/>licensed?}
    B -- No --> B1[Show locked card<br/>'Ask your admin to enable WhatsApp Agent'] --> Z([End])
    B -- Yes --> C[Select WhatsApp tab]
    C --> D[Select brand scope]
    D --> E{Connection exists<br/>for brand?}
    E -- Yes --> S[Show status card]
    E -- No --> F[Enter Account SID, Auth token, Sender number]
    F --> G{Valid format?<br/>AC…, E.164}
    G -- No --> F
    G -- Yes --> H[Save → state AWAITING_TEST]
    H --> I[Show webhook URL + status URL<br/>+ Sandbox join code steps]
    I --> J[Admin pastes URLs into Twilio Console]
    J --> K[Test contact sends the join code, then 'test']
    K --> L{Signed test<br/>received within 10 min?}
    L -- Yes --> M[State ACTIVE ✅<br/>show last inbound time]
    L -- No --> N[Show troubleshooting:<br/>URL mismatch · wrong token · not joined]
    N --> J
    M --> S
```

## 2. Admin / AP: watch a vendor contact

```mermaid
flowchart TD
    A([Open Vendor → Contacts]) --> B[Pick contact]
    B --> C[Toggle 'Watch on WhatsApp']
    C --> D{Phone present?}
    D -- No --> D1[Prompt for WhatsApp number] --> E
    D -- Yes --> E{Valid E.164?}
    E -- No --> E1[Inline error: '+91XXXXXXXXXX format'] --> D1
    E -- Yes --> F{Number watched by another<br/>vendor in this brand?}
    F -- Yes --> F1[409: show conflicting vendor<br/>Offer: move watch / cancel] --> G{Move?}
    G -- Yes --> H[Disable old watch, enable new] --> I
    G -- No --> Z([End])
    F -- No --> I[Watch enabled ✅<br/>Email watch unaffected]
    I --> J[Contact appears in Agent Hub watch list]
```

## 3. Vendor: send an invoice

```mermaid
flowchart TD
    A([Vendor opens WhatsApp chat<br/>with tenant number]) --> B{Joined sandbox?<br/>pilot only}
    B -- No --> B1[Twilio rejects / no delivery<br/>Vendor told to send join code]
    B -- Yes --> C[Attach PDF, optional caption]
    C --> D[Send]
    D --> E[Twilio delivers webhook]
    E --> F{System triage}
    F -- Watched + PDF --> G[Queued → processed → Draft]
    F -- Watched, text only --> H[Logged TEXT_ONLY<br/>visible to AP]
    F -- Unwatched --> I[Logged UNWATCHED<br/>no media download]
    F -- Inbound paused --> J[Logged PAUSED<br/>kept for resume]
    G --> K{R2: auto-ack enabled?}
    K -- Yes --> L[Vendor gets 'Received invoice INV-123, thanks']
    K -- No --> M([No reply])
```

## 4. AP analyst: review and submit a WhatsApp draft

```mermaid
flowchart TD
    A([Open Bills → Drafts]) --> B[Filter: channel = WhatsApp]
    B --> C[Open draft with 🟢 WhatsApp badge]
    C --> D[ReviewPage: PDF left, fields right<br/>Source: vendor · +91 98•••••210 · time]
    D --> E{Analysis}
    E -- New --> F[Check fields]
    E -- Correction --> G[Banner: 'Revised version of INV-123'<br/>shows diff: amount 10,000 → 11,800]
    G --> G1{Prior is posted bill?}
    G1 -- Yes --> G2[Follow existing credit/debit note<br/>or cancel-and-replace process]
    G1 -- No --> G3[Discard older draft or this one]
    E -- Low confidence / unreadable --> H[Banner: reason + 'Open original']
    F --> I{Fields correct?}
    H --> I
    I -- No --> J[Edit fields] --> I
    I -- Yes --> K{Action}
    K -- Submit --> L[Existing validation + permission check]
    L --> M{Valid?}
    M -- No --> J
    M -- Yes --> N[Bill created once<br/>draft → submitted] --> O([Approval workflow])
    K -- Discard --> P[Pick reason: duplicate / not a bill / wrong vendor / other] --> Q([Draft discarded, audit kept])
```

## 5. AP approver: approve with provenance

```mermaid
flowchart LR
    A([Approval queue]) --> B[Open bill]
    B --> C[Source panel:<br/>WhatsApp · vendor contact · received at · original PDF]
    C --> D{Approve?}
    D -- Yes --> E([Approved → payment flow])
    D -- No --> F([Rejected with comment → back to AP])
```

## 6. AP analyst: follow up with a vendor (R2)

```mermaid
flowchart TD
    A([Vendor → Conversations → WhatsApp]) --> B[Timeline: messages, PDFs, linked bills]
    B --> C[Optional: 'Summarize thread' → labelled suggestion]
    C --> D[Type reply or pick template]
    D --> E{SendPolicy}
    E -- Opted out --> E1[Blocked: 'Vendor opted out']
    E -- Window closed & no template --> E2[Blocked: 'Outside 24h window — pick an approved template']
    E -- Sandbox / trial limit --> E3[Blocked: 'Not allowed on trial sender']
    E -- Outbound paused --> E4[Blocked: 'Outbound paused by admin']
    E -- OK --> F[Queued → Sent]
    F --> G{Status callback}
    G -- delivered/read --> H[✓✓ shown]
    G -- failed --> I[Error code + reason shown]
    G -- none + timeout --> J[Unknown — reconciling]
```

## 7. Operator: recover from failures

```mermaid
flowchart TD
    A([Alert: backlog / dead jobs]) --> B[Agent Hub → WhatsApp → Health]
    B --> C{Failure type}
    C -- Transient OCR / fetch --> D[Retry job] --> E[Job → PENDING<br/>same idempotency key<br/>no duplicate draft]
    C -- Signature failures spike --> F[Check PUBLIC_BASE_URL / token rotation] --> G[State NEEDS_ATTENTION until fixed]
    C -- Quarantined contact --> H[Resolve watch conflict] --> I[Release quarantined jobs]
    C -- Incident --> J[Pause inbound and/or outbound]
    J --> K[Fix]
    K --> L[Resume: view backlog size + oldest age]
    L --> M{Backlog action}
    M -- Drain --> N[Process in order]
    M -- Discard --> O[Mark discarded with reason]
```

## 8. Brand switching (UI rule)

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Agent Hub
    participant API as API
    U->>FE: Switch brand A → B
    FE->>FE: Clear cached cards, counts, events, drafts
    FE->>API: GET status/events/drafts?brand_id=B
    API->>API: Verify caller has access to B
    API-->>FE: Scoped data for B only
    Note over FE: Responses that arrive late for brand A are ignored (request token check)
```
