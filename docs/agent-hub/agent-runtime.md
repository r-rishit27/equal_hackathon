# Agent runtime

The application and standalone processes share the Python implementation. The standalone package supplies lifecycle and ownership, while the application keeps its existing permissions, service licensing, approval and payment controls.

| Entry point | Existing work |
|---|---|
| `communication` | Watched mailbox intake, bill drafts and contract attachment capture |
| `compliance` | Review Hub adapters and review agent |
| `verification` | Vendor identity review findings |
| `recon` | Reconciliation document and case queue |
| `analytics` | Read-only approval lifecycle report |
| `payable` | Approval routing and status reconciliation for existing disbursements |
| `contract` | Communication evidence and contract term extraction |
| `tds` | Withholding calculations on eligible staged bills |
| `gst` | GST registration verification worker |
| `receivable` | Cash application queue |

The CFO Orchestrator runs on demand in the API and evaluates five stages for a selected invoice. Agent Hub also provides a shorter advisory invoice check. [CFO control sequence](../architecture/ARCHITECTURE.md#cfo-invoice-controls) The console's **Live** badge describes the module's release status. Communications also shows the mailbox's current pause setting.

## Deploy one worker separately

Run from the repository root with the existing application environment, schema and PostgreSQL notification triggers. The process supervisor should restart a worker on failure. Before moving a worker, configure the same comma-separated `ONSUMM_EXTERNAL_AGENTS` on the API, pipeline and standalone process, then restart the API and pipeline to hand off ownership. For Verification, include the setting on a standalone Compliance process too so that only Verification runs the vendor identity adapter.

```powershell
$env:ONSUMM_EXTERNAL_AGENTS = "recon,tds"
python -m backend_ocr.app.agents recon
# Run the next line in a second process with the same environment.
python -m backend_ocr.app.agents tds
```

Worker replicas use PostgreSQL advisory locks. Use existing tenant allowlists where the underlying worker supports them. Start workers against the intended environment. They process real queues and may call their configured providers. Analytics is a separate command and delegates to the same read-only report the API uses.

```text
python -m backend_ocr.app.agents analytics --tenant TENANT_UUID --brand BRAND_UUID
```
