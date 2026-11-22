# Reckon.ai hackathon local runbook

Run the commands below in Windows PowerShell from the repository root. The complete demo uses four processes sharing one hackathon PostgreSQL database. Vendor document reconciliation runs inside the main API. Nova billing reconciliation has its own API.

## Demo sign-in

Open [Reckon.ai sign-in](http://127.0.0.1:5174/login). On the local Vite development server, choose a role in **Demo account**, then click **Sign In**. The selector fills the form and the backend authenticates the account. Production builds use manual sign-in. Usernames are case-sensitive. These four accounts already exist in the configured hackathon database.

| Username | Password | Role | Workspace |
| --- | --- | --- | --- |
| `vibhanshu` | `vibhanshu123` | Admin | AVINASH CAPITAL MARKETS PVT LTD |
| `ravi` | `ravi123` | Member | AVINASH CAPITAL MARKETS PVT LTD |
| `arjun` | `arjun123` | Approver | AVINASH CAPITAL MARKETS PVT LTD |
| `finance` | `finance123` | Finance controller | Demo Company Pvt Ltd |

Use lowercase `ravi` for the member demo. The database also contains a distinct `Ravi` approver. Use `vibhanshu`, `ravi`, and `arjun` to demonstrate work in the same tenant. Use `finance` with invoices in **Demo Company Pvt Ltd**. The finance controller assigned to the first tenant is `salman`.

## Prepare the machine and database

Install Python 3.11, Node.js 20.19 or newer in the 20.x series, npm, and Git. PDF rasterization workflows also need Poppler available on PATH or through `POPPLER_PATH`. Start from the team's `dev` checkout. On a new machine:

```powershell
git clone --branch dev https://github.com/r-rishit27/equal_hackathon.git Equals
Set-Location Equals
py -3.11 --version
node --version
npm.cmd --version
```

Use a team-provisioned hackathon database or restore a copy of the seeded PostgreSQL 15 database, including its base schema, users, tenant licenses and demo documents. An empty PostgreSQL database needs that baseline before incremental migrations. A fresh clone alone cannot reproduce the four logins.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Use the [root environment template](.env.example) as the configuration reference. Set `DB_URL` to the connection string for that demo database. The API, Nova and the pipeline all read the root `.env`. Supply the team's local `JWT_SECRET` and existing encryption keys privately. For Nova, `NOVA_KEY_ENCRYPTION_KEY` must match the key used to save the workspace's Nova credentials. Check Integrations → Nova and the [vendor mapping](lendix/nova_vendor_mapping.json) before demonstrating a populated ledger. For OCR or AI extraction, configure the provider selected in `.env`. For live WhatsApp delivery, configure the sender in Integrations and use a publicly reachable signed Twilio webhook. Local sign-in and viewing saved data do not test provider connectivity.

## Install dependencies

Use separate Python environments for the main API, Nova and the pipeline. Run once per checkout and repeat the installation commands after dependency changes.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend_ocr/requirements.txt
py -3.11 -m venv .venv-nova
.\.venv-nova\Scripts\python.exe -m pip install -r services/nova_reconciliation/requirements.txt
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci --prefix frontend
```

With `DB_URL` pointing at your isolated demo database, apply the API migrations before the first launch or after a schema change:

```powershell
.\.venv\Scripts\python.exe scripts/run_api_migrations.py
```

## Start the stack together

Run this whole block from the root in one PowerShell terminal. It starts the frontend on **5174**, the main API on **8014**, Nova on **8100**, and the pipeline in the background of the same terminal. The API starts the vendor reconciliation, cash application and WhatsApp workers. These workers consume queued records, so use the team's isolated demo database. If the local stack is already running, use the checks below before starting a second copy.

```powershell
$repo = (Get-Location).Path
$env:PYTHONUTF8 = '1'
$env:VITE_API_URL = 'http://127.0.0.1:8014'
$env:VITE_NOVA_RECONCILIATION_API_URL = 'http://127.0.0.1:8100'
$env:RECON_WORKER_ENABLED = 'true'
$env:CASHAPP_WORKER_ENABLED = 'true'
$env:WA_WORKER_ENABLED = 'true'
$env:NOVA_ORCHESTRATOR_ENABLED = 'true'
$env:PIPELINE_TENANT_ID = 'd0e00000-0000-0000-0000-000000000003,d0e00000-0000-0000-0000-000000000001'

$services = @(
    @{ Name='Main API and recon'; Dir='backend_ocr'; Exe="$repo\.venv\Scripts\python.exe"; Args=@('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8014') }
    @{ Name='Nova'; Dir='services/nova_reconciliation'; Exe="$repo\.venv-nova\Scripts\python.exe"; Args=@('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8100') }
    @{ Name='Pipeline'; Dir='.'; Exe="$repo\venv\Scripts\python.exe"; Args=@('-u','main.py') }
    @{ Name='Frontend'; Dir='frontend'; Exe=(Get-Command node.exe).Source; Args=@('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5174','--strictPort') }
)
$started = @()
    try -*    $process = Start-Process -FilePath $service.Exe -ArgumentList $service.Args -WorkingDirectory (Join-Path $repo $service.Dir) -NoNewWindow -PassThru -ErrorAction Stop
        $started += $process
        Write-Host "$($service.Name) started with PID $($process.Id)"
    }
    Write-Host 'Press Ctrl+C here to stop this stack.'
    while ($true) {
        foreach ($process in $started) {
            if ($process.HasExited) { throw "Process $($process.Id) exited with code $($process.ExitCode). Check its output above." }
        }
        Start-Sleep -Seconds 2
    }
} finally {
    foreach ($process in $started) {
        if (!$process.HasExited) { Stop-Process -InputObject $process -ErrorAction SilentlyContinue }
    }
}
```

The pipeline prints the workers it actually started and takes a database singleton lock. If it reports that another instance owns the lock, find the existing pipeline or use a separate database. Tally read/sync and bank verification are disabled in the current [pipeline entry point](main.py). A license or a saved connection alone does not start those workers.

## Check the demo

Open another PowerShell terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8014/health
Invoke-RestMethod http://127.0.0.1:8100/health
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5174/login).StatusCode
```

Both APIs should return `status = ok` and the frontend should return HTTP 200. Check the pipeline terminal for `Singleton lock acquired` and `Started … workers`. Then exercise the workflow with a sample invoice:

1. Sign in as `ravi`, open **Upload Invoices**, upload a demo invoice and record its invoice number. Check its extraction and approval status in **Bills**.
2. Sign in as `arjun` and open **Bills → My Approvals**. Use an invoice assigned to Arjun by its approval chain.
3. Sign in as `vibhanshu` and open [Agent Hub](http://127.0.0.1:5174/agent-hub) for intake activity. In a reconciliation-enabled brand such as Bata, open **Vendors → vendor → Reconciliation** and inspect the dashboard and supporting documents.
4. Open [Nova](http://127.0.0.1:5174/nova) and select a mapped vendor and service month. A healthy Nova process can still return an upstream authorization error if the provider key is invalid.
5. Sign in as `finance` to demonstrate the finance-controller role using an assigned bill in Demo Company. Role checks, tenant selection and invoice assignment all affect which actions appear.

For component tests and a TypeScript check, run `npm.cmd --prefix frontend test` and `npm.cmd --prefix frontend run typecheck`. See the [README](README.md) for backend tests, worker details and deployment instructions.
