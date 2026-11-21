# 05 · User Flows

**Actors:**

| Actor | What they do |
|---|---|
| **Finance user** (`finance`, `admin`) | Uploads documents, resolves links, reviews lines, acknowledges |
| **Approver** (`approver`) | Sees the recon summary on the approval screen; can acknowledge with a note |
| **System** | ReconWorker, Review Hub |

## F1. Upload documents into Recon (happy path)

```mermaid
flowchart TD
    A([Vendor card → Documents]) --> B[Open Recon folder]
    B --> C[Drop 1..n files<br/>PDF / image / xlsx / csv]
    C --> D{Client check:<br/>type allowed, ≤25 MB}
    D -->|no| D1[Inline error per file<br/>others continue]
    D -->|yes| E[POST /recon/documents]
    E --> F{Same file already<br/>uploaded? sha256}
    F -->|yes| F1[Show 'Already uploaded on dd-mm'<br/>Open existing / Upload anyway]
    F -->|no| G[Row appears in Reading<br/>status PENDING]
    G --> H[Worker: reading → classifying → extracting → linking → matching<br/>progress bar per stage]
    H --> I{Outcome}
    I -->|READY| J[Row shows type chips + 'Linked to INV' ✓<br/>Case list refreshes]
    I -->|NEEDS_LINK| K[Row moves to Needs you<br/>→ F3]
    I -->|NEEDS_REVIEW| L[Needs you: 'N handwritten numbers to check'<br/>→ F5]
    I -->|FAILED| M[Error text + Retry<br/>→ E-IN in edge cases]
    J --> N([Open case → F4])
```

## F2. Bata store-level report (several vendors in one file)

```mermaid
flowchart TD
    A[Upload 'Report PM Rao Road 9621.pdf'<br/>under vendor Inner Space] --> B[Classifier: narrative p1-2,<br/>scanned sheets p3-10]
    B --> C[Segmenter splits by section title + vendor GSTIN]
    C --> D1[FAMILY-INTERIOR PO · Inner Space]
    C --> D2[FURNITURE PO · Inner Space]
    C --> D3[SIGNAGE PO · Inner Space]
    C --> D4[AC HS PO · Blue Star]
    C --> D5[AC LS PO · Universal Refrigeration]
    C --> D6[LIGHTS PO · VDM Enterprises]
    D1 & D2 & D3 --> E{Own vendor → link by<br/>line overlap with this vendor's POs}
    E -->|FURNITURE ↔ PPO00023557-1 96%| F[Attached to case IS-HO-26-27-109]
    E -->|FAMILY-INTERIOR: no matching PO uploaded yet| G[UNLINKED · 'Upload its PO or invoice'<br/>auto-links later when they arrive]
    D4 & D5 & D6 --> H[FOREIGN · shown under<br/>'Other vendors in this report'<br/>v1: Ignore · v2: route to that vendor]
```

## F3. Resolve an ambiguous link

```mermaid
flowchart TD
    A[Needs you: 'Which invoice?'] --> B[LinkPicker: top-3 with signals]
    B --> C{User choice}
    C -->|pick candidate| D[POST /segments/id/link]
    C -->|search other bill| E[Search by no./amount → pick] --> D
    C -->|None of these| F[Stays UNLINKED<br/>re-tried automatically when a new bill/PO arrives]
    C -->|Other vendor| G[POST /ignore reason=foreign]
    D --> H[Case created or extended → recompute]
    H --> I([Case view])
```

## F4. Review a case (main approver journey)

```mermaid
flowchart TD
    A([Open case]) --> B[Read header totals + Checks]
    B --> C{Any failed header check?}
    C -->|yes| C1[Read detail → act outside recon<br/>e.g. ask vendor for revised invoice]
    C -->|no| D[Lines → filter Flagged]
    C1 --> D
    D --> E{For each flagged line}
    E -->|wrong match| F[Change match → F6]
    E -->|handwritten number looks wrong| G[Correct reading → F5]
    E -->|true discrepancy, decided| H[Mark reviewed + note]
    E -->|info only| I[No action needed]
    F & G --> R[Recompute → table refreshes]
    R --> E
    H --> J{All BLOCKER lines reviewed<br/>and no unchecked cells?}
    I --> J
    J -->|no| E
    J -->|yes| K[Acknowledge + note]
    K --> L[Case ACKNOWLEDGED<br/>Review Hub finding auto-resolves<br/>Approval screen shows 'Recon acknowledged by X']
    L --> M([Export xlsx optional])
```

## F5. Check handwritten numbers

```mermaid
flowchart TD
    A[Cell with amber outline] --> B[CellCorrectDialog:<br/>crop at 300 dpi + Read A + Read B]
    B --> C{User}
    C -->|Read A right| D[Accept A]
    C -->|Read B right| E[Accept B]
    C -->|neither| F[Type value]
    C -->|blank / not counted| G[Set verdict: Not covered / Not done]
    D & E & F & G --> H[POST /evidence/row/correct<br/>original kept · event logged]
    H --> I[Recompute every case using this row]
    I --> J{More unchecked cells?}
    J -->|yes| A
    J -->|no| K([Back to lines])
```

## F6. Correct a line match (and teach the system)

```mermaid
flowchart TD
    A[Row detail → Change match] --> B[Dialog: searchable PO lines with rate/unit<br/>+ 'Not in this PO']
    B --> C[POST /cases/id/lines/match]
    C --> D[recon_match_overrides row<br/>vendor_item_aliases upsert]
    D --> E[Recompute case]
    E --> F[Badge 'You' on this line]
    D --> G[Next invoice from same vendor:<br/>alias hit → 'Learned' badge, no question]
```

## F7. Wrong document type

```mermaid
flowchart TD
    A[Segment chip says 'Other: Measurement sheet'<br/>but it is the audit report] --> B[Click chip → KindPicker]
    B --> C[PATCH /segments/id kind=PV_SECTION]
    C --> D[Re-extract this segment only<br/>pages cached, no OCR repeat]
    D --> E[Re-link → recompute]
```

## F8. Invoice arrives after the evidence (out-of-order uploads)

```mermaid
sequenceDiagram
    actor U as User
    participant R as Recon
    participant B as Bill ingest
    U->>R: upload PO + PV report (no bill yet)
    R->>R: PO stored; report section UNLINKED (store 1859, overlaps PO 96%)
    Note over R: case not created — no bill. Doc row: "Waiting for the invoice"
    B->>B: invoice IS-HO-26-27-120 ingested (email/upload)
    B-->>R: NOTIFY recon_docs (new bill for supplier)
    R->>R: relink sweep: bill.po_ref = PPO00024378 → create case, attach PO + section
    R->>R: recompute → READY
    R-->>U: case appears in list (and Review Hub if flagged)
```

**Implementation note.** The bill-ingest path (`domain/ingest.py`, after it inserts `stg_bills`)
runs `pg_notify('recon_docs', json{kind:'bill', supplier_id, bill_id})`. It does this only when
the tenant has the `recon` service and the supplier has recon segments in `UNLINKED` status.
ReconWorker handles `kind:'bill'` messages with `relink_supplier(supplier_id)`.

## F9. Approver on the bill approval screen

```mermaid
flowchart TD
    A[Approve bill screen] --> B[GET /bills/id/recon]
    B --> C{Case exists?}
    C -->|no| D[Nothing shown]
    C -->|yes, RECONCILED/ACK| E[Green: 'Recon ✓ · acknowledged by X']
    C -->|NEEDS_REVIEW| F[Amber/red: '2 blockers · ₹12,400 at risk' → Open recon]
    F --> G[Approver may still approve — L1 advisory<br/>approval note pre-filled 'Approved with open recon flags']
```

## F10. Re-run and versioning

```mermaid
flowchart TD
    A[Re-run clicked or engine_version bumped on deploy] --> B{reextract?}
    B -->|no| C[recompute from cached extractions]
    B -->|yes| D[re-extract segments, keep human corrections<br/>corrected rows are never overwritten]
    C & D --> E[new result; reviewed marks carried over by line key]
    E --> F{result hash changed after ACK?}
    F -->|yes| G[status back to NEEDS_REVIEW + event 'changed after acknowledgement']
    F -->|no| H[stays ACKNOWLEDGED]
```

## F11. Delete a document

```mermaid
flowchart TD
    A[Delete file in Recon] --> B[Confirm: 'Removes its PO/evidence from N cases']
    B --> C[soft delete vendor_documents]
    C --> D[detach its segments from cases<br/>PO rows kept if referenced by other cases? no — PO owned by segment → cases fall to AWAITING_PO]
    D --> E[recompute affected cases; events logged]
```
