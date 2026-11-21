# Full Database Schema Documentation

Snapshot of the `public` schema in `onsumm_db` on 21 November 2026 (PostgreSQL 17.9). The schema contains 166 tables and 34 enum types. The default development connection is `DEV_DB_URL`.

## Enum Types

### `account_type`

`ASSET`, `LIABILITY`, `INCOME`, `EXPENSE`, `EQUITY`

### `audit_action`

`INSERT`, `UPDATE`, `DELETE`

### `bank_account_type`

`CURRENT`, `SAVINGS`, `OVERDRAFT`

### `bill_verification_flag`

`GREEN`, `YELLOW`, `RED`

### `billing_discrepancy_status`

`OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISPUTED_WITH_VENDOR`, `IGNORED`

### `billing_discrepancy_type`

`QTY_MISMATCH`, `RATE_MISMATCH`, `COST_MISMATCH`, `MISSING_IN_NOVA`, `MISSING_IN_INVOICE`, `UNMAPPED_LINE_ITEM`, `ENTITY_UNRESOLVED`, `NOVA_SNAPSHOT_UNAVAILABLE`, `NOVA_SELF_INCONSISTENT`, `RATE_CHANGED_MOM`

### `billing_reconciliation_status`

`PENDING`, `RUNNING`, `COMPLETED`, `COMPLETED_WITH_DISCREPANCIES`, `FAILED`

### `conflict_resolution`

`OUTBOUND_WRITE`, `SKIP`, `LOG_CONFLICT`

### `connection_status`

`ACTIVE`, `PAUSED`, `ERROR`, `DISCONNECTED`, `PENDING`, `REVOKED`

### `data_source`

`TALLY`, `ZOHO`, `QBO`, `XERO`, `FRESHBOOKS`, `SAGE`, `MYOB`, `WAVE`, `RAZORPAY`, `STRIPE`, `UPLOAD`, `MANUAL`, `GENERIC_REST`, `SAP`

### `entity_type`

`INVOICE`, `PAYMENT`, `BILL`, `CREDIT_NOTE`, `CUSTOMER`, `SUPPLIER`, `JOURNAL`

### `invoice_status`

`DRAFT`, `SENT`, `PARTIAL`, `PAID`, `OVERDUE`, `VOID`, `PENDING_APPROVER`, `PENDING_ACCOUNTANT`, `PENDING_FC`, `NEEDS_REVISION`, `PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`

### `nudge_channel`

`EMAIL`, `SMS`, `WHATSAPP`, `SLACK`, `IN_APP`

### `nudge_status`

`PENDING`, `SENT`, `FAILED`, `CANCELLED`

### `ocr_engine`

`PADDLEOCR`, `SERVAM`, `MERGED`, `NONE`

### `payment_cycle_type`

`PAYABLE`, `RECEIVABLE`

### `payment_method`

`BANK_TRANSFER`, `UPI`, `CARD`, `CHEQUE`, `CASH`, `GATEWAY`

### `payment_status`

`PENDING`, `CLEARED`, `BOUNCED`, `REFUNDED`

### `plan_tier`

`FREE`, `STARTER`, `GROWTH`, `ENTERPRISE`

### `risk_bucket`

`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`

### `schedule_status`

`PENDING`, `PARTIAL`, `PAID`, `OVERDUE`, `WAIVED`, `DISPUTED`

### `severity_level`

`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`

### `supplier_status`

`ACTIVE`, `SUSPENDED`, `CHURNED`

### `sync_job_status`

`RUNNING`, `COMPLETED`, `FAILED`, `PARTIAL`

### `sync_status`

`PENDING`, `SYNCED`, `ERROR`

### `tally_mode`

`TDL_HTTP`, `XML_SOCKET`, `ODBC`

### `tax_type`

`GST`, `IGST`, `CGST`, `SGST`, `CESS`, `VAT`, `OTHER`

### `txn_status`

`INITIATED`, `PROCESSING`, `COMPLETED`, `FAILED`, `BOUNCED`, `REVERSED`, `CANCELLED`

### `upload_file_type`

`PDF`, `PNG`, `JPG`, `TIFF`, `XLSX`, `CSV`

### `upload_status`

`RECEIVED`, `PREPROCESSING`, `OCR_PRIMARY`, `OCR_FALLBACK`, `VALIDATING`, `DONE`, `ERROR`, `PREPROCESS_ERROR`

### `validation_flag`

`OK`, `MISMATCH`, `DUPLICATE`, `REVIEW`

### `wf_entity_type`

`INVOICE`, `CUSTOMER`, `PAYMENT`, `SUPPLIER`, `BILL`, `BILLING_DISCREPANCY`

### `wf_task_status`

`PENDING`, `IN_PROGRESS`, `DONE`, `SKIPPED`

### `wf_task_type`

`NUDGE`, `ESCALATE`, `APPROVE`, `REVIEW`, `ALERT`

## Table: `admin_audit_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `bigint` | NO | `nextval('admin_audit_log_id_seq'::regclass)` |
| `actor_platform_user_id` | `uuid` | YES | None |
| `actor_email` | `text` | NO | `'system'::text` |
| `action` | `text` | NO | None |
| `target_type` | `text` | NO | None |
| `target_id` | `text` | YES | None |
| `tenant_id` | `uuid` | YES | None |
| `before` | `jsonb` | YES | None |
| `after` | `jsonb` | YES | None |
| `impersonation_id` | `uuid` | YES | None |
| `ip` | `text` | YES | None |
| `user_agent` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `admin_audit_log_pkey` - `PRIMARY KEY (id)`

### Indexes

- `admin_audit_log_pkey` - `CREATE UNIQUE INDEX admin_audit_log_pkey ON public.admin_audit_log USING btree (id)`
- `idx_audit_action` - `CREATE INDEX idx_audit_action ON public.admin_audit_log USING btree (action, created_at DESC)`
- `idx_audit_actor` - `CREATE INDEX idx_audit_actor ON public.admin_audit_log USING btree (actor_platform_user_id, created_at DESC)`
- `idx_audit_tenant` - `CREATE INDEX idx_audit_tenant ON public.admin_audit_log USING btree (tenant_id, created_at DESC)`
- `idx_audit_time` - `CREATE INDEX idx_audit_time ON public.admin_audit_log USING btree (created_at DESC)`

---

## Table: `agent_budgets`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `day` | `date` | NO | None |
| `spent_usd` | `numeric(12,6)` | NO | `0` |
| `calls` | `integer` | NO | `0` |

### Keys and Constraints

- `agent_budgets_pkey` - `PRIMARY KEY (tenant_id, day)`
- `agent_budgets_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `agent_budgets_pkey` - `CREATE UNIQUE INDEX agent_budgets_pkey ON public.agent_budgets USING btree (tenant_id, day)`

---

## Table: `agent_draft_bills`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `contact_id` | `uuid` | YES | None |
| `thread_id` | `text` | YES | None |
| `message_gmail_id` | `text` | YES | None |
| `from_email` | `text` | YES | None |
| `subject` | `text` | YES | None |
| `source_file` | `text` | NO | None |
| `ocr_payload` | `jsonb` | NO | None |
| `status` | `text` | NO | `'pending'::text` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `analysis` | `text` | YES | None |
| `suggestion` | `text` | YES | None |
| `related_invoice` | `text` | YES | None |

### Keys and Constraints

- `agent_draft_bills_pkey` - `PRIMARY KEY (id)`

### Indexes

- `agent_draft_bills_pkey` - `CREATE UNIQUE INDEX agent_draft_bills_pkey ON public.agent_draft_bills USING btree (id)`
- `idx_adb_tenant_status` - `CREATE INDEX idx_adb_tenant_status ON public.agent_draft_bills USING btree (tenant_id, status)`
- `idx_adb_thread` - `CREATE INDEX idx_adb_thread ON public.agent_draft_bills USING btree (tenant_id, thread_id)`

---

## Table: `agent_email_events`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `contact_id` | `uuid` | YES | None |
| `message_gmail_id` | `text` | NO | None |
| `thread_id` | `text` | YES | None |
| `from_email` | `text` | YES | None |
| `subject` | `text` | YES | None |
| `action` | `text` | NO | None |
| `detail` | `text` | YES | None |
| `draft_id` | `uuid` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `agent_email_events_pkey` - `PRIMARY KEY (id)`
- `agent_email_events_tenant_id_message_gmail_id_key` - `UNIQUE (tenant_id, message_gmail_id)`

### Indexes

- `agent_email_events_pkey` - `CREATE UNIQUE INDEX agent_email_events_pkey ON public.agent_email_events USING btree (id)`
- `agent_email_events_tenant_id_message_gmail_id_key` - `CREATE UNIQUE INDEX agent_email_events_tenant_id_message_gmail_id_key ON public.agent_email_events USING btree (tenant_id, message_gmail_id)`
- `idx_aee_tenant_time` - `CREATE INDEX idx_aee_tenant_time ON public.agent_email_events USING btree (tenant_id, created_at DESC)`

---

## Table: `agent_registry`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `agent_id` | `uuid` | NO | `gen_random_uuid()` |
| `name` | `text` | NO | None |
| `display_name` | `text` | NO | None |
| `description` | `text` | YES | None |
| `autonomy` | `smallint` | NO | `0` |
| `enabled` | `boolean` | NO | `true` |
| `config` | `jsonb` | NO | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `agent_registry_autonomy_check` - `CHECK (((autonomy >= 0) AND (autonomy <= 3)))`
- `agent_registry_name_key` - `UNIQUE (name)`
- `agent_registry_pkey` - `PRIMARY KEY (agent_id)`

### Indexes

- `agent_registry_name_key` - `CREATE UNIQUE INDEX agent_registry_name_key ON public.agent_registry USING btree (name)`
- `agent_registry_pkey` - `CREATE UNIQUE INDEX agent_registry_pkey ON public.agent_registry USING btree (agent_id)`

---

## Table: `agent_runs`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `run_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `agent_name` | `text` | NO | None |
| `parent_run_id` | `uuid` | YES | None |
| `trigger_type` | `text` | NO | None |
| `trigger_ref` | `text` | YES | None |
| `subject_type` | `text` | YES | None |
| `subject_id` | `uuid` | YES | None |
| `requested_by` | `text` | YES | None |
| `status` | `text` | NO | `'RUNNING'::text` |
| `outcome` | `jsonb` | NO | `'{}'::jsonb` |
| `steps` | `jsonb` | NO | `'[]'::jsonb` |
| `tools_used` | `text[]` | NO | `'{}'::text[]` |
| `error` | `text` | YES | None |
| `model` | `text` | YES | None |
| `prompt_version` | `text` | YES | None |
| `input_tokens` | `integer` | NO | `0` |
| `output_tokens` | `integer` | NO | `0` |
| `cost_usd` | `numeric(12,6)` | NO | `0` |
| `latency_ms` | `integer` | YES | None |
| `started_at` | `timestamp with time zone` | NO | `now()` |
| `finished_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `agent_runs_parent_run_id_fkey` - `FOREIGN KEY (parent_run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL`
- `agent_runs_pkey` - `PRIMARY KEY (run_id)`
- `agent_runs_status_check` - `CHECK ((status = ANY (ARRAY['RUNNING'::text, 'SUCCEEDED'::text, 'FAILED'::text, 'SKIPPED'::text, 'REFUSED'::text])))`
- `agent_runs_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `agent_runs_pkey` - `CREATE UNIQUE INDEX agent_runs_pkey ON public.agent_runs USING btree (run_id)`
- `idx_agent_runs_cost` - `CREATE INDEX idx_agent_runs_cost ON public.agent_runs USING btree (tenant_id, started_at) WHERE (cost_usd > (0)::numeric)`
- `idx_agent_runs_subject` - `CREATE INDEX idx_agent_runs_subject ON public.agent_runs USING btree (tenant_id, subject_type, subject_id, started_at DESC)`
- `idx_agent_runs_tenant` - `CREATE INDEX idx_agent_runs_tenant ON public.agent_runs USING btree (tenant_id, started_at DESC)`

---

## Table: `agent_settings`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `enabled` | `boolean` | NO | `true` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `agent_settings_pkey` - `PRIMARY KEY (tenant_id)`

### Indexes

- `agent_settings_pkey` - `CREATE UNIQUE INDEX agent_settings_pkey ON public.agent_settings USING btree (tenant_id)`

---

## Table: `ai_anomalies`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `anomaly_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `entity_type` | `entity_type` | NO | None |
| `entity_id` | `uuid` | NO | None |
| `anomaly_type` | `text` | NO | None |
| `severity` | `severity_level` | NO | None |
| `description` | `text` | YES | None |
| `features_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `is_resolved` | `boolean` | NO | `false` |
| `resolved_by` | `uuid` | YES | None |
| `resolved_at` | `timestamp with time zone` | YES | None |
| `detected_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ai_anomalies_pkey` - `PRIMARY KEY (anomaly_id)`
- `ai_anomalies_resolved_by_fkey` - `FOREIGN KEY (resolved_by) REFERENCES org_users(user_id) ON DELETE SET NULL`
- `ai_anomalies_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `ai_anomalies_pkey` - `CREATE UNIQUE INDEX ai_anomalies_pkey ON public.ai_anomalies USING btree (anomaly_id)`

---

## Table: `ai_payment_predictions`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `prediction_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `stg_invoice_id` | `uuid` | NO | None |
| `predicted_pay_date` | `date` | YES | None |
| `predicted_pay_date_confidence` | `numeric(5,4)` | YES | None |
| `predicted_amount` | `numeric(18,4)` | YES | None |
| `amount_confidence` | `numeric(5,4)` | YES | None |
| `model_version` | `text` | NO | None |
| `features_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `computed_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ai_payment_predictions_pkey` - `PRIMARY KEY (prediction_id)`
- `ai_payment_predictions_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE RESTRICT`
- `ai_payment_predictions_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `ai_payment_predictions_pkey` - `CREATE UNIQUE INDEX ai_payment_predictions_pkey ON public.ai_payment_predictions USING btree (prediction_id)`

---

## Table: `ai_risk_scores`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `score_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `end_customer_id` | `uuid` | NO | None |
| `score` | `numeric(5,2)` | NO | None |
| `risk_bucket` | `risk_bucket` | NO | None |
| `model_version` | `text` | NO | None |
| `features_jsonb` | `jsonb` | NO | None |
| `explanation_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `computed_at` | `timestamp with time zone` | NO | `now()` |
| `valid_until` | `timestamp with time zone` | YES | None |
| `is_current` | `boolean` | NO | `true` |

### Keys and Constraints

- `ai_risk_scores_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `ai_risk_scores_pkey` - `PRIMARY KEY (score_id)`
- `ai_risk_scores_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `ai_risk_scores_pkey` - `CREATE UNIQUE INDEX ai_risk_scores_pkey ON public.ai_risk_scores USING btree (score_id)`
- `idx_ai_risk_bucket` - `CREATE INDEX idx_ai_risk_bucket ON public.ai_risk_scores USING btree (risk_bucket)`
- `idx_ai_risk_current` - `CREATE INDEX idx_ai_risk_current ON public.ai_risk_scores USING btree (tenant_id, end_customer_id, is_current)`

---

## Table: `ar_applications`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `payment_id` | `uuid` | NO | None |
| `invoice_id` | `uuid` | NO | None |
| `amount_applied` | `numeric(18,2)` | NO | None |
| `tds_amount` | `numeric(18,2)` | NO | `0` |
| `deduction_amount` | `numeric(18,2)` | NO | `0` |
| `reason_code` | `character varying(16)` | YES | None |
| `reason_note` | `text` | YES | None |
| `method` | `character varying(10)` | NO | None |
| `kind` | `character varying(32)` | YES | None |
| `confidence` | `numeric(4,3)` | YES | None |
| `applied_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `reversed_at` | `timestamp with time zone` | YES | None |
| `reversed_by` | `text` | YES | None |

### Keys and Constraints

- `ar_applications_amount_applied_check` - `CHECK ((amount_applied >= (0)::numeric))`
- `ar_applications_deduction_amount_check` - `CHECK ((deduction_amount >= (0)::numeric))`
- `ar_applications_invoice_id_fkey` - `FOREIGN KEY (invoice_id) REFERENCES ar_invoices(id)`
- `ar_applications_payment_id_fkey` - `FOREIGN KEY (payment_id) REFERENCES ar_payments(id) ON DELETE CASCADE`
- `ar_applications_pkey` - `PRIMARY KEY (id)`
- `ar_applications_tds_amount_check` - `CHECK ((tds_amount >= (0)::numeric))`

### Indexes

- `ar_applications_pkey` - `CREATE UNIQUE INDEX ar_applications_pkey ON public.ar_applications USING btree (id)`
- `idx_ar_apps_invoice` - `CREATE INDEX idx_ar_apps_invoice ON public.ar_applications USING btree (tenant_id, invoice_id)`
- `idx_ar_apps_payment` - `CREATE INDEX idx_ar_apps_payment ON public.ar_applications USING btree (tenant_id, payment_id)`

---

## Table: `ar_customers`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `name` | `text` | NO | None |
| `name_norm` | `text` | NO | `''::text` |
| `gstin` | `character varying(15)` | YES | None |
| `pan` | `character varying(10)` | YES | None |
| `email` | `text` | YES | None |
| `phone` | `text` | YES | None |
| `address` | `text` | YES | None |
| `payment_terms_days` | `integer` | YES | None |
| `tds_rate_hint` | `numeric(6,3)` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ar_customers_pkey` - `PRIMARY KEY (id)`

### Indexes

- `ar_customers_pkey` - `CREATE UNIQUE INDEX ar_customers_pkey ON public.ar_customers USING btree (id)`
- `idx_ar_customers_name` - `CREATE INDEX idx_ar_customers_name ON public.ar_customers USING btree (tenant_id, name_norm)`
- `idx_ar_customers_pan` - `CREATE INDEX idx_ar_customers_pan ON public.ar_customers USING btree (tenant_id, pan) WHERE (pan IS NOT NULL)`
- `idx_ar_customers_trgm` - `CREATE INDEX idx_ar_customers_trgm ON public.ar_customers USING gin (name_norm gin_trgm_ops)`
- `uq_ar_customers_gstin` - `CREATE UNIQUE INDEX uq_ar_customers_gstin ON public.ar_customers USING btree (tenant_id, gstin) WHERE (gstin IS NOT NULL)`

---

## Table: `ar_events`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `entity` | `character varying(12)` | NO | None |
| `entity_id` | `uuid` | YES | None |
| `action` | `character varying(32)` | NO | None |
| `actor` | `text` | YES | None |
| `payload` | `jsonb` | YES | None |
| `at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ar_events_pkey` - `PRIMARY KEY (id)`

### Indexes

- `ar_events_pkey` - `CREATE UNIQUE INDEX ar_events_pkey ON public.ar_events USING btree (id)`
- `idx_ar_events_entity` - `CREATE INDEX idx_ar_events_entity ON public.ar_events USING btree (tenant_id, entity, entity_id, at DESC)`

---

## Table: `ar_invoices`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `customer_id` | `uuid` | NO | None |
| `invoice_number` | `text` | NO | None |
| `number_norm` | `text` | YES | `GENERATED ALWAYS AS (regexp_replace(upper(invoice_number), '[^A-Z0-9]'::text, ''::text, 'g'::text)) STORED` |
| `invoice_date` | `date` | YES | None |
| `due_date` | `date` | YES | None |
| `po_number` | `text` | YES | None |
| `po_norm` | `text` | YES | `GENERATED ALWAYS AS (regexp_replace(upper(COALESCE(po_number, ''::text)), '[^A-Z0-9]'::text, ''::text, 'g'::text)) STORED` |
| `currency` | `character(3)` | NO | `'INR'::bpchar` |
| `taxable_amount` | `numeric(18,2)` | YES | None |
| `tax_amount` | `numeric(18,2)` | YES | None |
| `total_amount` | `numeric(18,2)` | NO | None |
| `amount_received` | `numeric(18,2)` | NO | `0` |
| `tds_amount` | `numeric(18,2)` | NO | `0` |
| `deduction_amount` | `numeric(18,2)` | NO | `0` |
| `outstanding` | `numeric(18,2)` | YES | `GENERATED ALWAYS AS ((((total_amount - amount_received) - tds_amount) - deduction_amount)) STORED` |
| `status` | `character varying(16)` | NO | `'open'::character varying` |
| `payment_terms` | `text` | YES | None |
| `source_file` | `text` | YES | None |
| `storage_ref` | `text` | YES | None |
| `payload` | `jsonb` | YES | None |
| `created_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `paid_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `ar_invoices_customer_id_fkey` - `FOREIGN KEY (customer_id) REFERENCES ar_customers(id)`
- `ar_invoices_pkey` - `PRIMARY KEY (id)`
- `ar_invoices_tenant_id_customer_id_invoice_number_key` - `UNIQUE (tenant_id, customer_id, invoice_number)`
- `ar_invoices_total_amount_check` - `CHECK ((total_amount >= (0)::numeric))`

### Indexes

- `ar_invoices_pkey` - `CREATE UNIQUE INDEX ar_invoices_pkey ON public.ar_invoices USING btree (id)`
- `ar_invoices_tenant_id_customer_id_invoice_number_key` - `CREATE UNIQUE INDEX ar_invoices_tenant_id_customer_id_invoice_number_key ON public.ar_invoices USING btree (tenant_id, customer_id, invoice_number)`
- `idx_ar_invoices_num` - `CREATE INDEX idx_ar_invoices_num ON public.ar_invoices USING btree (tenant_id, number_norm)`
- `idx_ar_invoices_open` - `CREATE INDEX idx_ar_invoices_open ON public.ar_invoices USING btree (tenant_id, customer_id, due_date) WHERE ((status)::text = ANY (ARRAY[('open'::character varying)::text, ('partially_paid'::character varying)::text]))`
- `idx_ar_invoices_open_amt` - `CREATE INDEX idx_ar_invoices_open_amt ON public.ar_invoices USING btree (tenant_id, outstanding) WHERE ((status)::text = ANY (ARRAY[('open'::character varying)::text, ('partially_paid'::character varying)::text]))`
- `idx_ar_invoices_po` - `CREATE INDEX idx_ar_invoices_po ON public.ar_invoices USING btree (tenant_id, po_norm) WHERE (po_norm <> ''::text)`

---

## Table: `ar_match_jobs`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `payment_id` | `uuid` | NO | None |
| `reason` | `character varying(16)` | NO | None |
| `status` | `character varying(8)` | NO | `'PENDING'::character varying` |
| `attempts` | `integer` | NO | `0` |
| `run_after` | `timestamp with time zone` | NO | `now()` |
| `locked_at` | `timestamp with time zone` | YES | None |
| `error` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `done_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `ar_match_jobs_payment_id_fkey` - `FOREIGN KEY (payment_id) REFERENCES ar_payments(id) ON DELETE CASCADE`
- `ar_match_jobs_pkey` - `PRIMARY KEY (id)`

### Indexes

- `ar_match_jobs_pkey` - `CREATE UNIQUE INDEX ar_match_jobs_pkey ON public.ar_match_jobs USING btree (id)`
- `idx_ar_jobs_claim` - `CREATE INDEX idx_ar_jobs_claim ON public.ar_match_jobs USING btree (run_after) WHERE ((status)::text = 'PENDING'::text)`
- `uq_ar_jobs_live` - `CREATE UNIQUE INDEX uq_ar_jobs_live ON public.ar_match_jobs USING btree (payment_id) WHERE ((status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('RUNNING'::character varying)::text]))`

---

## Table: `ar_payer_aliases`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `alias_norm` | `text` | NO | None |
| `alias_raw` | `text` | YES | None |
| `customer_id` | `uuid` | NO | None |
| `source` | `character varying(12)` | NO | None |
| `confirmations` | `integer` | NO | `1` |
| `last_seen_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ar_payer_aliases_customer_id_fkey` - `FOREIGN KEY (customer_id) REFERENCES ar_customers(id) ON DELETE CASCADE`
- `ar_payer_aliases_pkey` - `PRIMARY KEY (id)`
- `ar_payer_aliases_tenant_id_alias_norm_customer_id_key` - `UNIQUE (tenant_id, alias_norm, customer_id)`

### Indexes

- `ar_payer_aliases_pkey` - `CREATE UNIQUE INDEX ar_payer_aliases_pkey ON public.ar_payer_aliases USING btree (id)`
- `ar_payer_aliases_tenant_id_alias_norm_customer_id_key` - `CREATE UNIQUE INDEX ar_payer_aliases_tenant_id_alias_norm_customer_id_key ON public.ar_payer_aliases USING btree (tenant_id, alias_norm, customer_id)`
- `idx_ar_aliases_trgm` - `CREATE INDEX idx_ar_aliases_trgm ON public.ar_payer_aliases USING gin (alias_norm gin_trgm_ops)`

---

## Table: `ar_payments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `received_on` | `date` | NO | None |
| `amount` | `numeric(18,2)` | NO | None |
| `currency` | `character(3)` | NO | `'INR'::bpchar` |
| `method` | `character varying(12)` | YES | None |
| `reference` | `text` | YES | None |
| `utr` | `text` | YES | None |
| `payer_name` | `text` | YES | None |
| `payer_account` | `text` | YES | None |
| `narration` | `text` | YES | None |
| `bank_account` | `text` | YES | None |
| `source` | `character varying(16)` | NO | None |
| `source_file` | `text` | YES | None |
| `customer_id` | `uuid` | YES | None |
| `status` | `character varying(20)` | NO | `'unmatched'::character varying` |
| `applied_amount` | `numeric(18,2)` | NO | `0` |
| `suggestion` | `jsonb` | YES | None |
| `match_confidence` | `numeric(4,3)` | YES | None |
| `flags` | `text[]` | NO | `'{}'::text[]` |
| `auto_applied` | `boolean` | NO | `false` |
| `reason_code` | `character varying(24)` | YES | None |
| `note` | `text` | YES | None |
| `fingerprint` | `text` | YES | None |
| `version` | `integer` | NO | `1` |
| `created_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `matched_at` | `timestamp with time zone` | YES | None |
| `applied_at` | `timestamp with time zone` | YES | None |
| `applied_by` | `text` | YES | None |
| `posted_at` | `timestamp with time zone` | YES | None |
| `statement_id` | `uuid` | YES | None |
| `statement_line` | `integer` | YES | None |

### Keys and Constraints

- `ar_payments_amount_check` - `CHECK ((amount > (0)::numeric))`
- `ar_payments_customer_id_fkey` - `FOREIGN KEY (customer_id) REFERENCES ar_customers(id)`
- `ar_payments_pkey` - `PRIMARY KEY (id)`
- `ar_payments_statement_id_fkey` - `FOREIGN KEY (statement_id) REFERENCES ar_statements(id) ON DELETE SET NULL`

### Indexes

- `ar_payments_pkey` - `CREATE UNIQUE INDEX ar_payments_pkey ON public.ar_payments USING btree (id)`
- `idx_ar_payments_customer` - `CREATE INDEX idx_ar_payments_customer ON public.ar_payments USING btree (tenant_id, customer_id)`
- `idx_ar_payments_statement` - `CREATE INDEX idx_ar_payments_statement ON public.ar_payments USING btree (tenant_id, statement_id)`
- `idx_ar_payments_status` - `CREATE INDEX idx_ar_payments_status ON public.ar_payments USING btree (tenant_id, status, received_on DESC)`
- `idx_ar_payments_utr` - `CREATE INDEX idx_ar_payments_utr ON public.ar_payments USING btree (tenant_id, utr) WHERE (utr IS NOT NULL)`
- `uq_ar_payments_fp` - `CREATE UNIQUE INDEX uq_ar_payments_fp ON public.ar_payments USING btree (tenant_id, fingerprint) WHERE (fingerprint IS NOT NULL)`

---

## Table: `ar_remittances`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `payment_id` | `uuid` | YES | None |
| `customer_id` | `uuid` | YES | None |
| `payer_name` | `text` | YES | None |
| `payment_reference` | `text` | YES | None |
| `payment_date` | `date` | YES | None |
| `total_amount` | `numeric(18,2)` | YES | None |
| `lines` | `jsonb` | NO | `'[]'::jsonb` |
| `status` | `character varying(10)` | NO | `'unlinked'::character varying` |
| `source` | `character varying(8)` | NO | None |
| `source_file` | `text` | YES | None |
| `storage_ref` | `text` | YES | None |
| `raw_text` | `text` | YES | None |
| `created_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ar_remittances_customer_id_fkey` - `FOREIGN KEY (customer_id) REFERENCES ar_customers(id)`
- `ar_remittances_payment_id_fkey` - `FOREIGN KEY (payment_id) REFERENCES ar_payments(id) ON DELETE SET NULL`
- `ar_remittances_pkey` - `PRIMARY KEY (id)`

### Indexes

- `ar_remittances_pkey` - `CREATE UNIQUE INDEX ar_remittances_pkey ON public.ar_remittances USING btree (id)`
- `idx_ar_remittances_payment` - `CREATE INDEX idx_ar_remittances_payment ON public.ar_remittances USING btree (tenant_id, payment_id)`
- `idx_ar_remittances_unlinked` - `CREATE INDEX idx_ar_remittances_unlinked ON public.ar_remittances USING btree (tenant_id, total_amount) WHERE ((status)::text = 'unlinked'::text)`

---

## Table: `ar_settings`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `auto_apply_enabled` | `boolean` | NO | `true` |
| `auto_apply_threshold` | `numeric(4,3)` | NO | `0.95` |
| `amount_tolerance` | `numeric(10,2)` | NO | `1.00` |
| `writeoff_tolerance` | `numeric(10,2)` | NO | `0` |
| `tds_rates` | `numeric(6,3)[]` | NO | `'{0.1,1,2,5,10}'::numeric[]` |
| `trust_learned_tds` | `boolean` | NO | `false` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `updated_by` | `text` | YES | None |

### Keys and Constraints

- `ar_settings_pkey` - `PRIMARY KEY (tenant_id)`

### Indexes

- `ar_settings_pkey` - `CREATE UNIQUE INDEX ar_settings_pkey ON public.ar_settings USING btree (tenant_id)`

---

## Table: `ar_statements`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `file_name` | `text` | NO | None |
| `file_format` | `character varying(8)` | NO | None |
| `content_sha256` | `character(64)` | YES | None |
| `storage_ref` | `text` | YES | None |
| `bank_account` | `text` | YES | None |
| `period_from` | `date` | YES | None |
| `period_to` | `date` | YES | None |
| `credits` | `integer` | NO | `0` |
| `imported` | `integer` | NO | `0` |
| `duplicates` | `integer` | NO | `0` |
| `set_aside` | `integer` | NO | `0` |
| `bounces` | `integer` | NO | `0` |
| `lines` | `jsonb` | NO | `'[]'::jsonb` |
| `uploaded_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ar_statements_pkey` - `PRIMARY KEY (id)`

### Indexes

- `ar_statements_pkey` - `CREATE UNIQUE INDEX ar_statements_pkey ON public.ar_statements USING btree (id)`
- `idx_ar_statements_tenant` - `CREATE INDEX idx_ar_statements_tenant ON public.ar_statements USING btree (tenant_id, created_at DESC)`

---

## Table: `auth_refresh_tokens`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `token_hash` | `text` | NO | None |
| `username` | `text` | NO | None |
| `company_id` | `uuid` | NO | None |
| `issued_at` | `timestamp with time zone` | NO | `now()` |
| `expires_at` | `timestamp with time zone` | NO | None |
| `revoked` | `boolean` | NO | `false` |
| `revoked_at` | `timestamp with time zone` | YES | None |
| `replaced_by` | `text` | YES | None |

### Keys and Constraints

- `auth_refresh_tokens_pkey` - `PRIMARY KEY (id)`
- `auth_refresh_tokens_token_hash_key` - `UNIQUE (token_hash)`

### Indexes

- `auth_refresh_tokens_pkey` - `CREATE UNIQUE INDEX auth_refresh_tokens_pkey ON public.auth_refresh_tokens USING btree (id)`
- `auth_refresh_tokens_token_hash_key` - `CREATE UNIQUE INDEX auth_refresh_tokens_token_hash_key ON public.auth_refresh_tokens USING btree (token_hash)`
- `idx_refresh_username` - `CREATE INDEX idx_refresh_username ON public.auth_refresh_tokens USING btree (username)`

---

## Table: `auth_sso_codes`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `code_hash` | `text` | NO | None |
| `username` | `text` | NO | None |
| `company_id` | `uuid` | NO | None |
| `provider` | `text` | NO | None |
| `expires_at` | `timestamp with time zone` | NO | None |
| `used_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `auth_sso_codes_code_hash_key` - `UNIQUE (code_hash)`
- `auth_sso_codes_pkey` - `PRIMARY KEY (id)`

### Indexes

- `auth_sso_codes_code_hash_key` - `CREATE UNIQUE INDEX auth_sso_codes_code_hash_key ON public.auth_sso_codes USING btree (code_hash)`
- `auth_sso_codes_pkey` - `CREATE UNIQUE INDEX auth_sso_codes_pkey ON public.auth_sso_codes USING btree (id)`
- `idx_sso_codes_expiry` - `CREATE INDEX idx_sso_codes_expiry ON public.auth_sso_codes USING btree (expires_at)`

---

## Table: `bill_approval_chain`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `bigint` | NO | `nextval('bill_approval_chain_id_seq'::regclass)` |
| `invoice_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `step` | `smallint` | NO | None |
| `actor_role` | `character varying(50)` | YES | None |
| `actor_name` | `character varying(100)` | YES | None |
| `action` | `character varying(20)` | NO | None |
| `comment` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | YES | `now()` |
| `target_step` | `integer` | YES | None |

### Keys and Constraints

- `bill_approval_chain_pkey` - `PRIMARY KEY (id)`

### Indexes

- `bill_approval_chain_pkey` - `CREATE UNIQUE INDEX bill_approval_chain_pkey ON public.bill_approval_chain USING btree (id)`

---

## Table: `bill_attachment_edits`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `attachment_id` | `uuid` | NO | None |
| `invoice_id` | `uuid` | NO | None |
| `edited_by` | `character varying(100)` | YES | None |
| `edited_at` | `timestamp with time zone` | YES | `now()` |
| `diff_json` | `jsonb` | NO | None |

### Keys and Constraints

- `bill_attachment_edits_pkey` - `PRIMARY KEY (id)`

### Indexes

- `bill_attachment_edits_pkey` - `CREATE UNIQUE INDEX bill_attachment_edits_pkey ON public.bill_attachment_edits USING btree (id)`

---

## Table: `bill_attachments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `invoice_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `file_path` | `text` | NO | None |
| `file_name` | `text` | NO | None |
| `file_type` | `text` | YES | None |
| `file_size` | `bigint` | YES | None |
| `uploaded_by` | `text` | YES | None |
| `uploaded_at` | `timestamp with time zone` | NO | `now()` |
| `deleted_at` | `timestamp with time zone` | YES | None |
| `deleted_by` | `text` | YES | None |

### Keys and Constraints

- `bill_attachments_pkey` - `PRIMARY KEY (id)`

### Indexes

- `bill_attachments_pkey` - `CREATE UNIQUE INDEX bill_attachments_pkey ON public.bill_attachments USING btree (id)`
- `idx_bill_attachments_invoice` - `CREATE INDEX idx_bill_attachments_invoice ON public.bill_attachments USING btree (invoice_id)`

---

## Table: `billing_bill_reconciliation`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `invoice_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `result` | `jsonb` | NO | None |
| `computed_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `billing_bill_reconciliation_invoice_id_fkey` - `FOREIGN KEY (invoice_id) REFERENCES fact_invoices(invoice_id) ON DELETE CASCADE`
- `billing_bill_reconciliation_pkey` - `PRIMARY KEY (invoice_id)`

### Indexes

- `billing_bill_reconciliation_pkey` - `CREATE UNIQUE INDEX billing_bill_reconciliation_pkey ON public.billing_bill_reconciliation USING btree (invoice_id)`

---

## Table: `billing_nova_usage_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `usage_line_id` | `uuid` | NO | `gen_random_uuid()` |
| `snapshot_id` | `uuid` | NO | None |
| `nova_usage_slug` | `text` | NO | None |
| `api_call_count` | `integer` | NO | None |
| `billable_operations` | `integer` | NO | None |
| `cost_per_operation` | `numeric` | NO | None |
| `total_cost_rupees` | `numeric` | NO | None |

### Keys and Constraints

- `billing_nova_usage_lines_pkey` - `PRIMARY KEY (usage_line_id)`
- `billing_nova_usage_lines_snapshot_id_fkey` - `FOREIGN KEY (snapshot_id) REFERENCES billing_nova_usage_snapshots(snapshot_id) ON DELETE CASCADE`
- `billing_nova_usage_lines_snapshot_id_nova_usage_slug_key` - `UNIQUE (snapshot_id, nova_usage_slug)`

### Indexes

- `billing_nova_usage_lines_pkey` - `CREATE UNIQUE INDEX billing_nova_usage_lines_pkey ON public.billing_nova_usage_lines USING btree (usage_line_id)`
- `billing_nova_usage_lines_snapshot_id_nova_usage_slug_key` - `CREATE UNIQUE INDEX billing_nova_usage_lines_snapshot_id_nova_usage_slug_key ON public.billing_nova_usage_lines USING btree (snapshot_id, nova_usage_slug)`

---

## Table: `billing_nova_usage_snapshots`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `snapshot_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `vendor_name` | `text` | NO | None |
| `billing_month` | `text` | NO | None |
| `total_billable_operations` | `integer` | NO | None |
| `total_cost_rupees` | `numeric` | NO | None |
| `raw_response_jsonb` | `jsonb` | NO | None |
| `nova_reference_id` | `text` | YES | None |
| `fetched_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `billing_nova_usage_snapshots_pkey` - `PRIMARY KEY (snapshot_id)`
- `billing_nova_usage_snapshots_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `billing_nova_usage_snapshots_tenant_id_vendor_name_billing__key` - `UNIQUE (tenant_id, vendor_name, billing_month)`

### Indexes

- `billing_nova_usage_snapshots_pkey` - `CREATE UNIQUE INDEX billing_nova_usage_snapshots_pkey ON public.billing_nova_usage_snapshots USING btree (snapshot_id)`
- `billing_nova_usage_snapshots_tenant_id_vendor_name_billing__key` - `CREATE UNIQUE INDEX billing_nova_usage_snapshots_tenant_id_vendor_name_billing__key ON public.billing_nova_usage_snapshots USING btree (tenant_id, vendor_name, billing_month)`

---

## Table: `billing_reconciliation_discrepancies`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `discrepancy_id` | `uuid` | NO | `gen_random_uuid()` |
| `run_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `nova_module` | `text` | YES | None |
| `discrepancy_type` | `billing_discrepancy_type` | NO | None |
| `severity` | `severity_level` | NO | None |
| `invoice_value` | `jsonb` | YES | None |
| `nova_value` | `jsonb` | YES | None |
| `variance_pct` | `numeric` | YES | None |
| `variance_amount` | `numeric` | YES | None |
| `status` | `billing_discrepancy_status` | NO | `'OPEN'::billing_discrepancy_status` |
| `resolution_note` | `text` | YES | None |
| `resolved_by` | `uuid` | YES | None |
| `resolved_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `billing_reconciliation_discrepancies_pkey` - `PRIMARY KEY (discrepancy_id)`
- `billing_reconciliation_discrepancies_resolved_by_fkey` - `FOREIGN KEY (resolved_by) REFERENCES org_users(user_id)`
- `billing_reconciliation_discrepancies_run_id_fkey` - `FOREIGN KEY (run_id) REFERENCES billing_reconciliation_runs(run_id) ON DELETE CASCADE`
- `billing_reconciliation_discrepancies_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `billing_reconciliation_discrepancies_pkey` - `CREATE UNIQUE INDEX billing_reconciliation_discrepancies_pkey ON public.billing_reconciliation_discrepancies USING btree (discrepancy_id)`
- `idx_billing_disc_run` - `CREATE INDEX idx_billing_disc_run ON public.billing_reconciliation_discrepancies USING btree (run_id)`
- `idx_billing_disc_tenant_severity` - `CREATE INDEX idx_billing_disc_tenant_severity ON public.billing_reconciliation_discrepancies USING btree (tenant_id, severity)`
- `idx_billing_disc_tenant_status` - `CREATE INDEX idx_billing_disc_tenant_status ON public.billing_reconciliation_discrepancies USING btree (tenant_id, status)`

---

## Table: `billing_reconciliation_runs`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `run_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `vendor_name` | `text` | NO | None |
| `billing_month` | `text` | NO | None |
| `vendor_invoice_id` | `uuid` | YES | None |
| `snapshot_id` | `uuid` | YES | None |
| `status` | `billing_reconciliation_status` | NO | `'PENDING'::billing_reconciliation_status` |
| `total_invoice_amount` | `numeric` | YES | None |
| `total_nova_cost` | `numeric` | YES | None |
| `variance_amount` | `numeric` | YES | None |
| `started_at` | `timestamp with time zone` | NO | `now()` |
| `completed_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `billing_reconciliation_runs_pkey` - `PRIMARY KEY (run_id)`
- `billing_reconciliation_runs_snapshot_id_fkey` - `FOREIGN KEY (snapshot_id) REFERENCES billing_nova_usage_snapshots(snapshot_id)`
- `billing_reconciliation_runs_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `billing_reconciliation_runs_tenant_vendor_month_key` - `UNIQUE (tenant_id, vendor_name, billing_month)`
- `billing_reconciliation_runs_vendor_invoice_id_fkey` - `FOREIGN KEY (vendor_invoice_id) REFERENCES billing_vendor_invoices(vendor_invoice_id)`

### Indexes

- `billing_reconciliation_runs_pkey` - `CREATE UNIQUE INDEX billing_reconciliation_runs_pkey ON public.billing_reconciliation_runs USING btree (run_id)`
- `billing_reconciliation_runs_tenant_vendor_month_key` - `CREATE UNIQUE INDEX billing_reconciliation_runs_tenant_vendor_month_key ON public.billing_reconciliation_runs USING btree (tenant_id, vendor_name, billing_month)`

---

## Table: `billing_vendor_accounts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `vendor_account_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `vendor_name` | `text` | NO | None |
| `legal_entity_name` | `text` | NO | None |
| `gstin` | `character(15)` | YES | None |
| `nova_sub_account_id` | `text` | YES | None |
| `nova_api_key_ref` | `text` | NO | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `supplier_id` | `uuid` | YES | None |

### Keys and Constraints

- `billing_vendor_accounts_pkey` - `PRIMARY KEY (vendor_account_id)`
- `billing_vendor_accounts_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id)`
- `billing_vendor_accounts_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `billing_vendor_accounts_tenant_id_vendor_name_key` - `UNIQUE (tenant_id, vendor_name)`

### Indexes

- `billing_vendor_accounts_pkey` - `CREATE UNIQUE INDEX billing_vendor_accounts_pkey ON public.billing_vendor_accounts USING btree (vendor_account_id)`
- `billing_vendor_accounts_tenant_id_vendor_name_key` - `CREATE UNIQUE INDEX billing_vendor_accounts_tenant_id_vendor_name_key ON public.billing_vendor_accounts USING btree (tenant_id, vendor_name)`

---

## Table: `billing_vendor_invoice_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `line_id` | `uuid` | NO | `gen_random_uuid()` |
| `vendor_invoice_id` | `uuid` | NO | None |
| `line_number` | `smallint` | NO | None |
| `description` | `text` | NO | None |
| `hsn_sac` | `text` | YES | None |
| `quantity` | `numeric` | NO | None |
| `rate` | `numeric` | NO | None |
| `tax_pct` | `numeric` | NO | `0` |
| `amount` | `numeric` | NO | None |
| `nova_module` | `text` | YES | None |

### Keys and Constraints

- `billing_vendor_invoice_lines_pkey` - `PRIMARY KEY (line_id)`
- `billing_vendor_invoice_lines_vendor_invoice_id_fkey` - `FOREIGN KEY (vendor_invoice_id) REFERENCES billing_vendor_invoices(vendor_invoice_id) ON DELETE CASCADE`

### Indexes

- `billing_vendor_invoice_lines_pkey` - `CREATE UNIQUE INDEX billing_vendor_invoice_lines_pkey ON public.billing_vendor_invoice_lines USING btree (line_id)`

---

## Table: `billing_vendor_invoices`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `vendor_invoice_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `vendor_account_id` | `uuid` | NO | None |
| `upload_id` | `uuid` | YES | None |
| `bill_id` | `uuid` | YES | None |
| `invoice_number` | `text` | NO | None |
| `invoice_date` | `date` | NO | None |
| `billing_period` | `text` | NO | None |
| `subtotal` | `numeric` | NO | None |
| `tax_amount` | `numeric` | NO | `0` |
| `total_amount` | `numeric` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `verification_flag` | `bill_verification_flag` | NO | `'YELLOW'::bill_verification_flag` |
| `verification_detail` | `text` | YES | None |
| `verified_at` | `timestamp with time zone` | YES | None |
| `invoice_id` | `uuid` | YES | None |

### Keys and Constraints

- `billing_vendor_invoices_bill_id_fkey` - `FOREIGN KEY (bill_id) REFERENCES fact_bills(bill_id)`
- `billing_vendor_invoices_invoice_id_fkey` - `FOREIGN KEY (invoice_id) REFERENCES fact_invoices(invoice_id)`
- `billing_vendor_invoices_pkey` - `PRIMARY KEY (vendor_invoice_id)`
- `billing_vendor_invoices_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `billing_vendor_invoices_upload_id_fkey` - `FOREIGN KEY (upload_id) REFERENCES raw_invoice_uploads(upload_id)`
- `billing_vendor_invoices_vendor_account_id_fkey` - `FOREIGN KEY (vendor_account_id) REFERENCES billing_vendor_accounts(vendor_account_id)`
- `billing_vendor_invoices_vendor_account_id_invoice_number_key` - `UNIQUE (vendor_account_id, invoice_number)`

### Indexes

- `billing_vendor_invoices_pkey` - `CREATE UNIQUE INDEX billing_vendor_invoices_pkey ON public.billing_vendor_invoices USING btree (vendor_invoice_id)`
- `billing_vendor_invoices_vendor_account_id_invoice_number_key` - `CREATE UNIQUE INDEX billing_vendor_invoices_vendor_account_id_invoice_number_key ON public.billing_vendor_invoices USING btree (vendor_account_id, invoice_number)`

---

## Table: `billing_vendor_module_alias`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `alias_id` | `uuid` | NO | `gen_random_uuid()` |
| `vendor_name` | `text` | NO | None |
| `invoice_line_pattern` | `text` | YES | None |
| `nova_module` | `text` | NO | None |
| `nova_usage_slug` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `billing_basis` | `text` | NO | `'BILLABLE_OPERATIONS'::text` |

### Keys and Constraints

- `billing_vendor_module_alias_pattern_key` - `UNIQUE (vendor_name, nova_module, invoice_line_pattern)`
- `billing_vendor_module_alias_pkey` - `PRIMARY KEY (alias_id)`

### Indexes

- `billing_vendor_module_alias_pattern_key` - `CREATE UNIQUE INDEX billing_vendor_module_alias_pattern_key ON public.billing_vendor_module_alias USING btree (vendor_name, nova_module, invoice_line_pattern)`
- `billing_vendor_module_alias_pkey` - `CREATE UNIQUE INDEX billing_vendor_module_alias_pkey ON public.billing_vendor_module_alias USING btree (alias_id)`

---

## Table: `brands`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `name` | `character varying(255)` | NO | None |
| `logo_path` | `text` | YES | None |
| `is_default` | `boolean` | NO | `false` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `brands_pkey` - `PRIMARY KEY (id)`

### Indexes

- `brands_pkey` - `CREATE UNIQUE INDEX brands_pkey ON public.brands USING btree (id)`
- `idx_brands_tenant` - `CREATE INDEX idx_brands_tenant ON public.brands USING btree (tenant_id)`

---

## Table: `coa_rules`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `exp_head` | `text` | NO | None |
| `vendor_name` | `text` | YES | None |
| `category` | `text` | YES | None |
| `priority` | `integer` | NO | `0` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `coa_rules_pkey` - `PRIMARY KEY (id)`

### Indexes

- `coa_rules_pkey` - `CREATE UNIQUE INDEX coa_rules_pkey ON public.coa_rules USING btree (id)`
- `idx_coa_rules_tenant` - `CREATE INDEX idx_coa_rules_tenant ON public.coa_rules USING btree (tenant_id)`

---

## Table: `comm_extractions`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `extraction_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source_type` | `text` | NO | None |
| `source_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `contact_id` | `uuid` | YES | None |
| `thread_id` | `text` | YES | None |
| `model` | `text` | YES | None |
| `prompt_version` | `text` | YES | None |
| `agent_run_id` | `uuid` | YES | None |
| `claims` | `jsonb` | NO | `'[]'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `comm_extractions_pkey` - `PRIMARY KEY (extraction_id)`
- `comm_extractions_source_type_check` - `CHECK ((source_type = ANY (ARRAY['email'::text, 'contract'::text])))`
- `comm_extractions_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `comm_extractions_pkey` - `CREATE UNIQUE INDEX comm_extractions_pkey ON public.comm_extractions USING btree (extraction_id)`
- `idx_comm_extractions_supplier` - `CREATE INDEX idx_comm_extractions_supplier ON public.comm_extractions USING btree (tenant_id, supplier_id, created_at DESC)`

---

## Table: `comm_thread_state`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `thread_id` | `text` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `contact_id` | `uuid` | YES | None |
| `purpose` | `text` | NO | `'general'::text` |
| `status` | `text` | NO | `'open'::text` |
| `linked_subject_type` | `text` | YES | None |
| `linked_subject_id` | `uuid` | YES | None |
| `last_direction` | `text` | YES | None |
| `last_message_at` | `timestamp with time zone` | YES | None |
| `sla_due_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `comm_thread_state_pkey` - `PRIMARY KEY (tenant_id, thread_id)`
- `comm_thread_state_purpose_check` - `CHECK ((purpose = ANY (ARRAY['bill_followup'::text, 'contract_request'::text, 'verification_request'::text, 'general'::text])))`
- `comm_thread_state_status_check` - `CHECK ((status = ANY (ARRAY['open'::text, 'awaiting_vendor'::text, 'awaiting_internal'::text, 'resolved'::text])))`
- `comm_thread_state_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `comm_thread_state_pkey` - `CREATE UNIQUE INDEX comm_thread_state_pkey ON public.comm_thread_state USING btree (tenant_id, thread_id)`
- `idx_comm_thread_state_open` - `CREATE INDEX idx_comm_thread_state_open ON public.comm_thread_state USING btree (tenant_id, status) WHERE (status <> 'resolved'::text)`

---

## Table: `cost_centers`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `brand_id` | `uuid` | NO | None |
| `name` | `character varying(255)` | NO | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `cost_centers_pkey` - `PRIMARY KEY (id)`

### Indexes

- `cost_centers_pkey` - `CREATE UNIQUE INDEX cost_centers_pkey ON public.cost_centers USING btree (id)`
- `idx_cost_centers_tenant_brand` - `CREATE INDEX idx_cost_centers_tenant_brand ON public.cost_centers USING btree (tenant_id, brand_id)`
- `uq_cost_centers_tenant_brand_name` - `CREATE UNIQUE INDEX uq_cost_centers_tenant_brand_name ON public.cost_centers USING btree (tenant_id, brand_id, name)`

---

## Table: `dim_bank_accounts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `bank_account_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_account_id` | `text` | NO | None |
| `account_name` | `text` | NO | None |
| `account_number_enc` | `text` | YES | None |
| `bank_name` | `text` | YES | None |
| `ifsc_code` | `text` | YES | None |
| `swift_code` | `text` | YES | None |
| `account_type` | `bank_account_type` | NO | `'CURRENT'::bank_account_type` |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `is_primary` | `boolean` | NO | `false` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_bank_accounts_pkey` - `PRIMARY KEY (bank_account_id)`
- `dim_bank_accounts_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `dim_bank_accounts_tenant_id_source_source_account_id_key` - `UNIQUE (tenant_id, source, source_account_id)`

### Indexes

- `dim_bank_accounts_pkey` - `CREATE UNIQUE INDEX dim_bank_accounts_pkey ON public.dim_bank_accounts USING btree (bank_account_id)`
- `dim_bank_accounts_tenant_id_source_source_account_id_key` - `CREATE UNIQUE INDEX dim_bank_accounts_tenant_id_source_source_account_id_key ON public.dim_bank_accounts USING btree (tenant_id, source, source_account_id)`
- `idx_dim_bank_accounts_tenant` - `CREATE INDEX idx_dim_bank_accounts_tenant ON public.dim_bank_accounts USING btree (tenant_id)`

---

## Table: `dim_categories`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `name` | `text` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `exp_head` | `text` | YES | None |
| `is_builtin` | `boolean` | NO | `false` |

### Keys and Constraints

- `dim_categories_pkey` - `PRIMARY KEY (id)`
- `dim_categories_tenant_id_name_key` - `UNIQUE (tenant_id, name)`

### Indexes

- `dim_categories_pkey` - `CREATE UNIQUE INDEX dim_categories_pkey ON public.dim_categories USING btree (id)`
- `dim_categories_tenant_id_name_key` - `CREATE UNIQUE INDEX dim_categories_tenant_id_name_key ON public.dim_categories USING btree (tenant_id, name)`
- `idx_dim_categories_tenant` - `CREATE INDEX idx_dim_categories_tenant ON public.dim_categories USING btree (tenant_id)`

---

## Table: `dim_charges`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `charge_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `name` | `text` | NO | None |
| `hsn_sac` | `text` | YES | None |
| `default_ledger_id` | `uuid` | YES | None |
| `default_tax_rate` | `numeric(5,2)` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_charges_pkey` - `PRIMARY KEY (charge_id)`
- `dim_charges_tenant_id_name_key` - `UNIQUE (tenant_id, name)`
- `fk_dim_charges_ledger` - `FOREIGN KEY (default_ledger_id) REFERENCES dim_ledger_accounts(account_id) ON DELETE SET NULL`
- `fk_dim_charges_tenant` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `dim_charges_pkey` - `CREATE UNIQUE INDEX dim_charges_pkey ON public.dim_charges USING btree (charge_id)`
- `dim_charges_tenant_id_name_key` - `CREATE UNIQUE INDEX dim_charges_tenant_id_name_key ON public.dim_charges USING btree (tenant_id, name)`

---

## Table: `dim_cost_centres`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `cost_centre_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source_cc_id` | `text` | NO | None |
| `source` | `data_source` | NO | None |
| `name` | `text` | NO | None |
| `parent_cc_id` | `uuid` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_cost_centres_parent_cc_id_fkey` - `FOREIGN KEY (parent_cc_id) REFERENCES dim_cost_centres(cost_centre_id)`
- `dim_cost_centres_pkey` - `PRIMARY KEY (cost_centre_id)`
- `dim_cost_centres_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `dim_cost_centres_tenant_id_source_source_cc_id_key` - `UNIQUE (tenant_id, source, source_cc_id)`

### Indexes

- `dim_cost_centres_pkey` - `CREATE UNIQUE INDEX dim_cost_centres_pkey ON public.dim_cost_centres USING btree (cost_centre_id)`
- `dim_cost_centres_tenant_id_source_source_cc_id_key` - `CREATE UNIQUE INDEX dim_cost_centres_tenant_id_source_source_cc_id_key ON public.dim_cost_centres USING btree (tenant_id, source, source_cc_id)`

---

## Table: `dim_currencies`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `currency_code` | `character(3)` | NO | None |
| `name` | `text` | NO | None |
| `symbol` | `text` | NO | None |
| `decimal_places` | `smallint` | NO | `2` |
| `is_active` | `boolean` | NO | `true` |

### Keys and Constraints

- `dim_currencies_pkey` - `PRIMARY KEY (currency_code)`

### Indexes

- `dim_currencies_pkey` - `CREATE UNIQUE INDEX dim_currencies_pkey ON public.dim_currencies USING btree (currency_code)`

---

## Table: `dim_customers`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `customer_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source_customer_id` | `text` | NO | None |
| `source` | `data_source` | NO | None |
| `name` | `text` | NO | None |
| `email` | `text` | YES | None |
| `gstn` | `character(15)` | NO | None |
| `phone` | `text` | YES | None |
| `address_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `pii_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `payment_terms_days` | `smallint` | NO | `30` |
| `risk_score` | `numeric(5,2)` | NO | `50` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_customers_pkey` - `PRIMARY KEY (customer_id)`
- `dim_customers_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `dim_customers_tenant_id_source_source_customer_id_key` - `UNIQUE (tenant_id, source, source_customer_id)`

### Indexes

- `dim_customers_pkey` - `CREATE UNIQUE INDEX dim_customers_pkey ON public.dim_customers USING btree (customer_id)`
- `dim_customers_tenant_id_source_source_customer_id_key` - `CREATE UNIQUE INDEX dim_customers_tenant_id_source_source_customer_id_key ON public.dim_customers USING btree (tenant_id, source, source_customer_id)`
- `idx_dim_customers_email` - `CREATE INDEX idx_dim_customers_email ON public.dim_customers USING btree (tenant_id, email) WHERE (email IS NOT NULL)`
- `idx_dim_customers_gstn` - `CREATE INDEX idx_dim_customers_gstn ON public.dim_customers USING btree (gstn) WHERE (gstn IS NOT NULL)`
- `idx_dim_customers_name_trgm` - `CREATE INDEX idx_dim_customers_name_trgm ON public.dim_customers USING gin (name gin_trgm_ops)`
- `idx_dim_customers_tenant` - `CREATE INDEX idx_dim_customers_tenant ON public.dim_customers USING btree (tenant_id)`

---

## Table: `dim_end_customer_contacts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `contact_id` | `uuid` | NO | `gen_random_uuid()` |
| `end_customer_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `full_name` | `text` | NO | None |
| `email` | `text` | YES | None |
| `phone` | `text` | YES | None |
| `designation` | `text` | YES | None |
| `is_primary` | `boolean` | NO | `false` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_end_customer_contacts_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE CASCADE`
- `dim_end_customer_contacts_pkey` - `PRIMARY KEY (contact_id)`
- `dim_end_customer_contacts_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `dim_end_customer_contacts_pkey` - `CREATE UNIQUE INDEX dim_end_customer_contacts_pkey ON public.dim_end_customer_contacts USING btree (contact_id)`
- `uq_primary_contact` - `CREATE UNIQUE INDEX uq_primary_contact ON public.dim_end_customer_contacts USING btree (end_customer_id) WHERE (is_primary = true)`

---

## Table: `dim_end_customers`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `end_customer_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_customer_id` | `text` | NO | None |
| `company_name` | `text` | NO | None |
| `trade_name` | `text` | YES | None |
| `gstin` | `character(15)` | YES | None |
| `pan` | `character(10)` | YES | None |
| `email` | `text` | YES | None |
| `phone` | `text` | YES | None |
| `billing_address_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `shipping_address_jsonb` | `jsonb` | YES | None |
| `payment_terms_days` | `smallint` | NO | `30` |
| `credit_limit` | `numeric(18,4)` | YES | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `risk_score` | `numeric(5,2)` | NO | `50.00` |
| `risk_bucket` | `risk_bucket` | YES | None |
| `kyc_status` | `text` | NO | `'PENDING'::text` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `bank_account_no` | `text` | YES | None |
| `bank_ifsc` | `text` | YES | None |
| `bank_verified` | `boolean` | NO | `false` |

### Keys and Constraints

- `dim_end_customers_pkey` - `PRIMARY KEY (end_customer_id)`
- `dim_end_customers_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `uq_end_customer_source` - `UNIQUE (tenant_id, source, source_customer_id)`

### Indexes

- `dim_end_customers_pkey` - `CREATE UNIQUE INDEX dim_end_customers_pkey ON public.dim_end_customers USING btree (end_customer_id)`
- `idx_end_customers_gstin` - `CREATE INDEX idx_end_customers_gstin ON public.dim_end_customers USING btree (gstin)`
- `idx_end_customers_risk` - `CREATE INDEX idx_end_customers_risk ON public.dim_end_customers USING btree (risk_bucket)`
- `idx_end_customers_tenant` - `CREATE INDEX idx_end_customers_tenant ON public.dim_end_customers USING btree (tenant_id)`
- `uq_end_customer_source` - `CREATE UNIQUE INDEX uq_end_customer_source ON public.dim_end_customers USING btree (tenant_id, source, source_customer_id)`

---

## Table: `dim_fx_rates`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `rate_id` | `uuid` | NO | `gen_random_uuid()` |
| `rate_date` | `date` | NO | None |
| `currency_code` | `character(3)` | NO | None |
| `inr_per_unit` | `numeric(12,6)` | NO | None |
| `source` | `text` | NO | None |
| `is_business_day` | `boolean` | NO | `true` |
| `fetched_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_fx_rates_currency_code_fkey` - `FOREIGN KEY (currency_code) REFERENCES dim_currencies(currency_code)`
- `dim_fx_rates_pkey` - `PRIMARY KEY (rate_id)`
- `dim_fx_rates_rate_date_currency_code_key` - `UNIQUE (rate_date, currency_code)`

### Indexes

- `dim_fx_rates_pkey` - `CREATE UNIQUE INDEX dim_fx_rates_pkey ON public.dim_fx_rates USING btree (rate_id)`
- `dim_fx_rates_rate_date_currency_code_key` - `CREATE UNIQUE INDEX dim_fx_rates_rate_date_currency_code_key ON public.dim_fx_rates USING btree (rate_date, currency_code)`
- `idx_fx_rates_currency_date` - `CREATE INDEX idx_fx_rates_currency_date ON public.dim_fx_rates USING btree (currency_code, rate_date DESC)`
- `idx_fx_rates_date` - `CREATE INDEX idx_fx_rates_date ON public.dim_fx_rates USING btree (rate_date DESC)`

---

## Table: `dim_ledger_accounts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `account_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source_account_id` | `text` | NO | None |
| `source` | `data_source` | NO | None |
| `account_code` | `text` | YES | None |
| `account_name` | `text` | NO | None |
| `account_type` | `text` | NO | None |
| `parent_account_id` | `uuid` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_ledger_accounts_parent_account_id_fkey` - `FOREIGN KEY (parent_account_id) REFERENCES dim_ledger_accounts(account_id)`
- `dim_ledger_accounts_pkey` - `PRIMARY KEY (account_id)`
- `dim_ledger_accounts_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `dim_ledger_accounts_tenant_id_source_source_account_id_key` - `UNIQUE (tenant_id, source, source_account_id)`

### Indexes

- `dim_ledger_accounts_pkey` - `CREATE UNIQUE INDEX dim_ledger_accounts_pkey ON public.dim_ledger_accounts USING btree (account_id)`
- `dim_ledger_accounts_tenant_id_source_source_account_id_key` - `CREATE UNIQUE INDEX dim_ledger_accounts_tenant_id_source_source_account_id_key ON public.dim_ledger_accounts USING btree (tenant_id, source, source_account_id)`
- `idx_dim_ledger_tenant` - `CREATE INDEX idx_dim_ledger_tenant ON public.dim_ledger_accounts USING btree (tenant_id)`
- `idx_ledger_parent` - `CREATE INDEX idx_ledger_parent ON public.dim_ledger_accounts USING btree (parent_account_id)`
- `idx_ledger_tenant` - `CREATE INDEX idx_ledger_tenant ON public.dim_ledger_accounts USING btree (tenant_id)`

---

## Table: `dim_products`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `product_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source_product_id` | `text` | NO | None |
| `source` | `data_source` | NO | None |
| `name` | `text` | NO | None |
| `unit` | `text` | YES | None |
| `hsn_code` | `text` | YES | None |
| `description` | `text` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_products_pkey` - `PRIMARY KEY (product_id)`
- `dim_products_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `dim_products_tenant_id_source_source_product_id_key` - `UNIQUE (tenant_id, source, source_product_id)`

### Indexes

- `dim_products_pkey` - `CREATE UNIQUE INDEX dim_products_pkey ON public.dim_products USING btree (product_id)`
- `dim_products_tenant_id_source_source_product_id_key` - `CREATE UNIQUE INDEX dim_products_tenant_id_source_source_product_id_key ON public.dim_products USING btree (tenant_id, source, source_product_id)`
- `idx_products_hsn` - `CREATE INDEX idx_products_hsn ON public.dim_products USING btree (hsn_code)`
- `idx_products_tenant` - `CREATE INDEX idx_products_tenant ON public.dim_products USING btree (tenant_id)`

---

## Table: `dim_suppliers`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `supplier_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source_supplier_id` | `text` | NO | None |
| `source` | `data_source` | NO | None |
| `name` | `text` | NO | None |
| `gstn` | `character(15)` | YES | None |
| `email` | `text` | YES | None |
| `payment_terms_days` | `smallint` | NO | `30` |
| `status` | `text` | NO | `'UNVERIFIED'::text` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `category` | `character varying(100)` | YES | None |
| `bank_account` | `text` | YES | None |
| `bank_ifsc` | `text` | YES | None |
| `bank_verified` | `boolean` | NO | `false` |
| `pan` | `text` | YES | None |
| `vendor_category_id` | `uuid` | YES | None |
| `bank_name` | `text` | YES | None |
| `brand_id` | `uuid` | YES | None |
| `pan_dup_deferred` | `boolean` | NO | `false` |
| `legal_name` | `text` | YES | None |

### Keys and Constraints

- `dim_suppliers_pkey` - `PRIMARY KEY (supplier_id)`
- `dim_suppliers_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `dim_suppliers_tenant_id_source_source_supplier_id_key` - `UNIQUE (tenant_id, source, source_supplier_id)`
- `dim_suppliers_vendor_category_id_fkey` - `FOREIGN KEY (vendor_category_id) REFERENCES dim_vendor_categories(category_id)`

### Indexes

- `dim_suppliers_pkey` - `CREATE UNIQUE INDEX dim_suppliers_pkey ON public.dim_suppliers USING btree (supplier_id)`
- `dim_suppliers_tenant_id_source_source_supplier_id_key` - `CREATE UNIQUE INDEX dim_suppliers_tenant_id_source_source_supplier_id_key ON public.dim_suppliers USING btree (tenant_id, source, source_supplier_id)`
- `idx_dim_suppliers_gstn` - `CREATE INDEX idx_dim_suppliers_gstn ON public.dim_suppliers USING btree (gstn) WHERE (gstn IS NOT NULL)`
- `idx_dim_suppliers_name_trgm` - `CREATE INDEX idx_dim_suppliers_name_trgm ON public.dim_suppliers USING gin (name gin_trgm_ops)`
- `idx_dim_suppliers_tenant` - `CREATE INDEX idx_dim_suppliers_tenant ON public.dim_suppliers USING btree (tenant_id)`

---

## Table: `dim_tax_rates`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tax_rate_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | `'TALLY'::data_source` |
| `tax_name` | `text` | NO | None |
| `tax_type` | `tax_type` | NO | None |
| `rate_percent` | `numeric(5,2)` | NO | None |
| `effective_from` | `date` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_tax_rates_pkey` - `PRIMARY KEY (tax_rate_id)`
- `dim_tax_rates_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `dim_tax_rates_pkey` - `CREATE UNIQUE INDEX dim_tax_rates_pkey ON public.dim_tax_rates USING btree (tax_rate_id)`

---

## Table: `dim_tds_mapping_rules`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `rule_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `priority` | `integer` | NO | None |
| `vendor_category_id` | `uuid` | YES | None |
| `additional_condition` | `jsonb` | YES | None |
| `tds_section_id` | `uuid` | NO | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `rate_override` | `numeric(6,3)` | YES | None |
| `description` | `text` | YES | None |

### Keys and Constraints

- `dim_tds_mapping_rules_pkey` - `PRIMARY KEY (rule_id)`
- `dim_tds_mapping_rules_tds_section_id_fkey` - `FOREIGN KEY (tds_section_id) REFERENCES dim_tds_sections(tds_section_id)`
- `dim_tds_mapping_rules_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `dim_tds_mapping_rules_tenant_id_priority_key` - `UNIQUE (tenant_id, priority)`
- `dim_tds_mapping_rules_vendor_category_id_fkey` - `FOREIGN KEY (vendor_category_id) REFERENCES dim_vendor_categories(category_id)`

### Indexes

- `dim_tds_mapping_rules_pkey` - `CREATE UNIQUE INDEX dim_tds_mapping_rules_pkey ON public.dim_tds_mapping_rules USING btree (rule_id)`
- `dim_tds_mapping_rules_tenant_id_priority_key` - `CREATE UNIQUE INDEX dim_tds_mapping_rules_tenant_id_priority_key ON public.dim_tds_mapping_rules USING btree (tenant_id, priority)`
- `idx_tds_mapping_tenant_pri` - `CREATE INDEX idx_tds_mapping_tenant_pri ON public.dim_tds_mapping_rules USING btree (tenant_id, priority) WHERE (is_active = true)`

---

## Table: `dim_tds_sections`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tds_section_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `return_code` | `text` | NO | None |
| `old_section_label` | `text` | YES | None |
| `new_section_label` | `text` | YES | None |
| `nature_of_payment` | `text` | NO | None |
| `side` | `text` | NO | `'AP'::text` |
| `default_rate` | `numeric(5,2)` | NO | None |
| `has_split_rate` | `boolean` | NO | `false` |
| `rate_individual_huf` | `numeric(5,2)` | YES | None |
| `rate_others` | `numeric(5,2)` | YES | None |
| `pan_missing_rate` | `numeric(5,2)` | NO | `20.0` |
| `threshold_type` | `text` | NO | `'NONE'::text` |
| `threshold_amount` | `numeric(14,2)` | YES | None |
| `threshold_amount_2` | `numeric(14,2)` | YES | None |
| `threshold_2_type` | `text` | YES | None |
| `base_calculation` | `text` | NO | `'TAXABLE'::text` |
| `effective_from` | `date` | YES | None |
| `effective_to` | `date` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `display_order` | `integer` | NO | `0` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `dim_tds_sections_pkey` - `PRIMARY KEY (tds_section_id)`
- `dim_tds_sections_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `dim_tds_sections_tenant_id_return_code_effective_from_key` - `UNIQUE (tenant_id, return_code, effective_from)`

### Indexes

- `dim_tds_sections_pkey` - `CREATE UNIQUE INDEX dim_tds_sections_pkey ON public.dim_tds_sections USING btree (tds_section_id)`
- `dim_tds_sections_tenant_id_return_code_effective_from_key` - `CREATE UNIQUE INDEX dim_tds_sections_tenant_id_return_code_effective_from_key ON public.dim_tds_sections USING btree (tenant_id, return_code, effective_from)`
- `idx_dim_tds_sections_tenant` - `CREATE INDEX idx_dim_tds_sections_tenant ON public.dim_tds_sections USING btree (tenant_id, is_active)`

---

## Table: `dim_tenants`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | `gen_random_uuid()` |
| `company_name` | `text` | NO | None |
| `gstn` | `character(15)` | YES | None |
| `plan_tier` | `text` | NO | `'free'::text` |
| `timezone` | `text` | NO | `'Asia/Kolkata'::text` |
| `region` | `text` | NO | `'ap-south-1'::text` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `settings_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `sap_matching_enabled` | `boolean` | NO | `false` |
| `pipeline_enabled` | `boolean` | NO | `true` |
| `onboarded_at` | `timestamp with time zone` | YES | None |
| `package_key` | `text` | YES | None |
| `legal_name` | `text` | YES | None |
| `primary_contact_email` | `text` | YES | None |
| `agent_daily_cap_usd` | `numeric(10,4)` | YES | None |

### Keys and Constraints

- `dim_tenants_gstn_key` - `UNIQUE (gstn)`
- `dim_tenants_pkey` - `PRIMARY KEY (tenant_id)`

### Indexes

- `dim_tenants_gstn_key` - `CREATE UNIQUE INDEX dim_tenants_gstn_key ON public.dim_tenants USING btree (gstn)`
- `dim_tenants_pkey` - `CREATE UNIQUE INDEX dim_tenants_pkey ON public.dim_tenants USING btree (tenant_id)`

---

## Table: `dim_vendor_categories`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `category_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `name` | `text` | NO | None |
| `allowed_entity_types` | `text[]` | NO | `'{INDIVIDUAL_HUF,OTHERS}'::text[]` |
| `display_order` | `integer` | NO | `0` |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `description` | `text` | YES | None |

### Keys and Constraints

- `dim_vendor_categories_pkey` - `PRIMARY KEY (category_id)`
- `dim_vendor_categories_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `dim_vendor_categories_tenant_id_name_key` - `UNIQUE (tenant_id, name)`

### Indexes

- `dim_vendor_categories_pkey` - `CREATE UNIQUE INDEX dim_vendor_categories_pkey ON public.dim_vendor_categories USING btree (category_id)`
- `dim_vendor_categories_tenant_id_name_key` - `CREATE UNIQUE INDEX dim_vendor_categories_tenant_id_name_key ON public.dim_vendor_categories USING btree (tenant_id, name)`
- `idx_dim_vendor_cat_tenant` - `CREATE INDEX idx_dim_vendor_cat_tenant ON public.dim_vendor_categories USING btree (tenant_id)`

---

## Table: `dim_vendor_tds_overrides`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `override_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `category_id` | `uuid` | YES | None |
| `entity_type` | `text` | NO | `'OTHERS'::text` |
| `override_section_id` | `uuid` | YES | None |
| `lower_cert_rate` | `numeric(5,2)` | YES | None |
| `lower_cert_number` | `text` | YES | None |
| `lower_cert_valid_from` | `date` | YES | None |
| `lower_cert_valid_to` | `date` | YES | None |
| `pan_verified` | `boolean` | NO | `false` |
| `notes` | `text` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `tds_mode` | `text` | NO | `'cumulative'::text` |
| `mode_set_by` | `uuid` | YES | None |
| `mode_set_on` | `timestamp with time zone` | YES | None |
| `mode_reason` | `text` | YES | None |
| `effective_from` | `date` | NO | `CURRENT_DATE` |
| `override_rate` | `numeric(6,3)` | YES | None |
| `certificate_no` | `text` | YES | None |
| `tds_section_id` | `uuid` | YES | None |

### Keys and Constraints

- `dim_vendor_tds_overrides_category_id_fkey` - `FOREIGN KEY (category_id) REFERENCES dim_vendor_categories(category_id)`
- `dim_vendor_tds_overrides_override_section_id_fkey` - `FOREIGN KEY (override_section_id) REFERENCES dim_tds_sections(tds_section_id)`
- `dim_vendor_tds_overrides_pkey` - `PRIMARY KEY (override_id)`
- `dim_vendor_tds_overrides_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id)`
- `dim_vendor_tds_overrides_tds_section_id_fkey` - `FOREIGN KEY (tds_section_id) REFERENCES dim_tds_sections(tds_section_id)`
- `dim_vendor_tds_overrides_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `dim_vendor_tds_overrides_tenant_id_supplier_id_key` - `UNIQUE (tenant_id, supplier_id)`

### Indexes

- `dim_vendor_tds_overrides_pkey` - `CREATE UNIQUE INDEX dim_vendor_tds_overrides_pkey ON public.dim_vendor_tds_overrides USING btree (override_id)`
- `dim_vendor_tds_overrides_tenant_id_supplier_id_key` - `CREATE UNIQUE INDEX dim_vendor_tds_overrides_tenant_id_supplier_id_key ON public.dim_vendor_tds_overrides USING btree (tenant_id, supplier_id)`
- `idx_vendor_tds_override_supplier` - `CREATE INDEX idx_vendor_tds_override_supplier ON public.dim_vendor_tds_overrides USING btree (tenant_id, supplier_id, is_active)`

---

## Table: `disbursement_gateway_calls`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `call_id` | `uuid` | NO | `gen_random_uuid()` |
| `disbursement_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `endpoint` | `text` | NO | None |
| `request_jsonb` | `jsonb` | NO | None |
| `response_jsonb` | `jsonb` | YES | None |
| `success` | `boolean` | YES | None |
| `error_message` | `text` | YES | None |
| `called_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `disbursement_gateway_calls_pkey` - `PRIMARY KEY (call_id)`

### Indexes

- `disbursement_gateway_calls_pkey` - `CREATE UNIQUE INDEX disbursement_gateway_calls_pkey ON public.disbursement_gateway_calls USING btree (call_id)`
- `idx_dgc_disbursement` - `CREATE INDEX idx_dgc_disbursement ON public.disbursement_gateway_calls USING btree (disbursement_id, called_at)`

---

## Table: `disbursement_overrides`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `override_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `invoice_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `overridden_by` | `text` | YES | None |
| `overridden_by_role` | `text` | YES | None |
| `reason` | `text` | NO | None |
| `original_account_number` | `text` | YES | None |
| `original_ifsc` | `text` | YES | None |
| `original_gstin_verified` | `boolean` | YES | None |
| `override_account_number` | `text` | NO | None |
| `override_ifsc` | `text` | NO | None |
| `override_beneficiary_name` | `text` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `disbursement_overrides_pkey` - `PRIMARY KEY (override_id)`

### Indexes

- `disbursement_overrides_pkey` - `CREATE UNIQUE INDEX disbursement_overrides_pkey ON public.disbursement_overrides USING btree (override_id)`
- `idx_dover_tenant_supplier` - `CREATE INDEX idx_dover_tenant_supplier ON public.disbursement_overrides USING btree (tenant_id, supplier_id)`

---

## Table: `fact_bills`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `bill_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `stg_bill_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `bill_number` | `text` | NO | None |
| `bill_date` | `date` | NO | None |
| `due_date` | `date` | YES | None |
| `fiscal_year` | `text` | NO | None |
| `fiscal_quarter` | `text` | NO | None |
| `fiscal_month` | `text` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `subtotal` | `numeric` | NO | `0` |
| `tax_amount` | `numeric` | NO | `0` |
| `total_amount` | `numeric` | NO | None |
| `amount_paid` | `numeric` | NO | `0` |
| `outstanding_amount` | `numeric` | YES | None |
| `status` | `invoice_status` | NO | `'DRAFT'::invoice_status` |
| `source` | `data_source` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `tds_section_code` | `text` | YES | None |
| `tds_rate_percent` | `numeric(5,2)` | YES | None |
| `tds_base_amount` | `numeric(14,2)` | YES | None |
| `tds_amount` | `numeric(14,2)` | YES | None |
| `net_payable` | `numeric(14,2)` | YES | None |
| `tds_status` | `text` | YES | `'PENDING'::text` |
| `tds_section_id` | `uuid` | YES | None |
| `tds_rate` | `numeric(6,3)` | YES | None |
| `original_amount` | `numeric(18,2)` | YES | None |
| `fx_rate_id` | `uuid` | YES | None |
| `inr_amount_current` | `numeric(18,2)` | YES | None |
| `fx_gain_loss` | `numeric(18,2)` | YES | None |
| `fx_actual_inr` | `numeric(18,2)` | YES | None |
| `fx_effective_rate` | `numeric(12,6)` | YES | None |
| `fx_realized_cost` | `numeric(18,2)` | YES | None |
| `fx_agent_note` | `text` | YES | None |
| `fx_agent_note_at` | `timestamp with time zone` | YES | None |
| `verification_flag` | `bill_verification_flag` | YES | None |
| `verification_detail` | `text` | YES | None |
| `verified_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `fact_bills_fx_rate_id_fkey` - `FOREIGN KEY (fx_rate_id) REFERENCES dim_fx_rates(rate_id)`
- `fact_bills_pkey` - `PRIMARY KEY (bill_id)`
- `fact_bills_stg_bill_fkey` - `FOREIGN KEY (stg_bill_id) REFERENCES stg_bills(stg_bill_id)`
- `fact_bills_stg_bill_id_key` - `UNIQUE (stg_bill_id)`
- `fact_bills_supplier_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id)`
- `fact_bills_tenant_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `fact_bills_pkey` - `CREATE UNIQUE INDEX fact_bills_pkey ON public.fact_bills USING btree (bill_id)`
- `fact_bills_stg_bill_id_key` - `CREATE UNIQUE INDEX fact_bills_stg_bill_id_key ON public.fact_bills USING btree (stg_bill_id)`
- `idx_fact_bills_status` - `CREATE INDEX idx_fact_bills_status ON public.fact_bills USING btree (tenant_id, status, due_date)`
- `idx_fact_bills_supplier` - `CREATE INDEX idx_fact_bills_supplier ON public.fact_bills USING btree (supplier_id)`
- `idx_fact_bills_tenant` - `CREATE INDEX idx_fact_bills_tenant ON public.fact_bills USING btree (tenant_id)`

---

## Table: `fact_cashflow_daily`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `cashflow_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `cashflow_date` | `date` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `inflows_actual` | `numeric(18,4)` | NO | `0` |
| `outflows_actual` | `numeric(18,4)` | NO | `0` |
| `net_cashflow` | `numeric(18,4)` | YES | None |
| `inflows_forecast` | `numeric(18,4)` | NO | `0` |
| `outflows_forecast` | `numeric(18,4)` | NO | `0` |
| `opening_balance` | `numeric(18,4)` | YES | None |
| `closing_balance` | `numeric(18,4)` | YES | None |
| `ar_outstanding` | `numeric(18,4)` | YES | None |
| `ap_outstanding` | `numeric(18,4)` | YES | None |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `invoice_id` | `uuid` | YES | None |

### Keys and Constraints

- `fact_cashflow_daily_invoice_id_fkey` - `FOREIGN KEY (invoice_id) REFERENCES fact_invoices(invoice_id)`
- `fact_cashflow_daily_pkey` - `PRIMARY KEY (cashflow_id)`
- `fact_cashflow_daily_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `fact_cashflow_daily_pkey` - `CREATE UNIQUE INDEX fact_cashflow_daily_pkey ON public.fact_cashflow_daily USING btree (cashflow_id)`
- `uq_cashflow_date_idx` - `CREATE INDEX uq_cashflow_date_idx ON public.fact_cashflow_daily USING btree (tenant_id, cashflow_date)`
- `uq_cashflow_invoice` - `CREATE UNIQUE INDEX uq_cashflow_invoice ON public.fact_cashflow_daily USING btree (tenant_id, invoice_id)`

---

## Table: `fact_disbursements`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `disbursement_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `invoice_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `amount` | `numeric` | NO | None |
| `beneficiary_name` | `text` | NO | None |
| `beneficiary_account` | `text` | NO | None |
| `beneficiary_ifsc` | `text` | NO | None |
| `beneficiary_mobile` | `text` | YES | None |
| `remitter_account_number` | `text` | NO | None |
| `bank_provider` | `text` | NO | `'ICICI'::text` |
| `tran_ref_no` | `text` | NO | None |
| `bank_tran_ref_no` | `text` | YES | None |
| `bank_rrn` | `text` | YES | None |
| `status` | `text` | NO | `'PENDING_OTP'::text` |
| `status_message` | `text` | YES | None |
| `act_code` | `text` | YES | None |
| `otp_code_hash` | `text` | YES | None |
| `otp_expires_at` | `double precision` | YES | None |
| `otp_verified_at` | `timestamp with time zone` | YES | None |
| `otp_attempts` | `integer` | NO | `0` |
| `initiated_by` | `text` | YES | None |
| `raw_response_jsonb` | `jsonb` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `is_overridden` | `boolean` | NO | `false` |
| `override_id` | `uuid` | YES | None |
| `nbfc_name` | `text` | YES | None |
| `updated_by` | `text` | YES | None |
| `receipt_email_status` | `text` | YES | None |
| `receipt_emailed_at` | `timestamp with time zone` | YES | None |
| `receipt_email_error` | `text` | YES | None |

### Keys and Constraints

- `fact_disbursements_pkey` - `PRIMARY KEY (disbursement_id)`
- `fact_disbursements_tenant_id_tran_ref_no_key` - `UNIQUE (tenant_id, tran_ref_no)`

### Indexes

- `fact_disbursements_pkey` - `CREATE UNIQUE INDEX fact_disbursements_pkey ON public.fact_disbursements USING btree (disbursement_id)`
- `fact_disbursements_tenant_id_tran_ref_no_key` - `CREATE UNIQUE INDEX fact_disbursements_tenant_id_tran_ref_no_key ON public.fact_disbursements USING btree (tenant_id, tran_ref_no)`
- `idx_fdis_tenant_invoice` - `CREATE INDEX idx_fdis_tenant_invoice ON public.fact_disbursements USING btree (tenant_id, invoice_id)`
- `idx_fdis_tenant_status` - `CREATE INDEX idx_fdis_tenant_status ON public.fact_disbursements USING btree (tenant_id, status)`

---

## Table: `fact_graph_edges`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `edge_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `src_node_id` | `uuid` | NO | None |
| `dst_node_id` | `uuid` | NO | None |
| `relation` | `text` | NO | None |
| `weight` | `double precision` | NO | `1.0` |
| `properties` | `jsonb` | NO | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `fact_graph_edges_dst_node_id_fkey` - `FOREIGN KEY (dst_node_id) REFERENCES fact_graph_nodes(node_id) ON DELETE CASCADE`
- `fact_graph_edges_pkey` - `PRIMARY KEY (edge_id)`
- `fact_graph_edges_src_node_id_fkey` - `FOREIGN KEY (src_node_id) REFERENCES fact_graph_nodes(node_id) ON DELETE CASCADE`

### Indexes

- `fact_graph_edges_pkey` - `CREATE UNIQUE INDEX fact_graph_edges_pkey ON public.fact_graph_edges USING btree (edge_id)`
- `idx_fge_tenant_dst` - `CREATE INDEX idx_fge_tenant_dst ON public.fact_graph_edges USING btree (tenant_id, dst_node_id)`
- `idx_fge_tenant_src` - `CREATE INDEX idx_fge_tenant_src ON public.fact_graph_edges USING btree (tenant_id, src_node_id)`
- `uq_fge_triple` - `CREATE UNIQUE INDEX uq_fge_triple ON public.fact_graph_edges USING btree (tenant_id, src_node_id, dst_node_id, relation)`

---

## Table: `fact_graph_nodes`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `node_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `node_type` | `text` | NO | None |
| `ref_id` | `uuid` | YES | None |
| `label` | `text` | NO | None |
| `properties` | `jsonb` | NO | `'{}'::jsonb` |
| `embedding` | `vector(1536)` | YES | None |
| `content_hash` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `fact_graph_nodes_pkey` - `PRIMARY KEY (node_id)`

### Indexes

- `fact_graph_nodes_pkey` - `CREATE UNIQUE INDEX fact_graph_nodes_pkey ON public.fact_graph_nodes USING btree (node_id)`
- `idx_fgn_embedding_hnsw` - `CREATE INDEX idx_fgn_embedding_hnsw ON public.fact_graph_nodes USING hnsw (embedding vector_cosine_ops)`
- `idx_fgn_tenant_type` - `CREATE INDEX idx_fgn_tenant_type ON public.fact_graph_nodes USING btree (tenant_id, node_type)`
- `uq_fgn_entity` - `CREATE UNIQUE INDEX uq_fgn_entity ON public.fact_graph_nodes USING btree (tenant_id, node_type, ref_id) WHERE (ref_id IS NOT NULL)`
- `uq_fgn_fact` - `CREATE UNIQUE INDEX uq_fgn_fact ON public.fact_graph_nodes USING btree (tenant_id, node_type, content_hash) WHERE ((ref_id IS NULL) AND (content_hash IS NOT NULL))`

---

## Table: `fact_invoices`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `invoice_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `stg_invoice_id` | `uuid` | YES | None |
| `end_customer_id` | `uuid` | YES | None |
| `account_id` | `uuid` | YES | None |
| `invoice_number` | `text` | NO | None |
| `invoice_date` | `date` | NO | None |
| `due_date` | `date` | YES | None |
| `fiscal_year` | `smallint` | NO | None |
| `fiscal_quarter` | `smallint` | NO | None |
| `fiscal_month` | `smallint` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `subtotal` | `numeric(18,4)` | NO | None |
| `tax_amount` | `numeric(18,4)` | NO | `0` |
| `total_amount` | `numeric(18,4)` | NO | None |
| `amount_paid` | `numeric(18,4)` | NO | `0` |
| `outstanding_amount` | `numeric(18,4)` | YES | None |
| `status` | `invoice_status` | NO | None |
| `risk_bucket` | `risk_bucket` | YES | None |
| `dso_contribution` | `numeric(10,4)` | YES | None |
| `source` | `data_source` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `invoice_type` | `text` | NO | `'AR'::text` |
| `stg_bill_id` | `uuid` | YES | None |
| `supplier_id` | `uuid` | YES | None |
| `upload_id` | `uuid` | YES | None |
| `transaction_type` | `text` | YES | `GENERATED ALWAYS AS (
CASE invoice_type
    WHEN 'AR'::text THEN 'Receivable'::text
    WHEN 'AP'::text THEN 'Payable'::text
    ELSE NULL::text
END) STORED` |
| `category` | `character varying(100)` | YES | None |
| `payment_status` | `character varying(20)` | YES | `'unpaid'::character varying` |
| `tally_push_pending` | `boolean` | NO | `false` |
| `manual_priority` | `character varying(4)` | YES | `NULL::character varying` |
| `department` | `character varying(100)` | YES | None |
| `brand_id` | `uuid` | YES | None |
| `soft_status` | `character varying(20)` | NO | `'active'::character varying` |
| `archived_stg_bill_id` | `uuid` | YES | None |
| `original_amount` | `numeric(18,2)` | YES | None |
| `fx_rate_id` | `uuid` | YES | None |
| `inr_amount_current` | `numeric(18,2)` | YES | None |
| `fx_gain_loss` | `numeric(18,2)` | YES | None |
| `fx_actual_inr` | `numeric(18,2)` | YES | None |
| `fx_effective_rate` | `numeric(12,6)` | YES | None |
| `fx_realized_cost` | `numeric(18,2)` | YES | None |
| `verification_flag` | `bill_verification_flag` | YES | None |
| `verification_detail` | `text` | YES | None |
| `verified_at` | `timestamp with time zone` | YES | None |
| `cost_center_id` | `uuid` | YES | None |

### Keys and Constraints

- `fact_invoices_account_id_fkey` - `FOREIGN KEY (account_id) REFERENCES dim_ledger_accounts(account_id) ON DELETE SET NULL`
- `fact_invoices_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `fact_invoices_fx_rate_id_fkey` - `FOREIGN KEY (fx_rate_id) REFERENCES dim_fx_rates(rate_id)`
- `fact_invoices_pkey` - `PRIMARY KEY (invoice_id)`
- `fact_invoices_stg_bill_id_fkey` - `FOREIGN KEY (stg_bill_id) REFERENCES stg_bills(stg_bill_id)`
- `fact_invoices_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE RESTRICT`
- `fact_invoices_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id)`
- `fact_invoices_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `fact_invoices_upload_id_fkey` - `FOREIGN KEY (upload_id) REFERENCES raw_invoice_uploads(upload_id)`
- `uq_fact_invoice_stg` - `UNIQUE (stg_invoice_id)`

### Indexes

- `fact_invoices_ap_bill_uniq` - `CREATE UNIQUE INDEX fact_invoices_ap_bill_uniq ON public.fact_invoices USING btree (tenant_id, stg_bill_id) WHERE (stg_bill_id IS NOT NULL)`
- `fact_invoices_pkey` - `CREATE UNIQUE INDEX fact_invoices_pkey ON public.fact_invoices USING btree (invoice_id)`
- `idx_fact_inv_customer` - `CREATE INDEX idx_fact_inv_customer ON public.fact_invoices USING btree (end_customer_id)`
- `idx_fact_inv_due` - `CREATE INDEX idx_fact_inv_due ON public.fact_invoices USING btree (due_date)`
- `idx_fact_inv_fiscal` - `CREATE INDEX idx_fact_inv_fiscal ON public.fact_invoices USING btree (tenant_id, fiscal_year, fiscal_quarter)`
- `idx_fact_inv_risk` - `CREATE INDEX idx_fact_inv_risk ON public.fact_invoices USING btree (risk_bucket)`
- `idx_fact_inv_status` - `CREATE INDEX idx_fact_inv_status ON public.fact_invoices USING btree (status)`
- `idx_fi_invoice_number` - `CREATE INDEX idx_fi_invoice_number ON public.fact_invoices USING btree (tenant_id, invoice_number)`
- `idx_fi_soft_status` - `CREATE INDEX idx_fi_soft_status ON public.fact_invoices USING btree (tenant_id, soft_status)`
- `idx_fi_tenant_created` - `CREATE INDEX idx_fi_tenant_created ON public.fact_invoices USING btree (tenant_id, created_at DESC)`
- `idx_fi_tenant_status` - `CREATE INDEX idx_fi_tenant_status ON public.fact_invoices USING btree (tenant_id, status)`
- `idx_fi_tenant_supplier` - `CREATE INDEX idx_fi_tenant_supplier ON public.fact_invoices USING btree (tenant_id, supplier_id)`
- `uq_fact_invoice_stg` - `CREATE UNIQUE INDEX uq_fact_invoice_stg ON public.fact_invoices USING btree (stg_invoice_id)`

---

## Table: `fact_payments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `payment_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `stg_payment_id` | `uuid` | NO | None |
| `invoice_id` | `uuid` | YES | None |
| `end_customer_id` | `uuid` | NO | None |
| `bank_account_id` | `uuid` | YES | None |
| `payment_date` | `date` | NO | None |
| `fiscal_year` | `smallint` | NO | None |
| `fiscal_quarter` | `smallint` | NO | None |
| `amount` | `numeric(18,4)` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `payment_method` | `payment_method` | YES | None |
| `transaction_ref` | `text` | YES | None |
| `gateway` | `text` | YES | None |
| `status` | `payment_status` | NO | None |
| `source` | `data_source` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `fact_payments_bank_account_id_fkey` - `FOREIGN KEY (bank_account_id) REFERENCES dim_bank_accounts(bank_account_id) ON DELETE SET NULL`
- `fact_payments_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `fact_payments_invoice_id_fkey` - `FOREIGN KEY (invoice_id) REFERENCES fact_invoices(invoice_id) ON DELETE SET NULL`
- `fact_payments_pkey` - `PRIMARY KEY (payment_id)`
- `fact_payments_stg_payment_id_fkey` - `FOREIGN KEY (stg_payment_id) REFERENCES stg_payments(stg_payment_id) ON DELETE RESTRICT`
- `fact_payments_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `uq_fact_payment_stg` - `UNIQUE (stg_payment_id)`

### Indexes

- `fact_payments_pkey` - `CREATE UNIQUE INDEX fact_payments_pkey ON public.fact_payments USING btree (payment_id)`
- `uq_fact_payment_stg` - `CREATE UNIQUE INDEX uq_fact_payment_stg ON public.fact_payments USING btree (stg_payment_id)`

---

## Table: `fact_tds_ledger`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `ledger_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `fiscal_year` | `text` | NO | None |
| `tds_section_code` | `text` | NO | None |
| `ytd_base_amount` | `numeric(14,2)` | NO | `0` |
| `ytd_tds_deducted` | `numeric(14,2)` | NO | `0` |
| `txn_count` | `integer` | NO | `0` |
| `threshold_crossed` | `boolean` | NO | `false` |
| `last_updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `fact_tds_ledger_pkey` - `PRIMARY KEY (ledger_id)`
- `fact_tds_ledger_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id)`
- `fact_tds_ledger_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `fact_tds_ledger_tenant_id_supplier_id_fiscal_year_tds_secti_key` - `UNIQUE (tenant_id, supplier_id, fiscal_year, tds_section_code)`

### Indexes

- `fact_tds_ledger_pkey` - `CREATE UNIQUE INDEX fact_tds_ledger_pkey ON public.fact_tds_ledger USING btree (ledger_id)`
- `fact_tds_ledger_tenant_id_supplier_id_fiscal_year_tds_secti_key` - `CREATE UNIQUE INDEX fact_tds_ledger_tenant_id_supplier_id_fiscal_year_tds_secti_key ON public.fact_tds_ledger USING btree (tenant_id, supplier_id, fiscal_year, tds_section_code)`

---

## Table: `fx_agent_notes`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `note_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `target_type` | `text` | NO | None |
| `target_id` | `uuid` | YES | None |
| `currency_code` | `character(3)` | NO | None |
| `severity` | `text` | NO | None |
| `note_text` | `text` | NO | None |
| `confidence` | `numeric(3,2)` | YES | None |
| `context_snapshot` | `jsonb` | YES | None |
| `rate_at_generation` | `numeric(12,6)` | YES | None |
| `is_current` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `fx_agent_notes_pkey` - `PRIMARY KEY (note_id)`
- `fx_agent_notes_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `fx_agent_notes_pkey` - `CREATE UNIQUE INDEX fx_agent_notes_pkey ON public.fx_agent_notes USING btree (note_id)`
- `idx_fx_notes_target` - `CREATE INDEX idx_fx_notes_target ON public.fx_agent_notes USING btree (target_type, target_id, is_current) WHERE (is_current = true)`
- `idx_fx_notes_tenant` - `CREATE INDEX idx_fx_notes_tenant ON public.fx_agent_notes USING btree (tenant_id, target_type, created_at DESC)`

---

## Table: `fx_bill_payments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `payment_id` | `uuid` | NO | `gen_random_uuid()` |
| `invoice_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `payment_date` | `date` | NO | None |
| `foreign_amount` | `numeric(18,2)` | NO | None |
| `actual_inr` | `numeric(18,2)` | NO | None |
| `effective_rate` | `numeric(12,6)` | NO | None |
| `rbi_rate` | `numeric(12,6)` | YES | None |
| `bank_spread` | `numeric(8,6)` | YES | None |
| `bank_spread_pct` | `numeric(5,2)` | YES | None |
| `reference_no` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `currency_code` | `character(3)` | YES | None |
| `bank_name` | `text` | YES | None |
| `notes` | `text` | YES | None |

### Keys and Constraints

- `fx_bill_payments_actual_inr_check` - `CHECK ((actual_inr > (0)::numeric))`
- `fx_bill_payments_foreign_amount_check` - `CHECK ((foreign_amount > (0)::numeric))`
- `fx_bill_payments_pkey` - `PRIMARY KEY (payment_id)`
- `fx_bill_payments_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `fx_bill_payments_pkey` - `CREATE UNIQUE INDEX fx_bill_payments_pkey ON public.fx_bill_payments USING btree (payment_id)`
- `idx_fx_payments_bill` - `CREATE INDEX idx_fx_payments_bill ON public.fx_bill_payments USING btree (invoice_id)`
- `idx_fx_payments_tenant` - `CREATE INDEX idx_fx_payments_tenant ON public.fx_bill_payments USING btree (tenant_id, payment_date DESC)`

---

## Table: `fx_rate_alerts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `alert_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `alert_type` | `text` | NO | None |
| `currency_code` | `character(3)` | NO | `'USD'::bpchar` |
| `rate_date` | `date` | NO | None |
| `rate_inr` | `numeric(12,6)` | NO | None |
| `threshold_inr` | `numeric(12,6)` | YES | None |
| `direction` | `text` | YES | None |
| `recommendation` | `text` | NO | None |
| `affected_bill_ids` | `uuid[]` | YES | None |
| `affected_invoice_ids` | `uuid[]` | YES | None |
| `exposure_foreign` | `numeric(18,2)` | YES | None |
| `exposure_inr` | `numeric(18,2)` | YES | None |
| `status` | `text` | NO | `'ACTIVE'::text` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `dismissed_at` | `timestamp with time zone` | YES | None |
| `dismissed_by` | `text` | YES | None |

### Keys and Constraints

- `fx_rate_alerts_pkey` - `PRIMARY KEY (alert_id)`
- `fx_rate_alerts_tenant_id_alert_type_currency_code_rate_date_key` - `UNIQUE (tenant_id, alert_type, currency_code, rate_date)`
- `fx_rate_alerts_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `fx_rate_alerts_pkey` - `CREATE UNIQUE INDEX fx_rate_alerts_pkey ON public.fx_rate_alerts USING btree (alert_id)`
- `fx_rate_alerts_tenant_id_alert_type_currency_code_rate_date_key` - `CREATE UNIQUE INDEX fx_rate_alerts_tenant_id_alert_type_currency_code_rate_date_key ON public.fx_rate_alerts USING btree (tenant_id, alert_type, currency_code, rate_date)`
- `idx_fx_alerts_active` - `CREATE INDEX idx_fx_alerts_active ON public.fx_rate_alerts USING btree (tenant_id, status, created_at DESC)`

---

## Table: `int_conflict_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `conflict_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `connection_id` | `uuid` | YES | None |
| `source` | `data_source` | NO | None |
| `entity_type` | `text` | NO | None |
| `source_entity_id` | `text` | NO | None |
| `db_timestamp` | `timestamp with time zone` | NO | None |
| `event_timestamp` | `timestamp with time zone` | NO | None |
| `resolution` | `conflict_resolution` | NO | None |
| `db_payload` | `jsonb` | YES | None |
| `event_payload` | `jsonb` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `int_conflict_log_connection_id_fkey` - `FOREIGN KEY (connection_id) REFERENCES int_connections(connection_id)`
- `int_conflict_log_pkey` - `PRIMARY KEY (conflict_id)`
- `int_conflict_log_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_int_conflict_log_tenant` - `CREATE INDEX idx_int_conflict_log_tenant ON public.int_conflict_log USING btree (tenant_id, created_at DESC)`
- `int_conflict_log_pkey` - `CREATE UNIQUE INDEX int_conflict_log_pkey ON public.int_conflict_log USING btree (conflict_id)`

---

## Table: `int_connections`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `connection_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `apideck_consumer_id` | `text` | YES | None |
| `apideck_service_id` | `text` | YES | None |
| `tally_agent_id` | `uuid` | YES | None |
| `tally_company_id` | `text` | YES | None |
| `tally_mode` | `tally_mode` | YES | None |
| `status` | `connection_status` | NO | `'DISCONNECTED'::connection_status` |
| `last_sync_at` | `timestamp with time zone` | YES | None |
| `last_cursor` | `text` | YES | None |
| `error_message` | `text` | YES | None |
| `consecutive_failures` | `smallint` | NO | `0` |
| `sync_config_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `agent_api_key_hash` | `text` | YES | None |
| `agent_pairing_token` | `text` | YES | None |
| `agent_pairing_expires_at` | `timestamp with time zone` | YES | None |
| `agent_version` | `text` | YES | None |

### Keys and Constraints

- `int_connections_pkey` - `PRIMARY KEY (connection_id)`
- `int_connections_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `int_connections_tenant_id_source_key` - `UNIQUE (tenant_id, source)`

### Indexes

- `idx_int_conn_tenant` - `CREATE INDEX idx_int_conn_tenant ON public.int_connections USING btree (tenant_id)`
- `idx_int_connections_active` - `CREATE INDEX idx_int_connections_active ON public.int_connections USING btree (tenant_id, status)`
- `idx_int_connections_agent_api_key_hash` - `CREATE INDEX idx_int_connections_agent_api_key_hash ON public.int_connections USING btree (agent_api_key_hash) WHERE (agent_api_key_hash IS NOT NULL)`
- `int_connections_pkey` - `CREATE UNIQUE INDEX int_connections_pkey ON public.int_connections USING btree (connection_id)`
- `int_connections_tenant_id_source_key` - `CREATE UNIQUE INDEX int_connections_tenant_id_source_key ON public.int_connections USING btree (tenant_id, source)`

---

## Table: `int_connector_limits`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `connector` | `text` | NO | None |
| `per_minute_limit` | `integer` | YES | None |
| `per_day_limit` | `integer` | YES | None |
| `concurrency_limit` | `integer` | YES | `4` |
| `safety_margin_pct` | `numeric(4,2)` | NO | `15.0` |
| `retry_after_default_s` | `integer` | NO | `60` |
| `notes` | `text` | YES | None |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `int_connector_limits_pkey` - `PRIMARY KEY (connector)`

### Indexes

- `int_connector_limits_pkey` - `CREATE UNIQUE INDEX int_connector_limits_pkey ON public.int_connector_limits USING btree (connector)`

---

## Table: `int_field_mappings`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `mapping_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_table` | `text` | NO | None |
| `source_field` | `text` | NO | None |
| `target_table` | `text` | NO | None |
| `target_field` | `text` | NO | None |
| `transform_fn` | `text` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `int_field_mappings_pkey` - `PRIMARY KEY (mapping_id)`
- `int_field_mappings_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `int_field_mappings_pkey` - `CREATE UNIQUE INDEX int_field_mappings_pkey ON public.int_field_mappings USING btree (mapping_id)`

---

## Table: `int_nova_credentials`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `credential_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `brand` | `text` | YES | None |
| `api_key_encrypted` | `text` | NO | None |
| `base_url` | `text` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `int_nova_credentials_pkey` - `PRIMARY KEY (credential_id)`

### Indexes

- `int_nova_credentials_brand_uq` - `CREATE UNIQUE INDEX int_nova_credentials_brand_uq ON public.int_nova_credentials USING btree (tenant_id, brand) WHERE (brand IS NOT NULL)`
- `int_nova_credentials_default_uq` - `CREATE UNIQUE INDEX int_nova_credentials_default_uq ON public.int_nova_credentials USING btree (tenant_id) WHERE (brand IS NULL)`
- `int_nova_credentials_pkey` - `CREATE UNIQUE INDEX int_nova_credentials_pkey ON public.int_nova_credentials USING btree (credential_id)`

---

## Table: `int_sync_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `log_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `connection_id` | `uuid` | YES | None |
| `job_id` | `text` | YES | None |
| `source` | `data_source` | NO | None |
| `entity_type` | `text` | YES | None |
| `started_at` | `timestamp with time zone` | NO | None |
| `completed_at` | `timestamp with time zone` | YES | None |
| `records_fetched` | `integer` | NO | `0` |
| `records_inserted` | `integer` | NO | `0` |
| `records_updated` | `integer` | NO | `0` |
| `records_errored` | `integer` | NO | `0` |
| `status` | `sync_job_status` | NO | `'RUNNING'::sync_job_status` |
| `last_cursor` | `text` | YES | None |
| `error_message` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `int_sync_log_connection_id_fkey` - `FOREIGN KEY (connection_id) REFERENCES int_connections(connection_id)`
- `int_sync_log_pkey` - `PRIMARY KEY (log_id)`
- `int_sync_log_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_int_sync_log_tenant` - `CREATE INDEX idx_int_sync_log_tenant ON public.int_sync_log USING btree (tenant_id, created_at DESC)`
- `idx_int_sync_tenant` - `CREATE INDEX idx_int_sync_tenant ON public.int_sync_log USING btree (tenant_id)`
- `int_sync_log_pkey` - `CREATE UNIQUE INDEX int_sync_log_pkey ON public.int_sync_log USING btree (log_id)`

---

## Table: `ledger_mapping_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `hsn_code` | `text` | YES | None |
| `description` | `text` | YES | None |
| `account_id` | `uuid` | NO | None |
| `source` | `text` | NO | `'user'::text` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `ledger_mapping_log_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_lml_tenant_hsn` - `CREATE INDEX idx_lml_tenant_hsn ON public.ledger_mapping_log USING btree (tenant_id, hsn_code)`
- `idx_lml_tenant_supplier` - `CREATE INDEX idx_lml_tenant_supplier ON public.ledger_mapping_log USING btree (tenant_id, supplier_id)`
- `ledger_mapping_log_pkey` - `CREATE UNIQUE INDEX ledger_mapping_log_pkey ON public.ledger_mapping_log USING btree (id)`

---

## Table: `mapping_review_queue`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `review_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `line_item_id` | `uuid` | NO | None |
| `line_item_kind` | `text` | NO | None |
| `query_text` | `text` | NO | None |
| `candidates` | `jsonb` | NO | None |
| `status` | `text` | NO | `'PENDING'::text` |
| `chosen_item_code` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `resolved_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `mapping_review_queue_pkey` - `PRIMARY KEY (review_id)`
- `mapping_review_queue_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `idx_mapping_review_status` - `CREATE INDEX idx_mapping_review_status ON public.mapping_review_queue USING btree (tenant_id, status, created_at DESC)`
- `mapping_review_queue_pkey` - `CREATE UNIQUE INDEX mapping_review_queue_pkey ON public.mapping_review_queue USING btree (review_id)`

---

## Table: `nova_reconciliation_bill_queue`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `invoice_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `vendor` | `text` | NO | None |
| `status` | `text` | NO | `'PENDING'::text` |
| `run_id` | `uuid` | YES | None |
| `reason` | `text` | YES | None |
| `resolved_brand` | `text` | YES | None |
| `attempt_count` | `smallint` | NO | `0` |
| `last_attempted_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `nova_reconciliation_bill_queue_pkey` - `PRIMARY KEY (invoice_id)`

### Indexes

- `ix_nova_bill_queue_status` - `CREATE INDEX ix_nova_bill_queue_status ON public.nova_reconciliation_bill_queue USING btree (status)`
- `nova_reconciliation_bill_queue_pkey` - `CREATE UNIQUE INDEX nova_reconciliation_bill_queue_pkey ON public.nova_reconciliation_bill_queue USING btree (invoice_id)`

---

## Table: `nova_reconciliation_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `line_id` | `uuid` | NO | `gen_random_uuid()` |
| `run_id` | `uuid` | NO | None |
| `owner_tenant_id` | `uuid` | YES | None |
| `line_item_id` | `text` | YES | None |
| `cost_centre` | `text` | YES | None |
| `service_month` | `text` | YES | None |
| `module_slug` | `text` | YES | None |
| `invoice_description` | `text` | YES | None |
| `canonical_service` | `text` | YES | None |
| `scope` | `text` | YES | None |
| `certification_status` | `text` | NO | None |
| `match_status` | `text` | YES | None |
| `rate_status` | `text` | YES | None |
| `qty_status` | `text` | YES | None |
| `cost_status` | `text` | YES | None |
| `nova_self_consistent` | `boolean` | YES | None |
| `billed_rate` | `numeric` | YES | None |
| `expected_rate` | `numeric` | YES | None |
| `rate_variance_pct` | `numeric` | YES | None |
| `qty_variance_pct` | `numeric` | YES | None |
| `cost_variance_pct` | `numeric` | YES | None |
| `billable_operations` | `numeric` | YES | None |
| `api_call_count` | `numeric` | YES | None |
| `total_cost_rupees` | `numeric` | YES | None |
| `invoice_qty` | `numeric` | YES | None |
| `invoice_rate` | `numeric` | YES | None |
| `invoice_amount` | `numeric` | YES | None |
| `allowed_variance` | `numeric` | YES | None |
| `combined_brand_check` | `text` | YES | None |
| `cost_centre_attribution` | `text` | YES | None |

### Keys and Constraints

- `nova_reconciliation_lines_pkey` - `PRIMARY KEY (line_id)`
- `nova_reconciliation_lines_run_id_fkey` - `FOREIGN KEY (run_id) REFERENCES nova_reconciliation_runs(run_id) ON DELETE CASCADE`

### Indexes

- `nova_reconciliation_lines_owner_tenant_idx` - `CREATE INDEX nova_reconciliation_lines_owner_tenant_idx ON public.nova_reconciliation_lines USING btree (owner_tenant_id)`
- `nova_reconciliation_lines_pkey` - `CREATE UNIQUE INDEX nova_reconciliation_lines_pkey ON public.nova_reconciliation_lines USING btree (line_id)`
- `nova_reconciliation_lines_run_id_idx` - `CREATE INDEX nova_reconciliation_lines_run_id_idx ON public.nova_reconciliation_lines USING btree (run_id)`

---

## Table: `nova_reconciliation_module_aliases`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `alias_id` | `uuid` | NO | `gen_random_uuid()` |
| `vendor` | `text` | NO | None |
| `module_slug` | `text` | NO | None |
| `canonical_service` | `text` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `nova_reconciliation_module_aliases_pkey` - `PRIMARY KEY (alias_id)`
- `nova_reconciliation_module_aliases_vendor_slug_key` - `UNIQUE (vendor, module_slug)`

### Indexes

- `nova_reconciliation_module_aliases_pkey` - `CREATE UNIQUE INDEX nova_reconciliation_module_aliases_pkey ON public.nova_reconciliation_module_aliases USING btree (alias_id)`
- `nova_reconciliation_module_aliases_vendor_slug_key` - `CREATE UNIQUE INDEX nova_reconciliation_module_aliases_vendor_slug_key ON public.nova_reconciliation_module_aliases USING btree (vendor, module_slug)`

---

## Table: `nova_reconciliation_runs`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `run_id` | `uuid` | NO | `gen_random_uuid()` |
| `bill_id` | `text` | YES | None |
| `tenant_id` | `uuid` | NO | None |
| `brand_or_cost_centre` | `text` | NO | None |
| `cost_centre_id` | `uuid` | YES | None |
| `vendor` | `text` | NO | None |
| `billing_month` | `text` | NO | None |
| `nova_reference_id` | `text` | YES | None |
| `nova_response_jsonb` | `jsonb` | NO | None |
| `extended_nova_response_jsonb` | `jsonb` | YES | None |
| `rollup_status` | `text` | NO | None |
| `total_lines` | `integer` | NO | `0` |
| `certified_count` | `integer` | NO | `0` |
| `uncertified_count` | `integer` | NO | `0` |
| `ambiguous_count` | `integer` | NO | `0` |
| `unresolved_module_count` | `integer` | NO | `0` |
| `pending_extended_lookup_count` | `integer` | NO | `0` |
| `nova_logic_missing_count` | `integer` | NO | `0` |
| `rate_mismatch_count` | `integer` | NO | `0` |
| `qty_mismatch_count` | `integer` | NO | `0` |
| `cost_mismatch_count` | `integer` | NO | `0` |
| `missing_in_invoice_count` | `integer` | NO | `0` |
| `extra_in_invoice_count` | `integer` | NO | `0` |
| `self_inconsistent_count` | `integer` | NO | `0` |
| `total_cost_rupees` | `numeric` | NO | `0` |
| `total_invoice_amount` | `numeric` | NO | `0` |
| `variance_amount_rupees` | `numeric` | NO | `0` |
| `ingested_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `nova_reconciliation_runs_pkey` - `PRIMARY KEY (run_id)`

### Indexes

- `nova_reconciliation_runs_bill_id_idx` - `CREATE INDEX nova_reconciliation_runs_bill_id_idx ON public.nova_reconciliation_runs USING btree (bill_id)`
- `nova_reconciliation_runs_lookup_idx` - `CREATE INDEX nova_reconciliation_runs_lookup_idx ON public.nova_reconciliation_runs USING btree (tenant_id, vendor, billing_month, ingested_at DESC)`
- `nova_reconciliation_runs_pkey` - `CREATE UNIQUE INDEX nova_reconciliation_runs_pkey ON public.nova_reconciliation_runs USING btree (run_id)`

---

## Table: `org_user_access_levels`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `access_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `user_id` | `uuid` | NO | None |
| `access_level` | `text` | NO | None |
| `can_read` | `boolean` | NO | `false` |
| `can_edit` | `boolean` | NO | `false` |
| `can_approve_workflow` | `boolean` | NO | `false` |
| `can_export_data` | `boolean` | NO | `false` |
| `can_update` | `boolean` | NO | `false` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `org_user_access_levels_pkey` - `PRIMARY KEY (access_id)`
- `org_user_access_levels_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `org_user_access_levels_user_id_fkey` - `FOREIGN KEY (user_id) REFERENCES org_users(user_id) ON DELETE CASCADE`
- `uq_org_user_access` - `UNIQUE (tenant_id, user_id, access_level)`

### Indexes

- `org_user_access_levels_pkey` - `CREATE UNIQUE INDEX org_user_access_levels_pkey ON public.org_user_access_levels USING btree (access_id)`
- `uq_org_user_access` - `CREATE UNIQUE INDEX uq_org_user_access ON public.org_user_access_levels USING btree (tenant_id, user_id, access_level)`

---

## Table: `org_users`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `user_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `full_name` | `text` | NO | None |
| `work_email` | `text` | NO | None |
| `employee_id` | `text` | YES | None |
| `office_branch` | `text` | YES | None |
| `contact_number` | `text` | YES | None |
| `designation` | `text` | YES | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `org_users_pkey` - `PRIMARY KEY (user_id)`
- `org_users_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `uq_org_users_tenant_email` - `UNIQUE (tenant_id, work_email)`
- `uq_org_users_tenant_employee` - `UNIQUE (tenant_id, employee_id)`

### Indexes

- `org_users_pkey` - `CREATE UNIQUE INDEX org_users_pkey ON public.org_users USING btree (user_id)`
- `uq_org_users_tenant_email` - `CREATE UNIQUE INDEX uq_org_users_tenant_email ON public.org_users USING btree (tenant_id, work_email)`
- `uq_org_users_tenant_employee` - `CREATE UNIQUE INDEX uq_org_users_tenant_employee ON public.org_users USING btree (tenant_id, employee_id)`

---

## Table: `payment_schedules`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `schedule_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `cycle_type` | `payment_cycle_type` | NO | None |
| `stg_bill_id` | `uuid` | YES | None |
| `stg_invoice_id` | `uuid` | YES | None |
| `supplier_id` | `uuid` | YES | None |
| `end_customer_id` | `uuid` | YES | None |
| `installment_number` | `smallint` | NO | None |
| `due_date` | `date` | NO | None |
| `scheduled_amount` | `numeric(18,4)` | NO | None |
| `paid_amount` | `numeric(18,4)` | NO | `0` |
| `outstanding_amount` | `numeric(18,4)` | YES | None |
| `payment_term_days` | `smallint` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `status` | `schedule_status` | NO | `'PENDING'::schedule_status` |
| `notes` | `text` | YES | None |
| `reminder_sent_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `payment_schedules_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `payment_schedules_pkey` - `PRIMARY KEY (schedule_id)`
- `payment_schedules_stg_bill_id_fkey` - `FOREIGN KEY (stg_bill_id) REFERENCES stg_bills(stg_bill_id) ON DELETE RESTRICT`
- `payment_schedules_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE RESTRICT`
- `payment_schedules_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id) ON DELETE RESTRICT`
- `payment_schedules_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `idx_psched_bill` - `CREATE INDEX idx_psched_bill ON public.payment_schedules USING btree (stg_bill_id)`
- `idx_psched_customer` - `CREATE INDEX idx_psched_customer ON public.payment_schedules USING btree (end_customer_id)`
- `idx_psched_due` - `CREATE INDEX idx_psched_due ON public.payment_schedules USING btree (due_date)`
- `idx_psched_invoice` - `CREATE INDEX idx_psched_invoice ON public.payment_schedules USING btree (stg_invoice_id)`
- `idx_psched_status` - `CREATE INDEX idx_psched_status ON public.payment_schedules USING btree (status)`
- `idx_psched_supplier` - `CREATE INDEX idx_psched_supplier ON public.payment_schedules USING btree (supplier_id)`
- `idx_psched_tenant_cycle` - `CREATE INDEX idx_psched_tenant_cycle ON public.payment_schedules USING btree (tenant_id, cycle_type, status, due_date)`
- `payment_schedules_pkey` - `CREATE UNIQUE INDEX payment_schedules_pkey ON public.payment_schedules USING btree (schedule_id)`
- `uq_schedule_bill_installment` - `CREATE UNIQUE INDEX uq_schedule_bill_installment ON public.payment_schedules USING btree (stg_bill_id, installment_number) WHERE (stg_bill_id IS NOT NULL)`
- `uq_schedule_invoice_installment` - `CREATE UNIQUE INDEX uq_schedule_invoice_installment ON public.payment_schedules USING btree (stg_invoice_id, installment_number) WHERE (stg_invoice_id IS NOT NULL)`

---

## Table: `payment_transactions`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `txn_id` | `uuid` | NO | `gen_random_uuid()` |
| `schedule_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `cycle_type` | `payment_cycle_type` | NO | None |
| `paid_amount` | `numeric(18,4)` | NO | None |
| `payment_date` | `date` | NO | None |
| `value_date` | `date` | YES | None |
| `payment_mode` | `payment_method` | NO | None |
| `reference_number` | `character varying(100)` | YES | None |
| `bank_account_id` | `uuid` | YES | None |
| `status` | `txn_status` | NO | `'INITIATED'::txn_status` |
| `failure_reason` | `text` | YES | None |
| `notes` | `text` | YES | None |
| `recorded_by` | `uuid` | NO | None |
| `approved_by` | `uuid` | YES | None |
| `approved_at` | `timestamp with time zone` | YES | None |
| `is_reconciled` | `boolean` | NO | `false` |
| `stg_statement_id` | `uuid` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `payment_transactions_approved_by_fkey` - `FOREIGN KEY (approved_by) REFERENCES org_users(user_id) ON DELETE SET NULL`
- `payment_transactions_bank_account_id_fkey` - `FOREIGN KEY (bank_account_id) REFERENCES dim_bank_accounts(bank_account_id) ON DELETE SET NULL`
- `payment_transactions_pkey` - `PRIMARY KEY (txn_id)`
- `payment_transactions_recorded_by_fkey` - `FOREIGN KEY (recorded_by) REFERENCES org_users(user_id) ON DELETE RESTRICT`
- `payment_transactions_schedule_id_fkey` - `FOREIGN KEY (schedule_id) REFERENCES payment_schedules(schedule_id) ON DELETE RESTRICT`
- `payment_transactions_stg_statement_id_fkey` - `FOREIGN KEY (stg_statement_id) REFERENCES stg_bank_statements(stg_statement_id) ON DELETE SET NULL`
- `payment_transactions_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `idx_ptxn_cycle` - `CREATE INDEX idx_ptxn_cycle ON public.payment_transactions USING btree (cycle_type)`
- `idx_ptxn_date` - `CREATE INDEX idx_ptxn_date ON public.payment_transactions USING btree (payment_date)`
- `idx_ptxn_reconciled` - `CREATE INDEX idx_ptxn_reconciled ON public.payment_transactions USING btree (is_reconciled)`
- `idx_ptxn_ref` - `CREATE INDEX idx_ptxn_ref ON public.payment_transactions USING btree (reference_number)`
- `idx_ptxn_schedule` - `CREATE INDEX idx_ptxn_schedule ON public.payment_transactions USING btree (schedule_id)`
- `idx_ptxn_status` - `CREATE INDEX idx_ptxn_status ON public.payment_transactions USING btree (status)`
- `payment_transactions_pkey` - `CREATE UNIQUE INDEX payment_transactions_pkey ON public.payment_transactions USING btree (txn_id)`

---

## Table: `platform_impersonation`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `session_id` | `uuid` | NO | `gen_random_uuid()` |
| `platform_user_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `assumed_role` | `text` | NO | `'auditor'::text` |
| `reason` | `text` | NO | None |
| `read_only` | `boolean` | NO | `true` |
| `issued_at` | `timestamp with time zone` | NO | `now()` |
| `expires_at` | `timestamp with time zone` | NO | None |
| `revoked_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `platform_impersonation_pkey` - `PRIMARY KEY (session_id)`
- `platform_impersonation_platform_user_id_fkey` - `FOREIGN KEY (platform_user_id) REFERENCES platform_users(id)`
- `platform_impersonation_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `idx_impersonation_live` - `CREATE INDEX idx_impersonation_live ON public.platform_impersonation USING btree (expires_at) WHERE (revoked_at IS NULL)`
- `idx_impersonation_tenant` - `CREATE INDEX idx_impersonation_tenant ON public.platform_impersonation USING btree (tenant_id, issued_at DESC)`
- `platform_impersonation_pkey` - `CREATE UNIQUE INDEX platform_impersonation_pkey ON public.platform_impersonation USING btree (session_id)`

---

## Table: `platform_refresh_tokens`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `token_hash` | `text` | NO | None |
| `platform_user_id` | `uuid` | NO | None |
| `issued_at` | `timestamp with time zone` | NO | `now()` |
| `expires_at` | `timestamp with time zone` | NO | None |
| `revoked` | `boolean` | NO | `false` |
| `revoked_at` | `timestamp with time zone` | YES | None |
| `replaced_by` | `text` | YES | None |

### Keys and Constraints

- `platform_refresh_tokens_pkey` - `PRIMARY KEY (id)`
- `platform_refresh_tokens_platform_user_id_fkey` - `FOREIGN KEY (platform_user_id) REFERENCES platform_users(id) ON DELETE CASCADE`
- `platform_refresh_tokens_token_hash_key` - `UNIQUE (token_hash)`

### Indexes

- `idx_platform_refresh_user` - `CREATE INDEX idx_platform_refresh_user ON public.platform_refresh_tokens USING btree (platform_user_id) WHERE (NOT revoked)`
- `platform_refresh_tokens_pkey` - `CREATE UNIQUE INDEX platform_refresh_tokens_pkey ON public.platform_refresh_tokens USING btree (id)`
- `platform_refresh_tokens_token_hash_key` - `CREATE UNIQUE INDEX platform_refresh_tokens_token_hash_key ON public.platform_refresh_tokens USING btree (token_hash)`

---

## Table: `platform_users`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `email` | `text` | NO | None |
| `password_hash` | `text` | NO | None |
| `name` | `text` | NO | None |
| `role` | `text` | NO | `'support'::text` |
| `is_active` | `boolean` | NO | `true` |
| `last_login_at` | `timestamp with time zone` | YES | None |
| `failed_logins` | `integer` | NO | `0` |
| `locked_until` | `timestamp with time zone` | YES | None |
| `created_by` | `uuid` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `platform_users_pkey` - `PRIMARY KEY (id)`
- `platform_users_role_chk` - `CHECK ((role = ANY (ARRAY['owner'::text, 'admin'::text, 'support'::text, 'readonly'::text])))`

### Indexes

- `platform_users_pkey` - `CREATE UNIQUE INDEX platform_users_pkey ON public.platform_users USING btree (id)`
- `uq_platform_users_email` - `CREATE UNIQUE INDEX uq_platform_users_email ON public.platform_users USING btree (lower(email))`

---

## Table: `poc_email_messages`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `message_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | YES | None |
| `contact_id` | `uuid` | YES | None |
| `direction` | `text` | NO | None |
| `gmail_msg_id` | `text` | YES | None |
| `thread_id` | `text` | YES | None |
| `from_email` | `text` | YES | None |
| `to_email` | `text` | YES | None |
| `subject` | `text` | YES | None |
| `body` | `text` | YES | None |
| `sent_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `embedded_at` | `timestamp with time zone` | YES | None |
| `claims_status` | `text` | NO | `'PENDING'::text` |
| `claims_error` | `text` | YES | None |

### Keys and Constraints

- `poc_email_messages_claims_status_check` - `CHECK ((claims_status = ANY (ARRAY['PENDING'::text, 'RUNNING'::text, 'DONE'::text, 'SKIPPED'::text, 'FAILED'::text])))`
- `poc_email_messages_pkey` - `PRIMARY KEY (message_id)`

### Indexes

- `idx_pem_claims_pending` - `CREATE INDEX idx_pem_claims_pending ON public.poc_email_messages USING btree (tenant_id, created_at) WHERE ((claims_status = 'PENDING'::text) AND (direction = 'inbound'::text))`
- `idx_pem_tenant_supplier` - `CREATE INDEX idx_pem_tenant_supplier ON public.poc_email_messages USING btree (tenant_id, supplier_id)`
- `idx_pem_thread` - `CREATE INDEX idx_pem_thread ON public.poc_email_messages USING btree (tenant_id, thread_id)`
- `poc_email_messages_pkey` - `CREATE UNIQUE INDEX poc_email_messages_pkey ON public.poc_email_messages USING btree (message_id)`
- `uq_pem_gmail` - `CREATE UNIQUE INDEX uq_pem_gmail ON public.poc_email_messages USING btree (tenant_id, gmail_msg_id, direction) WHERE (gmail_msg_id IS NOT NULL)`

---

## Table: `purchase_order_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `po_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `sno` | `integer` | NO | None |
| `description` | `text` | NO | None |
| `norm` | `text` | NO | None |
| `unit` | `character varying(16)` | YES | None |
| `qty` | `numeric(14,3)` | NO | None |
| `unit_price` | `numeric(14,4)` | NO | None |
| `amount` | `numeric(14,2)` | NO | None |
| `delivery_date` | `date` | YES | None |

### Keys and Constraints

- `purchase_order_lines_pkey` - `PRIMARY KEY (id)`
- `purchase_order_lines_po_id_fkey` - `FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE`
- `purchase_order_lines_po_id_sno_key` - `UNIQUE (po_id, sno)`

### Indexes

- `purchase_order_lines_pkey` - `CREATE UNIQUE INDEX purchase_order_lines_pkey ON public.purchase_order_lines USING btree (id)`
- `purchase_order_lines_po_id_sno_key` - `CREATE UNIQUE INDEX purchase_order_lines_po_id_sno_key ON public.purchase_order_lines USING btree (po_id, sno)`

---

## Table: `purchase_orders`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `po_number` | `character varying(40)` | NO | None |
| `revision` | `integer` | NO | `1` |
| `po_date` | `date` | YES | None |
| `delivery_date` | `date` | YES | None |
| `store_sn` | `character varying(16)` | YES | None |
| `store_name` | `character varying(200)` | YES | None |
| `buyer_gstin` | `character varying(15)` | YES | None |
| `vendor_gstin` | `character varying(15)` | YES | None |
| `payment_terms` | `character varying(80)` | YES | None |
| `requisition_no` | `character varying(40)` | YES | None |
| `requisition_name` | `character varying(200)` | YES | None |
| `subtotal` | `numeric(14,2)` | YES | None |
| `tax` | `numeric(14,2)` | YES | None |
| `total` | `numeric(14,2)` | YES | None |
| `penalties` | `jsonb` | YES | None |
| `segment_id` | `uuid` | YES | None |
| `superseded_by` | `uuid` | YES | None |
| `deleted_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | YES | `now()` |

### Keys and Constraints

- `purchase_orders_pkey` - `PRIMARY KEY (id)`
- `purchase_orders_segment_id_fkey` - `FOREIGN KEY (segment_id) REFERENCES recon_doc_segments(id) ON DELETE SET NULL`
- `purchase_orders_superseded_by_fkey` - `FOREIGN KEY (superseded_by) REFERENCES purchase_orders(id)`
- `purchase_orders_tenant_id_po_number_revision_key` - `UNIQUE (tenant_id, po_number, revision)`

### Indexes

- `idx_po_supplier` - `CREATE INDEX idx_po_supplier ON public.purchase_orders USING btree (tenant_id, supplier_id)`
- `purchase_orders_pkey` - `CREATE UNIQUE INDEX purchase_orders_pkey ON public.purchase_orders USING btree (id)`
- `purchase_orders_tenant_id_po_number_revision_key` - `CREATE UNIQUE INDEX purchase_orders_tenant_id_po_number_revision_key ON public.purchase_orders USING btree (tenant_id, po_number, revision)`

---

## Table: `raw_api_payloads`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `payload_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `sync_job_id` | `text` | YES | None |
| `entity_type` | `entity_type` | NO | None |
| `raw_payload` | `jsonb` | NO | None |
| `is_processed` | `boolean` | NO | `false` |
| `received_at` | `timestamp with time zone` | NO | `now()` |
| `retry_count` | `integer` | NO | `0` |

### Keys and Constraints

- `raw_api_payloads_pkey` - `PRIMARY KEY (payload_id)`
- `raw_api_payloads_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `idx_raw_payload_entity` - `CREATE INDEX idx_raw_payload_entity ON public.raw_api_payloads USING btree (entity_type)`
- `idx_raw_payload_processed` - `CREATE INDEX idx_raw_payload_processed ON public.raw_api_payloads USING btree (tenant_id, is_processed)`
- `raw_api_payloads_pkey` - `CREATE UNIQUE INDEX raw_api_payloads_pkey ON public.raw_api_payloads USING btree (payload_id)`

---

## Table: `raw_ingestion_errors`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `error_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `payload_id` | `uuid` | YES | None |
| `upload_id` | `uuid` | YES | None |
| `webhook_event_id` | `uuid` | YES | None |
| `stage` | `text` | NO | None |
| `error_type` | `text` | NO | None |
| `validation_errors` | `jsonb` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `raw_ingestion_errors_payload_id_fkey` - `FOREIGN KEY (payload_id) REFERENCES raw_api_payloads(payload_id) ON DELETE SET NULL`
- `raw_ingestion_errors_pkey` - `PRIMARY KEY (error_id)`
- `raw_ingestion_errors_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `raw_ingestion_errors_upload_id_fkey` - `FOREIGN KEY (upload_id) REFERENCES raw_invoice_uploads(upload_id) ON DELETE SET NULL`
- `raw_ingestion_errors_webhook_event_id_fkey` - `FOREIGN KEY (webhook_event_id) REFERENCES raw_webhook_events(event_id) ON DELETE SET NULL`

### Indexes

- `raw_ingestion_errors_pkey` - `CREATE UNIQUE INDEX raw_ingestion_errors_pkey ON public.raw_ingestion_errors USING btree (error_id)`

---

## Table: `raw_invoice_uploads`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `upload_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `file_name` | `text` | NO | None |
| `file_type` | `upload_file_type` | NO | None |
| `file_size_bytes` | `integer` | YES | None |
| `storage_path` | `text` | NO | None |
| `status` | `upload_status` | NO | `'RECEIVED'::upload_status` |
| `ocr_engine_used` | `ocr_engine` | YES | None |
| `error_message` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `uploaded_by_name` | `character varying(100)` | YES | None |
| `uploaded_by_role` | `character varying(50)` | YES | None |
| `file_data` | `bytea` | YES | None |

### Keys and Constraints

- `raw_invoice_uploads_pkey` - `PRIMARY KEY (upload_id)`
- `raw_invoice_uploads_tenant_file_uniq` - `UNIQUE (tenant_id, file_name)`
- `raw_invoice_uploads_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_raw_uploads_status` - `CREATE INDEX idx_raw_uploads_status ON public.raw_invoice_uploads USING btree (tenant_id, status)`
- `raw_invoice_uploads_pkey` - `CREATE UNIQUE INDEX raw_invoice_uploads_pkey ON public.raw_invoice_uploads USING btree (upload_id)`
- `raw_invoice_uploads_tenant_file_uniq` - `CREATE UNIQUE INDEX raw_invoice_uploads_tenant_file_uniq ON public.raw_invoice_uploads USING btree (tenant_id, file_name)`

---

## Table: `raw_ocr_results`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `ocr_id` | `uuid` | NO | `gen_random_uuid()` |
| `upload_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `engine` | `ocr_engine` | NO | None |
| `page_number` | `smallint` | NO | `1` |
| `raw_response_jsonb` | `jsonb` | NO | None |
| `confidence_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `raw_ocr_results_pkey` - `PRIMARY KEY (ocr_id)`
- `raw_ocr_results_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `raw_ocr_results_upload_id_fkey` - `FOREIGN KEY (upload_id) REFERENCES raw_invoice_uploads(upload_id) ON DELETE CASCADE`

### Indexes

- `idx_raw_ocr_upload` - `CREATE INDEX idx_raw_ocr_upload ON public.raw_ocr_results USING btree (upload_id)`
- `raw_ocr_results_pkey` - `CREATE UNIQUE INDEX raw_ocr_results_pkey ON public.raw_ocr_results USING btree (ocr_id)`

---

## Table: `raw_webhook_events`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `event_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | YES | None |
| `source` | `data_source` | NO | None |
| `event_type` | `text` | NO | None |
| `raw_payload` | `jsonb` | NO | None |
| `is_signature_verified` | `boolean` | NO | `false` |
| `correlation_id` | `uuid` | YES | None |
| `received_at` | `timestamp with time zone` | NO | `now()` |
| `is_processed` | `boolean` | NO | `false` |
| `processing_error` | `text` | YES | None |
| `retry_count` | `integer` | NO | `0` |

### Keys and Constraints

- `raw_webhook_events_pkey` - `PRIMARY KEY (event_id)`
- `raw_webhook_events_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE SET NULL`

### Indexes

- `idx_webhook_processed` - `CREATE INDEX idx_webhook_processed ON public.raw_webhook_events USING btree (tenant_id, is_processed)`
- `raw_webhook_events_pkey` - `CREATE UNIQUE INDEX raw_webhook_events_pkey ON public.raw_webhook_events USING btree (event_id)`

---

## Table: `recon_case_segments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `case_id` | `uuid` | NO | None |
| `segment_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `role` | `character varying(16)` | NO | None |
| `link_method` | `character varying(8)` | NO | None |
| `link_score` | `numeric(4,3)` | YES | None |
| `linked_by` | `character varying(100)` | YES | None |
| `linked_at` | `timestamp with time zone` | YES | `now()` |

### Keys and Constraints

- `recon_case_segments_case_id_fkey` - `FOREIGN KEY (case_id) REFERENCES recon_cases(id) ON DELETE CASCADE`
- `recon_case_segments_pkey` - `PRIMARY KEY (case_id, segment_id)`
- `recon_case_segments_segment_id_fkey` - `FOREIGN KEY (segment_id) REFERENCES recon_doc_segments(id) ON DELETE CASCADE`

### Indexes

- `idx_rcs_segment` - `CREATE INDEX idx_rcs_segment ON public.recon_case_segments USING btree (segment_id)`
- `recon_case_segments_pkey` - `CREATE UNIQUE INDEX recon_case_segments_pkey ON public.recon_case_segments USING btree (case_id, segment_id)`

---

## Table: `recon_cases`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `brand_id` | `uuid` | YES | None |
| `bill_id` | `uuid` | YES | None |
| `invoice_segment_id` | `uuid` | YES | None |
| `po_id` | `uuid` | YES | None |
| `invoice_no` | `character varying(80)` | YES | None |
| `store_sn` | `character varying(16)` | YES | None |
| `status` | `character varying(20)` | NO | None |
| `summary_json` | `jsonb` | YES | None |
| `money_at_risk` | `numeric(14,2)` | NO | `0` |
| `under_billed` | `numeric(14,2)` | NO | `0` |
| `counts` | `jsonb` | YES | None |
| `result_hash` | `character(64)` | YES | None |
| `engine_version` | `character varying(16)` | YES | None |
| `computed_at` | `timestamp with time zone` | YES | None |
| `acknowledged_by` | `character varying(100)` | YES | None |
| `acknowledged_at` | `timestamp with time zone` | YES | None |
| `ack_hash` | `character(64)` | YES | None |
| `ack_note` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | YES | `now()` |
| `ref_no` | `integer` | YES | None |
| `input_fingerprint` | `character(64)` | YES | None |
| `rule_version` | `character varying(16)` | YES | None |
| `replay_of` | `uuid` | YES | None |
| `as_of` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `recon_cases_invoice_segment_id_fkey` - `FOREIGN KEY (invoice_segment_id) REFERENCES recon_doc_segments(id) ON DELETE SET NULL`
- `recon_cases_pkey` - `PRIMARY KEY (id)`
- `recon_cases_po_id_fkey` - `FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE SET NULL`
- `recon_cases_replay_of_fkey` - `FOREIGN KEY (replay_of) REFERENCES recon_cases(id)`

### Indexes

- `idx_rcase_fingerprint` - `CREATE INDEX idx_rcase_fingerprint ON public.recon_cases USING btree (tenant_id, input_fingerprint)`
- `idx_rcase_po` - `CREATE INDEX idx_rcase_po ON public.recon_cases USING btree (tenant_id, po_id)`
- `idx_rcase_supplier` - `CREATE INDEX idx_rcase_supplier ON public.recon_cases USING btree (tenant_id, supplier_id, status)`
- `recon_cases_pkey` - `CREATE UNIQUE INDEX recon_cases_pkey ON public.recon_cases USING btree (id)`
- `uq_rcase_bill` - `CREATE UNIQUE INDEX uq_rcase_bill ON public.recon_cases USING btree (tenant_id, bill_id) WHERE (bill_id IS NOT NULL)`
- `uq_rcase_ref` - `CREATE UNIQUE INDEX uq_rcase_ref ON public.recon_cases USING btree (tenant_id, ref_no) WHERE (ref_no IS NOT NULL)`

---

## Table: `recon_decisions`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `decision_id` | `bigint` | NO | `nextval('recon_decisions_decision_id_seq'::regclass)` |
| `tenant_id` | `uuid` | NO | None |
| `line_uid` | `uuid` | YES | None |
| `case_id` | `uuid` | YES | None |
| `kind` | `character varying(24)` | NO | None |
| `payload` | `jsonb` | NO | None |
| `supersedes` | `bigint` | YES | None |
| `actor` | `character varying(100)` | NO | None |
| `actor_kind` | `character varying(8)` | NO | `'human'::character varying` |
| `decided_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `recon_decisions_actor_kind_ck` - `CHECK (((actor_kind)::text = ANY (ARRAY[('human'::character varying)::text, ('rule'::character varying)::text, ('model'::character varying)::text])))`
- `recon_decisions_line_uid_fkey` - `FOREIGN KEY (line_uid) REFERENCES recon_line_identity(line_uid)`
- `recon_decisions_pkey` - `PRIMARY KEY (decision_id)`
- `recon_decisions_supersedes_fkey` - `FOREIGN KEY (supersedes) REFERENCES recon_decisions(decision_id)`

### Indexes

- `idx_rdec_asof` - `CREATE INDEX idx_rdec_asof ON public.recon_decisions USING btree (tenant_id, decided_at)`
- `idx_rdec_case` - `CREATE INDEX idx_rdec_case ON public.recon_decisions USING btree (tenant_id, case_id, decided_at DESC)`
- `idx_rdec_line` - `CREATE INDEX idx_rdec_line ON public.recon_decisions USING btree (tenant_id, line_uid, decided_at DESC)`
- `recon_decisions_pkey` - `CREATE UNIQUE INDEX recon_decisions_pkey ON public.recon_decisions USING btree (decision_id)`

---

## Table: `recon_doc_pages`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `doc_id` | `uuid` | NO | None |
| `page_index` | `integer` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `text` | `text` | YES | None |
| `source` | `character varying(8)` | NO | None |
| `ocr_confidence` | `numeric(4,3)` | YES | None |
| `doc_class` | `character varying(24)` | YES | None |
| `class_conf` | `numeric(4,3)` | YES | None |
| `class_method` | `character varying(8)` | YES | None |
| `llm_label` | `character varying(80)` | YES | None |
| `hints` | `jsonb` | YES | None |
| `doc_role_kind` | `text` | YES | `GENERATED ALWAYS AS ('doc_role'::text) STORED` |
| `doc_role` | `text` | YES | `GENERATED ALWAYS AS (
CASE doc_class
    WHEN 'APPROVAL_MEMO'::text THEN 'APPROVAL_COMMUNICATION'::text
    WHEN 'DELIVERY_CHALLAN'::text THEN 'DELIVERY_CHALLAN'::text
    WHEN 'GRN'::text THEN 'GOODS_RECEIPT_NOTE'::text
    WHEN 'INVOICE_ANNEXURE'::text THEN 'TAX_INVOICE'::text
    WHEN 'MEASUREMENT_SHEET'::text THEN 'MEASUREMENT_SHEET'::text
    WHEN 'POD'::text THEN 'PROOF_OF_DELIVERY'::text
    WHEN 'PURCHASE_ORDER'::text THEN 'PURCHASE_ORDER'::text
    WHEN 'PV_ANNEXURE_TYPED'::text THEN 'PHYSICAL_VERIFICATION_REPORT'::text
    WHEN 'PV_FIELD_SHEET'::text THEN 'SITE_VERIFICATION_SHEET'::text
    WHEN 'PV_NARRATIVE'::text THEN 'PHYSICAL_VERIFICATION_REPORT'::text
    WHEN 'PV_SHEET_SCANNED'::text THEN 'PHYSICAL_VERIFICATION_REPORT'::text
    WHEN 'TAX_INVOICE'::text THEN 'TAX_INVOICE'::text
    ELSE NULL::text
END) STORED` |

### Keys and Constraints

- `fk_recon_doc_pages_doc_role_vocab` - `FOREIGN KEY (doc_role_kind, doc_role) REFERENCES vocab_codes(kind, code)`
- `recon_doc_pages_doc_id_fkey` - `FOREIGN KEY (doc_id) REFERENCES vendor_documents(id) ON DELETE CASCADE`
- `recon_doc_pages_pkey` - `PRIMARY KEY (doc_id, page_index)`

### Indexes

- `recon_doc_pages_pkey` - `CREATE UNIQUE INDEX recon_doc_pages_pkey ON public.recon_doc_pages USING btree (doc_id, page_index)`

---

## Table: `recon_doc_segments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `doc_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `kind` | `character varying(16)` | NO | None |
| `llm_label` | `character varying(80)` | YES | None |
| `pages` | `integer[]` | NO | None |
| `section_title` | `character varying(160)` | YES | None |
| `vendor_name` | `character varying(200)` | YES | None |
| `vendor_gstin` | `character varying(15)` | YES | None |
| `store_sn` | `character varying(16)` | YES | None |
| `confidence` | `numeric(4,3)` | YES | None |
| `extracted_json` | `jsonb` | YES | None |
| `extractor_version` | `character varying(16)` | YES | None |
| `status` | `character varying(16)` | NO | `'PENDING'::character varying` |
| `link_candidates` | `jsonb` | YES | None |
| `warnings` | `jsonb` | YES | None |
| `kind_overridden_by` | `character varying(100)` | YES | None |
| `created_at` | `timestamp with time zone` | YES | `now()` |
| `doc_role_kind` | `text` | YES | `GENERATED ALWAYS AS ('doc_role'::text) STORED` |
| `recon_leg_kind` | `text` | YES | `GENERATED ALWAYS AS ('recon_leg'::text) STORED` |
| `receipt_granularity_kind` | `text` | YES | `GENERATED ALWAYS AS ('receipt_granularity'::text) STORED` |
| `pv_format_kind` | `text` | YES | `GENERATED ALWAYS AS ('pv_format'::text) STORED` |
| `evidence_layer_kind` | `text` | YES | `GENERATED ALWAYS AS ('evidence_layer'::text) STORED` |
| `doc_role` | `text` | YES | `GENERATED ALWAYS AS (
CASE kind
    WHEN 'APPROVAL_MEMO'::text THEN 'APPROVAL_COMMUNICATION'::text
    WHEN 'POD'::text THEN 'PROOF_OF_DELIVERY'::text
    WHEN 'PURCHASE_ORDER'::text THEN 'PURCHASE_ORDER'::text
    WHEN 'PV_SECTION'::text THEN 'PHYSICAL_VERIFICATION_REPORT'::text
    WHEN 'TAX_INVOICE'::text THEN 'TAX_INVOICE'::text
    ELSE NULL::text
END) STORED` |
| `recon_leg` | `text` | YES | `GENERATED ALWAYS AS (
CASE kind
    WHEN 'POD'::text THEN 'RECEIPT'::text
    WHEN 'PURCHASE_ORDER'::text THEN 'COMMITMENT'::text
    WHEN 'PV_SECTION'::text THEN 'RECEIPT'::text
    WHEN 'TAX_INVOICE'::text THEN 'BILLING'::text
    ELSE NULL::text
END) STORED` |
| `receipt_granularity` | `text` | YES | `GENERATED ALWAYS AS (
CASE kind
    WHEN 'POD'::text THEN 'CONSIGNMENT'::text
    WHEN 'PV_SECTION'::text THEN 'ITEM_QTY'::text
    ELSE NULL::text
END) STORED` |
| `pv_format` | `text` | YES | `GENERATED ALWAYS AS (
CASE (extracted_json ->> 'layout'::text)
    WHEN 'generic'::text THEN 'SPREADSHEET_TABLE'::text
    WHEN 'jpc_typed'::text THEN 'AUDITOR_ANNEXURE'::text
    WHEN 'matolia_scan'::text THEN 'WITNESSED_VENDOR_SHEET'::text
    ELSE NULL::text
END) STORED` |
| `evidence_layer` | `text` | YES | `GENERATED ALWAYS AS (
CASE (extracted_json ->> 'layout'::text)
    WHEN 'generic'::text THEN 'TYPED_BODY'::text
    WHEN 'jpc_typed'::text THEN 'TYPED_ANNEXURE'::text
    WHEN 'matolia_scan'::text THEN 'WITNESSED_SHEET'::text
    ELSE NULL::text
END) STORED` |

### Keys and Constraints

- `fk_recon_doc_segments_doc_role_vocab` - `FOREIGN KEY (doc_role_kind, doc_role) REFERENCES vocab_codes(kind, code)`
- `fk_recon_doc_segments_evidence_layer_vocab` - `FOREIGN KEY (evidence_layer_kind, evidence_layer) REFERENCES vocab_codes(kind, code)`
- `fk_recon_doc_segments_pv_format_vocab` - `FOREIGN KEY (pv_format_kind, pv_format) REFERENCES vocab_codes(kind, code)`
- `fk_recon_doc_segments_receipt_granularity_vocab` - `FOREIGN KEY (receipt_granularity_kind, receipt_granularity) REFERENCES vocab_codes(kind, code)`
- `fk_recon_doc_segments_recon_leg_vocab` - `FOREIGN KEY (recon_leg_kind, recon_leg) REFERENCES vocab_codes(kind, code)`
- `recon_doc_segments_doc_id_fkey` - `FOREIGN KEY (doc_id) REFERENCES vendor_documents(id) ON DELETE CASCADE`
- `recon_doc_segments_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_rseg_doc` - `CREATE INDEX idx_rseg_doc ON public.recon_doc_segments USING btree (doc_id)`
- `idx_rseg_store` - `CREATE INDEX idx_rseg_store ON public.recon_doc_segments USING btree (tenant_id, store_sn)`
- `idx_rseg_supplier` - `CREATE INDEX idx_rseg_supplier ON public.recon_doc_segments USING btree (tenant_id, supplier_id, kind)`
- `recon_doc_segments_pkey` - `CREATE UNIQUE INDEX recon_doc_segments_pkey ON public.recon_doc_segments USING btree (id)`

---

## Table: `recon_edges`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `edge_id` | `bigint` | NO | `nextval('recon_edges_edge_id_seq'::regclass)` |
| `tenant_id` | `uuid` | NO | None |
| `case_id` | `uuid` | NO | None |
| `kind` | `character varying(24)` | NO | None |
| `src_key` | `character varying(200)` | NO | None |
| `dst_key` | `character varying(200)` | NO | None |
| `src_line_uid` | `uuid` | YES | None |
| `dst_line_uid` | `uuid` | YES | None |
| `method` | `character varying(16)` | YES | None |
| `score` | `numeric(4,3)` | YES | None |
| `confirmed` | `boolean` | NO | `false` |
| `built_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `recon_edges_case_id_fkey` - `FOREIGN KEY (case_id) REFERENCES recon_cases(id) ON DELETE CASCADE`
- `recon_edges_case_id_kind_src_key_dst_key_key` - `UNIQUE (case_id, kind, src_key, dst_key)`
- `recon_edges_pkey` - `PRIMARY KEY (edge_id)`

### Indexes

- `idx_redge_case` - `CREATE INDEX idx_redge_case ON public.recon_edges USING btree (tenant_id, case_id, kind)`
- `idx_redge_dst` - `CREATE INDEX idx_redge_dst ON public.recon_edges USING btree (tenant_id, dst_line_uid)`
- `idx_redge_src` - `CREATE INDEX idx_redge_src ON public.recon_edges USING btree (tenant_id, src_line_uid)`
- `recon_edges_case_id_kind_src_key_dst_key_key` - `CREATE UNIQUE INDEX recon_edges_case_id_kind_src_key_dst_key_key ON public.recon_edges USING btree (case_id, kind, src_key, dst_key)`
- `recon_edges_pkey` - `CREATE UNIQUE INDEX recon_edges_pkey ON public.recon_edges USING btree (edge_id)`

---

## Table: `recon_events`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `bigint` | NO | `nextval('recon_events_id_seq'::regclass)` |
| `tenant_id` | `uuid` | NO | None |
| `case_id` | `uuid` | YES | None |
| `doc_id` | `uuid` | YES | None |
| `kind` | `character varying(32)` | NO | None |
| `payload` | `jsonb` | YES | None |
| `actor` | `character varying(100)` | YES | None |
| `at` | `timestamp with time zone` | YES | `now()` |

### Keys and Constraints

- `recon_events_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_revents_case` - `CREATE INDEX idx_revents_case ON public.recon_events USING btree (tenant_id, case_id, at)`
- `idx_revents_doc` - `CREATE INDEX idx_revents_doc ON public.recon_events USING btree (tenant_id, doc_id, at)`
- `recon_events_pkey` - `CREATE UNIQUE INDEX recon_events_pkey ON public.recon_events USING btree (id)`

---

## Table: `recon_evidence_rows`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `segment_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `sno` | `integer` | YES | None |
| `asset_code` | `character varying(80)` | YES | None |
| `item` | `text` | NO | None |
| `norm` | `text` | NO | None |
| `unit` | `character varying(16)` | YES | None |
| `po_qty` | `numeric(14,3)` | YES | None |
| `vendor_qty` | `numeric(14,3)` | YES | None |
| `audit_qty` | `numeric(14,3)` | YES | None |
| `audit_qty_raw` | `character varying(40)` | YES | None |
| `audit_alternatives` | `jsonb` | YES | None |
| `remark` | `text` | YES | None |
| `verdict` | `character varying(16)` | YES | None |
| `mounted` | `integer` | YES | None |
| `unmounted` | `integer` | YES | None |
| `damaged` | `integer` | YES | None |
| `rate` | `numeric(14,4)` | YES | None |
| `rate_after_discount` | `numeric(14,4)` | YES | None |
| `row_type` | `character varying(12)` | NO | `'po'::character varying` |
| `confidence` | `numeric(4,3)` | YES | None |
| `needs_review` | `boolean` | NO | `false` |
| `page` | `integer` | YES | None |
| `bbox` | `jsonb` | YES | None |
| `corrected_by` | `character varying(100)` | YES | None |
| `corrected_at` | `timestamp with time zone` | YES | None |
| `original_json` | `jsonb` | YES | None |
| `value_history` | `jsonb` | YES | None |
| `verification_status_kind` | `text` | YES | `GENERATED ALWAYS AS ('verification_status'::text) STORED` |
| `scope_exclusion_source_kind` | `text` | YES | `GENERATED ALWAYS AS ('scope_exclusion_source'::text) STORED` |
| `line_origin_kind` | `text` | YES | `GENERATED ALWAYS AS ('line_origin'::text) STORED` |
| `uom_kind` | `text` | YES | `GENERATED ALWAYS AS ('uom'::text) STORED` |
| `uom_family_kind` | `text` | YES | `GENERATED ALWAYS AS ('uom_family'::text) STORED` |
| `auto_verdict` | `character varying(16)` | YES | None |
| `verification_status` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN (((COALESCE(verdict, auto_verdict))::text = 'NOT_COVERED'::text) OR (((COALESCE(verdict, auto_verdict))::text = ANY (ARRAY[('NOT_COVERED'::character varying)::text, ('NOT_COUNTABLE'::character varying)::text, ('ADDITIONAL'::character varying)::text])) AND (COALESCE(remark, ''::text) ~* 'not in scope\|out of (audit\|scope)\|not covered\|certificate needed'::text))) THEN 'NOT_IN_SCOPE'::text
    ELSE
    CASE COALESCE(verdict, auto_verdict)
        WHEN 'ADDITIONAL'::text THEN 'VERIFIED'::text
        WHEN 'NOT_COUNTABLE'::text THEN 'NOT_VERIFIABLE'::text
        WHEN 'NOT_COVERED'::text THEN 'NOT_IN_SCOPE'::text
        WHEN 'NOT_DONE'::text THEN 'NOT_EXECUTED'::text
        WHEN 'VERIFIED'::text THEN 'VERIFIED'::text
        ELSE NULL::text
    END
END) STORED` |
| `scope_exclusion_source` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN (((COALESCE(verdict, auto_verdict))::text = 'NOT_COVERED'::text) OR (((COALESCE(verdict, auto_verdict))::text = ANY (ARRAY[('NOT_COVERED'::character varying)::text, ('NOT_COUNTABLE'::character varying)::text, ('ADDITIONAL'::character varying)::text])) AND (COALESCE(remark, ''::text) ~* 'not in scope\|out of (audit\|scope)\|not covered\|certificate needed'::text))) THEN
    CASE
        WHEN (COALESCE(remark, ''::text) ~* 'instruction'::text) THEN 'CLIENT_INSTRUCTION'::text
        WHEN (COALESCE(remark, ''::text) ~* 'certificate'::text) THEN 'CERTIFICATE_PENDING'::text
        ELSE 'AUDITOR_SCOPE'::text
    END
    ELSE NULL::text
END) STORED` |
| `line_origin` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN (((row_type)::text = 'additional'::text) OR ((COALESCE(verdict, auto_verdict))::text = 'ADDITIONAL'::text)) THEN 'ADDITIONAL_WORK'::text
    ELSE 'CONTRACT_LINE'::text
END) STORED` |
| `uom` | `text` | YES | `GENERATED ALWAYS AS (
CASE regexp_replace(lower((COALESCE(unit, ''::character varying))::text), '[^a-z0-9%²'']'::text, ''::text, 'g'::text)
    WHEN '%'::text THEN 'PCT'::text
    WHEN ''''::text THEN 'RFT'::text
    WHEN 'actwt'::text THEN 'KG'::text
    WHEN 'box'::text THEN 'PKG'::text
    WHEN 'boxes'::text THEN 'PKG'::text
    WHEN 'carton'::text THEN 'PKG'::text
    WHEN 'cartons'::text THEN 'PKG'::text
    WHEN 'each'::text THEN 'EA'::text
    WHEN 'fit'::text THEN 'RFT'::text
    WHEN 'ft'::text THEN 'RFT'::text
    WHEN 'hp'::text THEN 'HP'::text
    WHEN 'job'::text THEN 'LS'::text
    WHEN 'kg'::text THEN 'KG'::text
    WHEN 'kgs'::text THEN 'KG'::text
    WHEN 'kit'::text THEN 'SET'::text
    WHEN 'kits'::text THEN 'SET'::text
    WHEN 'km'::text THEN 'KM'::text
    WHEN 'kms'::text THEN 'KM'::text
    WHEN 'kva'::text THEN 'KVA'::text
    WHEN 'kw'::text THEN 'KW'::text
    WHEN 'lot'::text THEN 'LS'::text
    WHEN 'ls'::text THEN 'LS'::text
    WHEN 'lumpsum'::text THEN 'LS'::text
    WHEN 'm'::text THEN 'RMT'::text
    WHEN 'm2'::text THEN 'SQM'::text
    WHEN 'meter'::text THEN 'RMT'::text
    WHEN 'metre'::text THEN 'RMT'::text
    WHEN 'mtr'::text THEN 'RMT'::text
    WHEN 'mtrs'::text THEN 'RMT'::text
    WHEN 'm²'::text THEN 'SQM'::text
    WHEN 'na'::text THEN 'LS'::text
    WHEN 'no'::text THEN 'EA'::text
    WHEN 'nos'::text THEN 'EA'::text
    WHEN 'package'::text THEN 'PKG'::text
    WHEN 'packages'::text THEN 'PKG'::text
    WHEN 'pc'::text THEN 'EA'::text
    WHEN 'pcs'::text THEN 'EA'::text
    WHEN 'pct'::text THEN 'PCT'::text
    WHEN 'percent'::text THEN 'PCT'::text
    WHEN 'pkg'::text THEN 'PKG'::text
    WHEN 'pkgs'::text THEN 'PKG'::text
    WHEN 'rft'::text THEN 'RFT'::text
    WHEN 'rmt'::text THEN 'RMT'::text
    WHEN 'runningfeet'::text THEN 'RFT'::text
    WHEN 'runningft'::text THEN 'RFT'::text
    WHEN 'runningmetre'::text THEN 'RMT'::text
    WHEN 'set'::text THEN 'SET'::text
    WHEN 'sets'::text THEN 'SET'::text
    WHEN 'sf'::text THEN 'SQFT'::text
    WHEN 'sft'::text THEN 'SQFT'::text
    WHEN 'sm'::text THEN 'SQM'::text
    WHEN 'sqft'::text THEN 'SQFT'::text
    WHEN 'sqm'::text THEN 'SQM'::text
    WHEN 'sqmt'::text THEN 'SQM'::text
    WHEN 'sqmtrs'::text THEN 'SQM'::text
    WHEN 'squarefeet'::text THEN 'SQFT'::text
    WHEN 'ton'::text THEN 'TR'::text
    WHEN 'tons'::text THEN 'TR'::text
    WHEN 'tr'::text THEN 'TR'::text
    WHEN 'unit'::text THEN 'EA'::text
    WHEN 'units'::text THEN 'EA'::text
    ELSE NULL::text
END) STORED` |
| `uom_family` | `text` | YES | `GENERATED ALWAYS AS (
CASE regexp_replace(lower((COALESCE(unit, ''::character varying))::text), '[^a-z0-9%²'']'::text, ''::text, 'g'::text)
    WHEN '%'::text THEN 'PERCENT'::text
    WHEN ''''::text THEN 'LENGTH'::text
    WHEN 'actwt'::text THEN 'MASS'::text
    WHEN 'box'::text THEN 'COUNT'::text
    WHEN 'boxes'::text THEN 'COUNT'::text
    WHEN 'carton'::text THEN 'COUNT'::text
    WHEN 'cartons'::text THEN 'COUNT'::text
    WHEN 'each'::text THEN 'COUNT'::text
    WHEN 'fit'::text THEN 'LENGTH'::text
    WHEN 'ft'::text THEN 'LENGTH'::text
    WHEN 'hp'::text THEN 'CAPACITY'::text
    WHEN 'job'::text THEN 'LUMPSUM'::text
    WHEN 'kg'::text THEN 'MASS'::text
    WHEN 'kgs'::text THEN 'MASS'::text
    WHEN 'kit'::text THEN 'COUNT'::text
    WHEN 'kits'::text THEN 'COUNT'::text
    WHEN 'km'::text THEN 'DISTANCE'::text
    WHEN 'kms'::text THEN 'DISTANCE'::text
    WHEN 'kva'::text THEN 'CAPACITY'::text
    WHEN 'kw'::text THEN 'CAPACITY'::text
    WHEN 'lot'::text THEN 'LUMPSUM'::text
    WHEN 'ls'::text THEN 'LUMPSUM'::text
    WHEN 'lumpsum'::text THEN 'LUMPSUM'::text
    WHEN 'm'::text THEN 'LENGTH'::text
    WHEN 'm2'::text THEN 'AREA'::text
    WHEN 'meter'::text THEN 'LENGTH'::text
    WHEN 'metre'::text THEN 'LENGTH'::text
    WHEN 'mtr'::text THEN 'LENGTH'::text
    WHEN 'mtrs'::text THEN 'LENGTH'::text
    WHEN 'm²'::text THEN 'AREA'::text
    WHEN 'na'::text THEN 'LUMPSUM'::text
    WHEN 'no'::text THEN 'COUNT'::text
    WHEN 'nos'::text THEN 'COUNT'::text
    WHEN 'package'::text THEN 'COUNT'::text
    WHEN 'packages'::text THEN 'COUNT'::text
    WHEN 'pc'::text THEN 'COUNT'::text
    WHEN 'pcs'::text THEN 'COUNT'::text
    WHEN 'pct'::text THEN 'PERCENT'::text
    WHEN 'percent'::text THEN 'PERCENT'::text
    WHEN 'pkg'::text THEN 'COUNT'::text
    WHEN 'pkgs'::text THEN 'COUNT'::text
    WHEN 'rft'::text THEN 'LENGTH'::text
    WHEN 'rmt'::text THEN 'LENGTH'::text
    WHEN 'runningfeet'::text THEN 'LENGTH'::text
    WHEN 'runningft'::text THEN 'LENGTH'::text
    WHEN 'runningmetre'::text THEN 'LENGTH'::text
    WHEN 'set'::text THEN 'COUNT'::text
    WHEN 'sets'::text THEN 'COUNT'::text
    WHEN 'sf'::text THEN 'AREA'::text
    WHEN 'sft'::text THEN 'AREA'::text
    WHEN 'sm'::text THEN 'AREA'::text
    WHEN 'sqft'::text THEN 'AREA'::text
    WHEN 'sqm'::text THEN 'AREA'::text
    WHEN 'sqmt'::text THEN 'AREA'::text
    WHEN 'sqmtrs'::text THEN 'AREA'::text
    WHEN 'squarefeet'::text THEN 'AREA'::text
    WHEN 'ton'::text THEN 'CAPACITY'::text
    WHEN 'tons'::text THEN 'CAPACITY'::text
    WHEN 'tr'::text THEN 'CAPACITY'::text
    WHEN 'unit'::text THEN 'COUNT'::text
    WHEN 'units'::text THEN 'COUNT'::text
    ELSE NULL::text
END) STORED` |
| `natural_key` | `character varying(120)` | YES | None |
| `key_basis` | `character varying(16)` | YES | None |
| `key_confidence` | `numeric(4,3)` | YES | None |
| `line_uid` | `uuid` | YES | None |
| `amount` | `numeric(16,2)` | YES | None |

### Keys and Constraints

- `fk_recon_evidence_rows_line_origin_vocab` - `FOREIGN KEY (line_origin_kind, line_origin) REFERENCES vocab_codes(kind, code)`
- `fk_recon_evidence_rows_scope_exclusion_source_vocab` - `FOREIGN KEY (scope_exclusion_source_kind, scope_exclusion_source) REFERENCES vocab_codes(kind, code)`
- `fk_recon_evidence_rows_uom_family_vocab` - `FOREIGN KEY (uom_family_kind, uom_family) REFERENCES vocab_codes(kind, code)`
- `fk_recon_evidence_rows_uom_vocab` - `FOREIGN KEY (uom_kind, uom) REFERENCES vocab_codes(kind, code)`
- `fk_recon_evidence_rows_verification_status_vocab` - `FOREIGN KEY (verification_status_kind, verification_status) REFERENCES vocab_codes(kind, code)`
- `recon_evidence_rows_pkey` - `PRIMARY KEY (id)`
- `recon_evidence_rows_segment_id_fkey` - `FOREIGN KEY (segment_id) REFERENCES recon_doc_segments(id) ON DELETE CASCADE`

### Indexes

- `idx_rev_seg` - `CREATE INDEX idx_rev_seg ON public.recon_evidence_rows USING btree (segment_id)`
- `idx_rev_uid` - `CREATE INDEX idx_rev_uid ON public.recon_evidence_rows USING btree (line_uid)`
- `recon_evidence_rows_pkey` - `CREATE UNIQUE INDEX recon_evidence_rows_pkey ON public.recon_evidence_rows USING btree (id)`

---

## Table: `recon_grn_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `grn_line_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `grn_number` | `character varying(60)` | YES | None |
| `grn_date` | `date` | YES | None |
| `po_number` | `character varying(40)` | NO | None |
| `po_line_no` | `character varying(20)` | YES | None |
| `item_code` | `character varying(80)` | YES | None |
| `description` | `text` | YES | None |
| `norm` | `text` | YES | None |
| `unit` | `character varying(16)` | YES | None |
| `qty_received` | `numeric(14,3)` | NO | None |
| `rate` | `numeric(14,4)` | YES | None |
| `amount` | `numeric(14,2)` | YES | None |
| `msd_voucher` | `character varying(60)` | YES | None |
| `source_file` | `text` | YES | None |
| `line_uid` | `uuid` | YES | None |
| `ingested_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `recon_grn_lines_pkey` - `PRIMARY KEY (grn_line_id)`

### Indexes

- `idx_grn_number` - `CREATE INDEX idx_grn_number ON public.recon_grn_lines USING btree (tenant_id, grn_number)`
- `idx_grn_po` - `CREATE INDEX idx_grn_po ON public.recon_grn_lines USING btree (tenant_id, po_number)`
- `recon_grn_lines_pkey` - `CREATE UNIQUE INDEX recon_grn_lines_pkey ON public.recon_grn_lines USING btree (grn_line_id)`
- `uq_grn_line` - `CREATE UNIQUE INDEX uq_grn_line ON public.recon_grn_lines USING btree (tenant_id, grn_number, po_number, COALESCE(po_line_no, ''::character varying), COALESCE(item_code, ''::character varying))`

---

## Table: `recon_header_checks`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `case_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `code` | `character varying(32)` | NO | None |
| `label` | `text` | NO | None |
| `severity` | `character varying(8)` | NO | None |
| `passed` | `boolean` | NO | None |
| `detail` | `text` | YES | None |
| `evidence` | `jsonb` | YES | None |
| `check_code_kind` | `text` | YES | `GENERATED ALWAYS AS ('recon_check_code'::text) STORED` |
| `outcome_kind` | `text` | YES | `GENERATED ALWAYS AS ('recon_outcome'::text) STORED` |
| `check_code` | `text` | YES | `GENERATED ALWAYS AS (upper((code)::text)) STORED` |
| `outcome` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN passed THEN 'PASS'::text
    ELSE
    CASE severity
        WHEN 'BLOCKER'::text THEN 'FAIL'::text
        WHEN 'INFO'::text THEN 'WARN'::text
        WHEN 'OK'::text THEN 'PASS'::text
        WHEN 'REVIEW'::text THEN 'HOLD'::text
        ELSE NULL::text
    END
END) STORED` |

### Keys and Constraints

- `fk_recon_header_checks_check_code_vocab` - `FOREIGN KEY (check_code_kind, check_code) REFERENCES vocab_codes(kind, code)`
- `fk_recon_header_checks_outcome_vocab` - `FOREIGN KEY (outcome_kind, outcome) REFERENCES vocab_codes(kind, code)`
- `recon_header_checks_case_id_fkey` - `FOREIGN KEY (case_id) REFERENCES recon_cases(id) ON DELETE CASCADE`
- `recon_header_checks_pkey` - `PRIMARY KEY (case_id, code)`

### Indexes

- `recon_header_checks_pkey` - `CREATE UNIQUE INDEX recon_header_checks_pkey ON public.recon_header_checks USING btree (case_id, code)`

---

## Table: `recon_invoice_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `segment_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `sno` | `integer` | YES | None |
| `description` | `text` | NO | None |
| `norm` | `text` | NO | None |
| `hsn` | `character varying(12)` | YES | None |
| `unit` | `character varying(16)` | YES | None |
| `qty` | `numeric(14,3)` | YES | None |
| `rate` | `numeric(14,4)` | YES | None |
| `amount` | `numeric(14,2)` | YES | None |
| `tax_rate` | `numeric(5,2)` | YES | None |
| `confidence` | `numeric(4,3)` | YES | None |
| `page` | `integer` | YES | None |
| `bbox` | `jsonb` | YES | None |
| `is_charge` | `boolean` | NO | `false` |
| `charge_pct` | `numeric(6,3)` | YES | None |
| `line_origin_kind` | `text` | YES | `GENERATED ALWAYS AS ('line_origin'::text) STORED` |
| `charge_type_kind` | `text` | YES | `GENERATED ALWAYS AS ('charge_type'::text) STORED` |
| `pricing_basis_kind` | `text` | YES | `GENERATED ALWAYS AS ('pricing_basis'::text) STORED` |
| `uom_kind` | `text` | YES | `GENERATED ALWAYS AS ('uom'::text) STORED` |
| `uom_family_kind` | `text` | YES | `GENERATED ALWAYS AS ('uom_family'::text) STORED` |
| `line_origin` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN is_charge THEN 'CHARGE'::text
    ELSE 'CONTRACT_LINE'::text
END) STORED` |
| `charge_type` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN is_charge THEN
    CASE
        WHEN (description ~* 'packing\|p\s*&\s*f\|forwarding'::text) THEN 'PACKING_FORWARDING'::text
        WHEN (description ~* 'transport\|freight\|cartage'::text) THEN 'FREIGHT'::text
        WHEN (description ~* 'loading'::text) THEN 'LOADING_UNLOADING'::text
        WHEN (description ~* 'outst?ation'::text) THEN 'OUTSTATION'::text
        WHEN (description ~* 'scaffold'::text) THEN 'SCAFFOLDING'::text
        WHEN (description ~* 'malba\|debris'::text) THEN 'DEBRIS_DISPOSAL'::text
        WHEN (description ~* 'insurance'::text) THEN 'INSURANCE'::text
        WHEN (description ~* 'mobili[sz]ation'::text) THEN 'MOBILISATION'::text
        WHEN (description ~* 'handling'::text) THEN 'HANDLING'::text
        ELSE NULL::text
    END
    ELSE NULL::text
END) STORED` |
| `pricing_basis` | `text` | YES | `GENERATED ALWAYS AS (
CASE
    WHEN (is_charge AND (charge_pct IS NOT NULL)) THEN 'PERCENT_OF_BASE'::text
    WHEN is_charge THEN 'LUMPSUM'::text
    ELSE 'UNIT_RATE'::text
END) STORED` |
| `uom` | `text` | YES | `GENERATED ALWAYS AS (
CASE regexp_replace(lower((COALESCE(unit, ''::character varying))::text), '[^a-z0-9%²'']'::text, ''::text, 'g'::text)
    WHEN '%'::text THEN 'PCT'::text
    WHEN ''''::text THEN 'RFT'::text
    WHEN 'actwt'::text THEN 'KG'::text
    WHEN 'box'::text THEN 'PKG'::text
    WHEN 'boxes'::text THEN 'PKG'::text
    WHEN 'carton'::text THEN 'PKG'::text
    WHEN 'cartons'::text THEN 'PKG'::text
    WHEN 'each'::text THEN 'EA'::text
    WHEN 'fit'::text THEN 'RFT'::text
    WHEN 'ft'::text THEN 'RFT'::text
    WHEN 'hp'::text THEN 'HP'::text
    WHEN 'job'::text THEN 'LS'::text
    WHEN 'kg'::text THEN 'KG'::text
    WHEN 'kgs'::text THEN 'KG'::text
    WHEN 'kit'::text THEN 'SET'::text
    WHEN 'kits'::text THEN 'SET'::text
    WHEN 'km'::text THEN 'KM'::text
    WHEN 'kms'::text THEN 'KM'::text
    WHEN 'kva'::text THEN 'KVA'::text
    WHEN 'kw'::text THEN 'KW'::text
    WHEN 'lot'::text THEN 'LS'::text
    WHEN 'ls'::text THEN 'LS'::text
    WHEN 'lumpsum'::text THEN 'LS'::text
    WHEN 'm'::text THEN 'RMT'::text
    WHEN 'm2'::text THEN 'SQM'::text
    WHEN 'meter'::text THEN 'RMT'::text
    WHEN 'metre'::text THEN 'RMT'::text
    WHEN 'mtr'::text THEN 'RMT'::text
    WHEN 'mtrs'::text THEN 'RMT'::text
    WHEN 'm²'::text THEN 'SQM'::text
    WHEN 'na'::text THEN 'LS'::text
    WHEN 'no'::text THEN 'EA'::text
    WHEN 'nos'::text THEN 'EA'::text
    WHEN 'package'::text THEN 'PKG'::text
    WHEN 'packages'::text THEN 'PKG'::text
    WHEN 'pc'::text THEN 'EA'::text
    WHEN 'pcs'::text THEN 'EA'::text
    WHEN 'pct'::text THEN 'PCT'::text
    WHEN 'percent'::text THEN 'PCT'::text
    WHEN 'pkg'::text THEN 'PKG'::text
    WHEN 'pkgs'::text THEN 'PKG'::text
    WHEN 'rft'::text THEN 'RFT'::text
    WHEN 'rmt'::text THEN 'RMT'::text
    WHEN 'runningfeet'::text THEN 'RFT'::text
    WHEN 'runningft'::text THEN 'RFT'::text
    WHEN 'runningmetre'::text THEN 'RMT'::text
    WHEN 'set'::text THEN 'SET'::text
    WHEN 'sets'::text THEN 'SET'::text
    WHEN 'sf'::text THEN 'SQFT'::text
    WHEN 'sft'::text THEN 'SQFT'::text
    WHEN 'sm'::text THEN 'SQM'::text
    WHEN 'sqft'::text THEN 'SQFT'::text
    WHEN 'sqm'::text THEN 'SQM'::text
    WHEN 'sqmt'::text THEN 'SQM'::text
    WHEN 'sqmtrs'::text THEN 'SQM'::text
    WHEN 'squarefeet'::text THEN 'SQFT'::text
    WHEN 'ton'::text THEN 'TR'::text
    WHEN 'tons'::text THEN 'TR'::text
    WHEN 'tr'::text THEN 'TR'::text
    WHEN 'unit'::text THEN 'EA'::text
    WHEN 'units'::text THEN 'EA'::text
    ELSE NULL::text
END) STORED` |
| `uom_family` | `text` | YES | `GENERATED ALWAYS AS (
CASE regexp_replace(lower((COALESCE(unit, ''::character varying))::text), '[^a-z0-9%²'']'::text, ''::text, 'g'::text)
    WHEN '%'::text THEN 'PERCENT'::text
    WHEN ''''::text THEN 'LENGTH'::text
    WHEN 'actwt'::text THEN 'MASS'::text
    WHEN 'box'::text THEN 'COUNT'::text
    WHEN 'boxes'::text THEN 'COUNT'::text
    WHEN 'carton'::text THEN 'COUNT'::text
    WHEN 'cartons'::text THEN 'COUNT'::text
    WHEN 'each'::text THEN 'COUNT'::text
    WHEN 'fit'::text THEN 'LENGTH'::text
    WHEN 'ft'::text THEN 'LENGTH'::text
    WHEN 'hp'::text THEN 'CAPACITY'::text
    WHEN 'job'::text THEN 'LUMPSUM'::text
    WHEN 'kg'::text THEN 'MASS'::text
    WHEN 'kgs'::text THEN 'MASS'::text
    WHEN 'kit'::text THEN 'COUNT'::text
    WHEN 'kits'::text THEN 'COUNT'::text
    WHEN 'km'::text THEN 'DISTANCE'::text
    WHEN 'kms'::text THEN 'DISTANCE'::text
    WHEN 'kva'::text THEN 'CAPACITY'::text
    WHEN 'kw'::text THEN 'CAPACITY'::text
    WHEN 'lot'::text THEN 'LUMPSUM'::text
    WHEN 'ls'::text THEN 'LUMPSUM'::text
    WHEN 'lumpsum'::text THEN 'LUMPSUM'::text
    WHEN 'm'::text THEN 'LENGTH'::text
    WHEN 'm2'::text THEN 'AREA'::text
    WHEN 'meter'::text THEN 'LENGTH'::text
    WHEN 'metre'::text THEN 'LENGTH'::text
    WHEN 'mtr'::text THEN 'LENGTH'::text
    WHEN 'mtrs'::text THEN 'LENGTH'::text
    WHEN 'm²'::text THEN 'AREA'::text
    WHEN 'na'::text THEN 'LUMPSUM'::text
    WHEN 'no'::text THEN 'COUNT'::text
    WHEN 'nos'::text THEN 'COUNT'::text
    WHEN 'package'::text THEN 'COUNT'::text
    WHEN 'packages'::text THEN 'COUNT'::text
    WHEN 'pc'::text THEN 'COUNT'::text
    WHEN 'pcs'::text THEN 'COUNT'::text
    WHEN 'pct'::text THEN 'PERCENT'::text
    WHEN 'percent'::text THEN 'PERCENT'::text
    WHEN 'pkg'::text THEN 'COUNT'::text
    WHEN 'pkgs'::text THEN 'COUNT'::text
    WHEN 'rft'::text THEN 'LENGTH'::text
    WHEN 'rmt'::text THEN 'LENGTH'::text
    WHEN 'runningfeet'::text THEN 'LENGTH'::text
    WHEN 'runningft'::text THEN 'LENGTH'::text
    WHEN 'runningmetre'::text THEN 'LENGTH'::text
    WHEN 'set'::text THEN 'COUNT'::text
    WHEN 'sets'::text THEN 'COUNT'::text
    WHEN 'sf'::text THEN 'AREA'::text
    WHEN 'sft'::text THEN 'AREA'::text
    WHEN 'sm'::text THEN 'AREA'::text
    WHEN 'sqft'::text THEN 'AREA'::text
    WHEN 'sqm'::text THEN 'AREA'::text
    WHEN 'sqmt'::text THEN 'AREA'::text
    WHEN 'sqmtrs'::text THEN 'AREA'::text
    WHEN 'squarefeet'::text THEN 'AREA'::text
    WHEN 'ton'::text THEN 'CAPACITY'::text
    WHEN 'tons'::text THEN 'CAPACITY'::text
    WHEN 'tr'::text THEN 'CAPACITY'::text
    WHEN 'unit'::text THEN 'COUNT'::text
    WHEN 'units'::text THEN 'COUNT'::text
    ELSE NULL::text
END) STORED` |
| `natural_key` | `character varying(120)` | YES | None |
| `key_basis` | `character varying(16)` | YES | None |
| `key_confidence` | `numeric(4,3)` | YES | None |
| `line_uid` | `uuid` | YES | None |

### Keys and Constraints

- `fk_recon_invoice_lines_charge_type_vocab` - `FOREIGN KEY (charge_type_kind, charge_type) REFERENCES vocab_codes(kind, code)`
- `fk_recon_invoice_lines_line_origin_vocab` - `FOREIGN KEY (line_origin_kind, line_origin) REFERENCES vocab_codes(kind, code)`
- `fk_recon_invoice_lines_pricing_basis_vocab` - `FOREIGN KEY (pricing_basis_kind, pricing_basis) REFERENCES vocab_codes(kind, code)`
- `fk_recon_invoice_lines_uom_family_vocab` - `FOREIGN KEY (uom_family_kind, uom_family) REFERENCES vocab_codes(kind, code)`
- `fk_recon_invoice_lines_uom_vocab` - `FOREIGN KEY (uom_kind, uom) REFERENCES vocab_codes(kind, code)`
- `recon_invoice_lines_pkey` - `PRIMARY KEY (id)`
- `recon_invoice_lines_segment_id_fkey` - `FOREIGN KEY (segment_id) REFERENCES recon_doc_segments(id) ON DELETE CASCADE`

### Indexes

- `idx_rinv_seg` - `CREATE INDEX idx_rinv_seg ON public.recon_invoice_lines USING btree (segment_id)`
- `idx_rinv_uid` - `CREATE INDEX idx_rinv_uid ON public.recon_invoice_lines USING btree (line_uid)`
- `recon_invoice_lines_pkey` - `CREATE UNIQUE INDEX recon_invoice_lines_pkey ON public.recon_invoice_lines USING btree (id)`

---

## Table: `recon_line_identity`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `line_uid` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `doc_id` | `uuid` | NO | None |
| `leg` | `character varying(16)` | NO | None |
| `natural_key` | `character varying(120)` | NO | None |
| `key_basis` | `character varying(16)` | NO | None |
| `key_confidence` | `numeric(4,3)` | NO | None |
| `first_seen_at` | `timestamp with time zone` | NO | `now()` |
| `last_seen_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `recon_line_identity_doc_id_fkey` - `FOREIGN KEY (doc_id) REFERENCES vendor_documents(id) ON DELETE CASCADE`
- `recon_line_identity_pkey` - `PRIMARY KEY (line_uid)`
- `recon_line_identity_tenant_id_doc_id_leg_natural_key_key` - `UNIQUE (tenant_id, doc_id, leg, natural_key)`

### Indexes

- `idx_rlid_doc` - `CREATE INDEX idx_rlid_doc ON public.recon_line_identity USING btree (tenant_id, doc_id)`
- `recon_line_identity_pkey` - `CREATE UNIQUE INDEX recon_line_identity_pkey ON public.recon_line_identity USING btree (line_uid)`
- `recon_line_identity_tenant_id_doc_id_leg_natural_key_key` - `CREATE UNIQUE INDEX recon_line_identity_tenant_id_doc_id_leg_natural_key_key ON public.recon_line_identity USING btree (tenant_id, doc_id, leg, natural_key)`

---

## Table: `recon_line_results`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `case_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `ord` | `integer` | NO | None |
| `kind` | `character varying(12)` | NO | None |
| `line_key` | `character varying(200)` | NO | None |
| `po_line_key` | `character varying(80)` | YES | None |
| `invoice_line_key` | `character varying(80)` | YES | None |
| `evidence_row_key` | `character varying(80)` | YES | None |
| `result` | `jsonb` | NO | None |
| `severity` | `character varying(8)` | NO | None |
| `statuses` | `character varying(24)[]` | NO | None |
| `reviewed_by` | `character varying(100)` | YES | None |
| `reviewed_at` | `timestamp with time zone` | YES | None |
| `reviewed_note` | `text` | YES | None |
| `outcome_kind` | `text` | YES | `GENERATED ALWAYS AS ('recon_outcome'::text) STORED` |
| `outcome` | `text` | YES | `GENERATED ALWAYS AS (
CASE severity
    WHEN 'BLOCKER'::text THEN 'FAIL'::text
    WHEN 'INFO'::text THEN 'WARN'::text
    WHEN 'OK'::text THEN 'PASS'::text
    WHEN 'REVIEW'::text THEN 'HOLD'::text
    ELSE NULL::text
END) STORED` |

### Keys and Constraints

- `fk_recon_line_results_outcome_vocab` - `FOREIGN KEY (outcome_kind, outcome) REFERENCES vocab_codes(kind, code)`
- `recon_line_results_case_id_fkey` - `FOREIGN KEY (case_id) REFERENCES recon_cases(id) ON DELETE CASCADE`
- `recon_line_results_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_rlr_case` - `CREATE INDEX idx_rlr_case ON public.recon_line_results USING btree (case_id, ord)`
- `recon_line_results_pkey` - `CREATE UNIQUE INDEX recon_line_results_pkey ON public.recon_line_results USING btree (id)`

---

## Table: `recon_match_overrides`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `case_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `po_line_key` | `character varying(80)` | YES | None |
| `other_key` | `character varying(80)` | NO | None |
| `decided_by` | `character varying(100)` | NO | None |
| `decided_at` | `timestamp with time zone` | YES | `now()` |

### Keys and Constraints

- `recon_match_overrides_case_id_fkey` - `FOREIGN KEY (case_id) REFERENCES recon_cases(id) ON DELETE CASCADE`
- `recon_match_overrides_pkey` - `PRIMARY KEY (case_id, other_key)`

### Indexes

- `recon_match_overrides_pkey` - `CREATE UNIQUE INDEX recon_match_overrides_pkey ON public.recon_match_overrides USING btree (case_id, other_key)`

---

## Table: `remitter_accounts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `account_number` | `text` | NO | None |
| `bank_name` | `text` | NO | None |
| `ifsc` | `text` | YES | None |
| `bank_provider` | `text` | NO | `'ICICI'::text` |
| `balance` | `numeric` | NO | `5000000` |
| `notify_email` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `nbfc_name` | `text` | YES | None |

### Keys and Constraints

- `remitter_accounts_pkey` - `PRIMARY KEY (id)`
- `remitter_accounts_tenant_id_account_number_key` - `UNIQUE (tenant_id, account_number)`

### Indexes

- `remitter_accounts_pkey` - `CREATE UNIQUE INDEX remitter_accounts_pkey ON public.remitter_accounts USING btree (id)`
- `remitter_accounts_tenant_id_account_number_key` - `CREATE UNIQUE INDEX remitter_accounts_tenant_id_account_number_key ON public.remitter_accounts USING btree (tenant_id, account_number)`

---

## Table: `rh_audit_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `audit_id` | `bigint` | NO | `nextval('rh_audit_log_audit_id_seq'::regclass)` |
| `tenant_id` | `uuid` | YES | None |
| `actor` | `text` | YES | None |
| `actor_role` | `text` | YES | None |
| `finding_id` | `uuid` | YES | None |
| `surface` | `text` | YES | None |
| `method` | `text` | NO | None |
| `path` | `text` | NO | None |
| `entity_type` | `text` | YES | None |
| `entity_id` | `text` | YES | None |
| `request_body` | `jsonb` | NO | `'{}'::jsonb` |
| `changes` | `jsonb` | NO | `'{}'::jsonb` |
| `status_code` | `integer` | YES | None |
| `request_id` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `rh_audit_log_pkey` - `PRIMARY KEY (audit_id)`

### Indexes

- `rh_audit_log_finding` - `CREATE INDEX rh_audit_log_finding ON public.rh_audit_log USING btree (finding_id, created_at DESC)`
- `rh_audit_log_pkey` - `CREATE UNIQUE INDEX rh_audit_log_pkey ON public.rh_audit_log USING btree (audit_id)`
- `rh_audit_log_tenant_time` - `CREATE INDEX rh_audit_log_tenant_time ON public.rh_audit_log USING btree (tenant_id, created_at DESC)`

---

## Table: `rh_finding_entities`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `finding_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `entity_type` | `text` | NO | None |
| `entity_id` | `uuid` | NO | None |
| `entity_role` | `text` | NO | `'related'::text` |
| `label` | `text` | YES | None |

### Keys and Constraints

- `rh_finding_entities_entity_role_check` - `CHECK ((entity_role = ANY (ARRAY['subject'::text, 'related'::text, 'counterparty'::text, 'evidence'::text])))`
- `rh_finding_entities_finding_id_fkey` - `FOREIGN KEY (finding_id) REFERENCES rh_findings(finding_id) ON DELETE CASCADE`
- `rh_finding_entities_pkey` - `PRIMARY KEY (finding_id, entity_type, entity_id)`

### Indexes

- `idx_rh_fe_entity` - `CREATE INDEX idx_rh_fe_entity ON public.rh_finding_entities USING btree (tenant_id, entity_type, entity_id)`
- `rh_finding_entities_pkey` - `CREATE UNIQUE INDEX rh_finding_entities_pkey ON public.rh_finding_entities USING btree (finding_id, entity_type, entity_id)`

---

## Table: `rh_finding_events`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `event_id` | `bigint` | NO | `nextval('rh_finding_events_event_id_seq'::regclass)` |
| `finding_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `event_type` | `text` | NO | None |
| `actor` | `text` | YES | None |
| `reason` | `text` | YES | None |
| `payload_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `rh_finding_events_event_type_check` - `CHECK ((event_type = ANY (ARRAY['DETECTED'::text, 'REDETECTED'::text, 'VIEWED'::text, 'ACKNOWLEDGED'::text, 'SNOOZED'::text, 'OPEN'::text, 'RESOLVED'::text, 'DISMISSED'::text, 'AUTO_RESOLVED'::text, 'ACTION_EXECUTED'::text, 'COMMENT'::text, 'RERANKED'::text, 'REFUTED'::text, 'FEEDBACK'::text])))`
- `rh_finding_events_finding_id_fkey` - `FOREIGN KEY (finding_id) REFERENCES rh_findings(finding_id) ON DELETE CASCADE`
- `rh_finding_events_pkey` - `PRIMARY KEY (event_id)`

### Indexes

- `idx_rh_fev_finding` - `CREATE INDEX idx_rh_fev_finding ON public.rh_finding_events USING btree (finding_id, created_at DESC)`
- `idx_rh_fev_label` - `CREATE INDEX idx_rh_fev_label ON public.rh_finding_events USING btree (tenant_id, event_type, created_at DESC) WHERE (event_type = ANY (ARRAY['RESOLVED'::text, 'DISMISSED'::text]))`
- `rh_finding_events_pkey` - `CREATE UNIQUE INDEX rh_finding_events_pkey ON public.rh_finding_events USING btree (event_id)`

---

## Table: `rh_finding_rejects`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `reject_id` | `bigint` | NO | `nextval('rh_finding_rejects_reject_id_seq'::regclass)` |
| `tenant_id` | `uuid` | NO | None |
| `agent_run_id` | `uuid` | YES | None |
| `subject_type` | `text` | YES | None |
| `subject_id` | `uuid` | YES | None |
| `proposed_type` | `text` | YES | None |
| `claim_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `reject_reason` | `text` | NO | None |
| `model` | `text` | YES | None |
| `prompt_version` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `rh_finding_rejects_pkey` - `PRIMARY KEY (reject_id)`

### Indexes

- `idx_rh_rejects_tenant` - `CREATE INDEX idx_rh_rejects_tenant ON public.rh_finding_rejects USING btree (tenant_id, created_at DESC)`
- `rh_finding_rejects_pkey` - `CREATE UNIQUE INDEX rh_finding_rejects_pkey ON public.rh_finding_rejects USING btree (reject_id)`

---

## Table: `rh_finding_types`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `type_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `type_slug` | `text` | NO | None |
| `display_name` | `text` | NO | None |
| `description` | `text` | YES | None |
| `family` | `text` | NO | None |
| `origin` | `text` | NO | None |
| `default_severity` | `severity_level` | NO | `'MEDIUM'::severity_level` |
| `verifier_spec` | `jsonb` | NO | `'{}'::jsonb` |
| `promoted_detector` | `text` | YES | None |
| `status` | `text` | NO | `'ACTIVE'::text` |
| `occurrences` | `integer` | NO | `0` |
| `confirmed_count` | `integer` | NO | `0` |
| `dismissed_count` | `integer` | NO | `0` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `centroid` | `vector(1536)` | YES | None |

### Keys and Constraints

- `rh_finding_types_origin_check` - `CHECK ((origin = ANY (ARRAY['adapter'::text, 'agent'::text, 'promoted'::text, 'manual'::text])))`
- `rh_finding_types_pkey` - `PRIMARY KEY (type_id)`
- `rh_finding_types_status_check` - `CHECK ((status = ANY (ARRAY['ACTIVE'::text, 'SHADOW'::text, 'SUPPRESSED'::text, 'PROMOTED'::text, 'RETIRED'::text])))`
- `rh_finding_types_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `rh_finding_types_tenant_id_type_slug_key` - `UNIQUE (tenant_id, type_slug)`

### Indexes

- `idx_rh_types_centroid` - `CREATE INDEX idx_rh_types_centroid ON public.rh_finding_types USING hnsw (centroid vector_cosine_ops)`
- `rh_finding_types_pkey` - `CREATE UNIQUE INDEX rh_finding_types_pkey ON public.rh_finding_types USING btree (type_id)`
- `rh_finding_types_tenant_id_type_slug_key` - `CREATE UNIQUE INDEX rh_finding_types_tenant_id_type_slug_key ON public.rh_finding_types USING btree (tenant_id, type_slug)`

---

## Table: `rh_findings`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `finding_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `finding_key` | `text` | NO | None |
| `finding_type` | `text` | NO | None |
| `family` | `text` | NO | None |
| `type_id` | `uuid` | YES | None |
| `subject_type` | `text` | NO | None |
| `subject_id` | `uuid` | YES | None |
| `severity` | `severity_level` | NO | None |
| `confidence` | `numeric(4,3)` | NO | `0.500` |
| `verification` | `text` | NO | `'UNVERIFIED'::text` |
| `money_at_risk` | `numeric(18,2)` | YES | None |
| `money_currency` | `character(3)` | NO | `'INR'::bpchar` |
| `money_at_risk_inr` | `numeric(18,2)` | YES | None |
| `due_at` | `timestamp with time zone` | YES | None |
| `rank_score` | `numeric(12,6)` | NO | `0` |
| `title` | `text` | NO | None |
| `detail` | `text` | YES | None |
| `evidence_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `actions_jsonb` | `jsonb` | NO | `'[]'::jsonb` |
| `deep_link` | `text` | NO | None |
| `audience_roles` | `text[]` | NO | `'{}'::text[]` |
| `audience_users` | `text[]` | NO | `'{}'::text[]` |
| `audience_departments` | `text[]` | NO | `'{}'::text[]` |
| `required_capability` | `text` | NO | `'view'::text` |
| `status` | `text` | NO | `'OPEN'::text` |
| `status_reason` | `text` | YES | None |
| `status_by` | `text` | YES | None |
| `status_at` | `timestamp with time zone` | YES | None |
| `snoozed_until` | `timestamp with time zone` | YES | None |
| `resolved_at` | `timestamp with time zone` | YES | None |
| `source_service` | `text` | NO | `'bills'::text` |
| `detector` | `text` | NO | None |
| `detector_version` | `text` | NO | `'v1'::text` |
| `agent_run_id` | `uuid` | YES | None |
| `model` | `text` | YES | None |
| `cost_usd` | `numeric(12,6)` | YES | None |
| `condition_hash` | `text` | NO | None |
| `occurrence_count` | `integer` | NO | `1` |
| `first_detected_at` | `timestamp with time zone` | NO | `now()` |
| `last_seen_at` | `timestamp with time zone` | NO | `now()` |
| `preempted_event_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `fk_rh_findings_type` - `FOREIGN KEY (type_id) REFERENCES rh_finding_types(type_id) ON DELETE SET NULL`
- `rh_findings_confidence_check` - `CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric)))`
- `rh_findings_family_check` - `CHECK ((family = ANY (ARRAY['approval'::text, 'payment'::text, 'vendor_identity'::text, 'tax'::text, 'reconciliation'::text, 'data_quality'::text, 'duplication'::text, 'fx'::text])))`
- `rh_findings_finding_key_check` - `CHECK (((length(finding_key) >= 3) AND (length(finding_key) <= 240)))`
- `rh_findings_finding_type_check` - `CHECK ((finding_type ~ '^[a-z][a-z0-9_]{2,79}$'::text))`
- `rh_findings_pkey` - `PRIMARY KEY (finding_id)`
- `rh_findings_required_capability_check` - `CHECK ((required_capability = ANY (ARRAY['view'::text, 'edit'::text, 'approve'::text, 'verify'::text, 'pay'::text, 'admin'::text])))`
- `rh_findings_status_check` - `CHECK ((status = ANY (ARRAY['OPEN'::text, 'ACKNOWLEDGED'::text, 'SNOOZED'::text, 'RESOLVED'::text, 'DISMISSED'::text, 'AUTO_RESOLVED'::text])))`
- `rh_findings_subject_type_check` - `CHECK ((subject_type = ANY (ARRAY['bill'::text, 'invoice'::text, 'vendor'::text, 'payment'::text, 'disbursement'::text, 'upload'::text, 'line_item'::text, 'gstin'::text, 'bank_account'::text, 'recon_run'::text, 'agent_run'::text, 'tenant'::text])))`
- `rh_findings_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `rh_findings_verification_check` - `CHECK ((verification = ANY (ARRAY['VERIFIED'::text, 'UNVERIFIABLE'::text, 'UNVERIFIED'::text, 'REFUTED'::text])))`

### Indexes

- `idx_rh_findings_archive` - `CREATE INDEX idx_rh_findings_archive ON public.rh_findings USING btree (resolved_at) WHERE (resolved_at IS NOT NULL)`
- `idx_rh_findings_aud_roles` - `CREATE INDEX idx_rh_findings_aud_roles ON public.rh_findings USING gin (audience_roles) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_aud_users` - `CREATE INDEX idx_rh_findings_aud_users ON public.rh_findings USING gin (audience_users) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_counts` - `CREATE INDEX idx_rh_findings_counts ON public.rh_findings USING btree (tenant_id, family, severity) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_lane` - `CREATE INDEX idx_rh_findings_lane ON public.rh_findings USING btree (tenant_id, family, rank_score DESC, finding_id DESC) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_stream` - `CREATE INDEX idx_rh_findings_stream ON public.rh_findings USING btree (tenant_id, rank_score DESC, finding_id DESC) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_subject` - `CREATE INDEX idx_rh_findings_subject ON public.rh_findings USING btree (tenant_id, subject_type, subject_id) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_sweep` - `CREATE INDEX idx_rh_findings_sweep ON public.rh_findings USING btree (tenant_id, detector, last_seen_at) WHERE (resolved_at IS NULL)`
- `idx_rh_findings_type_hist` - `CREATE INDEX idx_rh_findings_type_hist ON public.rh_findings USING btree (tenant_id, finding_type, created_at DESC)`
- `rh_findings_pkey` - `CREATE UNIQUE INDEX rh_findings_pkey ON public.rh_findings USING btree (finding_id)`
- `uq_rh_findings_live_key` - `CREATE UNIQUE INDEX uq_rh_findings_live_key ON public.rh_findings USING btree (tenant_id, finding_key) WHERE (resolved_at IS NULL)`

---

## Table: `rh_review_requests`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `request_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `subject_type` | `text` | NO | None |
| `subject_id` | `uuid` | YES | None |
| `trigger_type` | `text` | NO | None |
| `trigger_ref` | `text` | YES | None |
| `tier` | `text` | NO | `'standard'::text` |
| `idempotency_key` | `text` | NO | None |
| `status` | `text` | NO | `'PENDING'::text` |
| `agent_run_id` | `uuid` | YES | None |
| `error` | `text` | YES | None |
| `requested_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `started_at` | `timestamp with time zone` | YES | None |
| `finished_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `rh_review_requests_pkey` - `PRIMARY KEY (request_id)`
- `rh_review_requests_status_check` - `CHECK ((status = ANY (ARRAY['PENDING'::text, 'RUNNING'::text, 'DONE'::text, 'SKIPPED'::text, 'FAILED'::text])))`
- `rh_review_requests_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `rh_review_requests_tier_check` - `CHECK ((tier = ANY (ARRAY['cheap'::text, 'standard'::text, 'deep'::text])))`
- `rh_review_requests_trigger_type_check` - `CHECK ((trigger_type = ANY (ARRAY['user'::text, 'event'::text, 'schedule'::text, 'sweep'::text])))`

### Indexes

- `idx_rh_req_pending` - `CREATE INDEX idx_rh_req_pending ON public.rh_review_requests USING btree (tenant_id, created_at) WHERE (status = 'PENDING'::text)`
- `rh_review_requests_pkey` - `CREATE UNIQUE INDEX rh_review_requests_pkey ON public.rh_review_requests USING btree (request_id)`
- `uq_rh_req_idem` - `CREATE UNIQUE INDEX uq_rh_req_idem ON public.rh_review_requests USING btree (tenant_id, idempotency_key) WHERE (status = ANY (ARRAY['PENDING'::text, 'RUNNING'::text, 'DONE'::text]))`

---

## Table: `rh_suppressions`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `suppression_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `scope` | `text` | NO | None |
| `finding_key` | `text` | YES | None |
| `finding_type` | `text` | YES | None |
| `subject_type` | `text` | YES | None |
| `subject_id` | `uuid` | YES | None |
| `until` | `timestamp with time zone` | YES | None |
| `reason` | `text` | NO | None |
| `created_by` | `text` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `rh_suppressions_pkey` - `PRIMARY KEY (suppression_id)`
- `rh_suppressions_scope_check` - `CHECK ((scope = ANY (ARRAY['exact_key'::text, 'type_on_subject'::text, 'type_tenant_wide'::text])))`
- `rh_suppressions_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_rh_supp_lookup` - `CREATE INDEX idx_rh_supp_lookup ON public.rh_suppressions USING btree (tenant_id, finding_type, subject_id)`
- `rh_suppressions_pkey` - `CREATE UNIQUE INDEX rh_suppressions_pkey ON public.rh_suppressions USING btree (suppression_id)`

---

## Table: `rh_undo_tokens`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `token` | `text` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `finding_id` | `uuid` | NO | None |
| `prev_state` | `jsonb` | NO | None |
| `created_by` | `text` | NO | None |
| `expires_at` | `timestamp with time zone` | NO | None |
| `used_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `rh_undo_tokens_finding_id_fkey` - `FOREIGN KEY (finding_id) REFERENCES rh_findings(finding_id) ON DELETE CASCADE`
- `rh_undo_tokens_pkey` - `PRIMARY KEY (token)`

### Indexes

- `idx_rh_undo_expiry` - `CREATE INDEX idx_rh_undo_expiry ON public.rh_undo_tokens USING btree (expires_at) WHERE (used_at IS NULL)`
- `rh_undo_tokens_pkey` - `CREATE UNIQUE INDEX rh_undo_tokens_pkey ON public.rh_undo_tokens USING btree (token)`

---

## Table: `sap_item_aliases`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `alias_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `alias_text` | `text` | NO | None |
| `item_code` | `text` | NO | None |
| `source` | `text` | NO | `'operator'::text` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `sap_item_aliases_pkey` - `PRIMARY KEY (alias_id)`
- `sap_item_aliases_tenant_id_alias_text_key` - `UNIQUE (tenant_id, alias_text)`
- `sap_item_aliases_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `sap_item_aliases_pkey` - `CREATE UNIQUE INDEX sap_item_aliases_pkey ON public.sap_item_aliases USING btree (alias_id)`
- `sap_item_aliases_tenant_id_alias_text_key` - `CREATE UNIQUE INDEX sap_item_aliases_tenant_id_alias_text_key ON public.sap_item_aliases USING btree (tenant_id, alias_text)`

---

## Table: `sap_item_catalog`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `catalog_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `item_code` | `text` | NO | None |
| `material_desc` | `text` | NO | None |
| `hsn_code` | `text` | YES | None |
| `embedding_text` | `text` | NO | None |
| `text_hash` | `text` | NO | None |
| `is_active` | `boolean` | NO | `true` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `sap_item_catalog_pkey` - `PRIMARY KEY (catalog_id)`
- `sap_item_catalog_tenant_code_desc_key` - `UNIQUE (tenant_id, item_code, material_desc)`
- `sap_item_catalog_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `sap_item_catalog_tenant_id_item_code_material_desc_key` - `UNIQUE (tenant_id, item_code, material_desc)`

### Indexes

- `idx_sap_catalog_hsn` - `CREATE INDEX idx_sap_catalog_hsn ON public.sap_item_catalog USING btree (tenant_id, hsn_code)`
- `idx_sap_catalog_item` - `CREATE INDEX idx_sap_catalog_item ON public.sap_item_catalog USING btree (tenant_id, item_code)`
- `idx_sap_catalog_tenant` - `CREATE INDEX idx_sap_catalog_tenant ON public.sap_item_catalog USING btree (tenant_id)`
- `sap_item_catalog_pkey` - `CREATE UNIQUE INDEX sap_item_catalog_pkey ON public.sap_item_catalog USING btree (catalog_id)`
- `sap_item_catalog_tenant_code_desc_key` - `CREATE UNIQUE INDEX sap_item_catalog_tenant_code_desc_key ON public.sap_item_catalog USING btree (tenant_id, item_code, material_desc)`
- `sap_item_catalog_tenant_id_item_code_material_desc_key` - `CREATE UNIQUE INDEX sap_item_catalog_tenant_id_item_code_material_desc_key ON public.sap_item_catalog USING btree (tenant_id, item_code, material_desc)`

---

## Table: `sap_item_embeddings`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `catalog_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `model` | `text` | NO | None |
| `dim` | `integer` | NO | None |
| `embedding` | `double precision[]` | NO | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `sap_item_embeddings_catalog_id_fkey` - `FOREIGN KEY (catalog_id) REFERENCES sap_item_catalog(catalog_id) ON DELETE CASCADE`
- `sap_item_embeddings_pkey` - `PRIMARY KEY (catalog_id)`
- `sap_item_embeddings_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`

### Indexes

- `idx_sap_emb_tenant` - `CREATE INDEX idx_sap_emb_tenant ON public.sap_item_embeddings USING btree (tenant_id)`
- `sap_item_embeddings_pkey` - `CREATE UNIQUE INDEX sap_item_embeddings_pkey ON public.sap_item_embeddings USING btree (catalog_id)`

---

## Table: `sap_item_vendors`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `item_code` | `text` | NO | None |
| `vendor_gstn` | `text` | NO | `''::text` |
| `supplier_code` | `text` | NO | None |
| `supplier_name` | `text` | YES | None |
| `freq` | `integer` | NO | `1` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `sap_item_vendors_pkey` - `PRIMARY KEY (id)`
- `sap_item_vendors_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `sap_item_vendors_tenant_id_item_code_vendor_gstn_supplier_c_key` - `UNIQUE (tenant_id, item_code, vendor_gstn, supplier_code)`

### Indexes

- `idx_sap_itemvend_gstn` - `CREATE INDEX idx_sap_itemvend_gstn ON public.sap_item_vendors USING btree (tenant_id, vendor_gstn)`
- `idx_sap_itemvend_item` - `CREATE INDEX idx_sap_itemvend_item ON public.sap_item_vendors USING btree (tenant_id, item_code)`
- `sap_item_vendors_pkey` - `CREATE UNIQUE INDEX sap_item_vendors_pkey ON public.sap_item_vendors USING btree (id)`
- `sap_item_vendors_tenant_id_item_code_vendor_gstn_supplier_c_key` - `CREATE UNIQUE INDEX sap_item_vendors_tenant_id_item_code_vendor_gstn_supplier_c_key ON public.sap_item_vendors USING btree (tenant_id, item_code, vendor_gstn, supplier_code)`

---

## Table: `schema_migrations`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `label` | `text` | NO | None |
| `applied_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `schema_migrations_pkey` - `PRIMARY KEY (label)`

### Indexes

- `schema_migrations_pkey` - `CREATE UNIQUE INDEX schema_migrations_pkey ON public.schema_migrations USING btree (label)`

---

## Table: `service_catalog`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `service_key` | `text` | NO | None |
| `display_name` | `text` | NO | None |
| `description` | `text` | NO | `''::text` |
| `category` | `text` | NO | None |
| `is_core` | `boolean` | NO | `false` |
| `default_enabled` | `boolean` | NO | `false` |
| `metered_unit` | `text` | YES | None |
| `sort_order` | `integer` | NO | `0` |
| `retired_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `service_catalog_pkey` - `PRIMARY KEY (service_key)`

### Indexes

- `service_catalog_pkey` - `CREATE UNIQUE INDEX service_catalog_pkey ON public.service_catalog USING btree (service_key)`

---

## Table: `service_package`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `package_id` | `uuid` | NO | `gen_random_uuid()` |
| `key` | `text` | NO | None |
| `name` | `text` | NO | None |
| `description` | `text` | NO | `''::text` |
| `is_active` | `boolean` | NO | `true` |
| `sort_order` | `integer` | NO | `0` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `service_package_key_key` - `UNIQUE (key)`
- `service_package_pkey` - `PRIMARY KEY (package_id)`

### Indexes

- `service_package_key_key` - `CREATE UNIQUE INDEX service_package_key_key ON public.service_package USING btree (key)`
- `service_package_pkey` - `CREATE UNIQUE INDEX service_package_pkey ON public.service_package USING btree (package_id)`

---

## Table: `service_package_item`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `package_id` | `uuid` | NO | None |
| `service_key` | `text` | NO | None |
| `enabled` | `boolean` | NO | `true` |
| `limits` | `jsonb` | NO | `'{}'::jsonb` |

### Keys and Constraints

- `service_package_item_package_id_fkey` - `FOREIGN KEY (package_id) REFERENCES service_package(package_id) ON DELETE CASCADE`
- `service_package_item_pkey` - `PRIMARY KEY (package_id, service_key)`
- `service_package_item_service_key_fkey` - `FOREIGN KEY (service_key) REFERENCES service_catalog(service_key)`

### Indexes

- `service_package_item_pkey` - `CREATE UNIQUE INDEX service_package_item_pkey ON public.service_package_item USING btree (package_id, service_key)`

---

## Table: `stg_bank_statements`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `stg_statement_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_txn_id` | `text` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `bank_account_id` | `uuid` | YES | None |
| `transaction_date` | `date` | NO | None |
| `value_date` | `date` | YES | None |
| `description` | `text` | YES | None |
| `credit_amount` | `numeric(18,4)` | NO | `0` |
| `debit_amount` | `numeric(18,4)` | NO | `0` |
| `running_balance` | `numeric(18,4)` | YES | None |
| `reference` | `text` | YES | None |
| `is_reconciled` | `boolean` | NO | `false` |
| `stg_payment_id` | `uuid` | YES | None |
| `sync_status` | `sync_status` | NO | `'PENDING'::sync_status` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `stg_bank_statements_bank_account_id_fkey` - `FOREIGN KEY (bank_account_id) REFERENCES dim_bank_accounts(bank_account_id) ON DELETE SET NULL`
- `stg_bank_statements_pkey` - `PRIMARY KEY (stg_statement_id)`
- `stg_bank_statements_stg_payment_id_fkey` - `FOREIGN KEY (stg_payment_id) REFERENCES stg_payments(stg_payment_id) ON DELETE SET NULL`
- `stg_bank_statements_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `uq_stg_bank_stmt_source` - `UNIQUE (tenant_id, source, source_txn_id)`

### Indexes

- `idx_stg_stmt_bank` - `CREATE INDEX idx_stg_stmt_bank ON public.stg_bank_statements USING btree (bank_account_id)`
- `idx_stg_stmt_reconciled` - `CREATE INDEX idx_stg_stmt_reconciled ON public.stg_bank_statements USING btree (is_reconciled)`
- `stg_bank_statements_pkey` - `CREATE UNIQUE INDEX stg_bank_statements_pkey ON public.stg_bank_statements USING btree (stg_statement_id)`
- `uq_stg_bank_stmt_source` - `CREATE UNIQUE INDEX uq_stg_bank_stmt_source ON public.stg_bank_statements USING btree (tenant_id, source, source_txn_id)`

---

## Table: `stg_bill_line_items`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `line_item_id` | `uuid` | NO | `gen_random_uuid()` |
| `stg_bill_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `line_number` | `smallint` | NO | None |
| `product_id` | `uuid` | YES | None |
| `product_name` | `text` | NO | None |
| `hsn_code` | `text` | YES | None |
| `quantity` | `numeric(18,4)` | YES | None |
| `unit` | `text` | YES | None |
| `unit_price` | `numeric(18,4)` | YES | None |
| `discount_amount` | `numeric(18,4)` | NO | `0` |
| `tax_rate_percent` | `numeric(6,3)` | NO | `0` |
| `tax_amount` | `numeric(18,4)` | NO | `0` |
| `line_total` | `numeric(18,4)` | NO | None |
| `cost_centre_id` | `uuid` | YES | None |
| `account_id` | `uuid` | YES | None |
| `sap_item_code` | `text` | YES | None |
| `sap_material_desc` | `text` | YES | None |
| `sap_map_score` | `numeric(5,4)` | YES | None |
| `sap_map_status` | `text` | YES | None |
| `service_month` | `text` | YES | None |
| `rate_is_percent` | `boolean` | NO | `false` |

### Keys and Constraints

- `stg_bill_line_items_account_id_fkey` - `FOREIGN KEY (account_id) REFERENCES dim_ledger_accounts(account_id) ON DELETE SET NULL`
- `stg_bill_line_items_cost_centre_id_fkey` - `FOREIGN KEY (cost_centre_id) REFERENCES dim_cost_centres(cost_centre_id) ON DELETE SET NULL`
- `stg_bill_line_items_pkey` - `PRIMARY KEY (line_item_id)`
- `stg_bill_line_items_product_id_fkey` - `FOREIGN KEY (product_id) REFERENCES dim_products(product_id) ON DELETE SET NULL`
- `stg_bill_line_items_stg_bill_id_fkey` - `FOREIGN KEY (stg_bill_id) REFERENCES stg_bills(stg_bill_id) ON DELETE CASCADE`
- `stg_bill_line_items_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `stg_bill_line_items_pkey` - `CREATE UNIQUE INDEX stg_bill_line_items_pkey ON public.stg_bill_line_items USING btree (line_item_id)`

---

## Table: `stg_bills`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `stg_bill_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_bill_id` | `text` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `raw_payload_id` | `uuid` | YES | None |
| `bill_number` | `text` | NO | None |
| `bill_date` | `date` | NO | None |
| `due_date` | `date` | YES | None |
| `supplier_id` | `uuid` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `subtotal` | `numeric(18,4)` | NO | `0` |
| `discount_amount` | `numeric(18,4)` | NO | `0` |
| `tax_amount` | `numeric(18,4)` | NO | `0` |
| `total_amount` | `numeric(18,4)` | NO | None |
| `amount_paid` | `numeric(18,4)` | NO | `0` |
| `outstanding_amount` | `numeric(18,4)` | YES | None |
| `status` | `invoice_status` | NO | `'DRAFT'::invoice_status` |
| `gstin_seller` | `character(15)` | YES | None |
| `validation_flag` | `validation_flag` | NO | `'OK'::validation_flag` |
| `sync_status` | `sync_status` | NO | `'PENDING'::sync_status` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `upload_id` | `uuid` | YES | None |
| `category` | `character varying(100)` | YES | None |
| `tds_section_code` | `text` | YES | None |
| `tds_rate_percent` | `numeric(5,2)` | YES | None |
| `tds_base_amount` | `numeric(14,2)` | YES | None |
| `tds_amount` | `numeric(14,2)` | YES | None |
| `net_payable` | `numeric(14,2)` | YES | None |
| `tds_status` | `text` | YES | `'PENDING'::text` |
| `tds_section_id` | `uuid` | YES | None |
| `tds_rate` | `numeric(6,3)` | YES | None |
| `original_amount` | `numeric(18,2)` | YES | None |
| `fx_rate_id` | `uuid` | YES | None |
| `vendor_sap_code` | `text` | YES | None |
| `service_month` | `text` | YES | None |
| `cgst_amount` | `numeric(18,2)` | YES | None |
| `sgst_amount` | `numeric(18,2)` | YES | None |
| `igst_amount` | `numeric(18,2)` | YES | None |
| `cess_amount` | `numeric(18,2)` | YES | None |
| `cgst_rate` | `numeric(18,2)` | YES | None |
| `sgst_rate` | `numeric(18,2)` | YES | None |
| `igst_rate` | `numeric(18,2)` | YES | None |
| `taxable_amount` | `numeric(18,2)` | YES | None |
| `place_of_supply` | `text` | YES | None |

### Keys and Constraints

- `stg_bills_fx_rate_id_fkey` - `FOREIGN KEY (fx_rate_id) REFERENCES dim_fx_rates(rate_id)`
- `stg_bills_pkey` - `PRIMARY KEY (stg_bill_id)`
- `stg_bills_raw_payload_id_fkey` - `FOREIGN KEY (raw_payload_id) REFERENCES raw_api_payloads(payload_id) ON DELETE SET NULL`
- `stg_bills_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id) ON DELETE RESTRICT`
- `stg_bills_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `stg_bills_upload_id_fkey` - `FOREIGN KEY (upload_id) REFERENCES raw_invoice_uploads(upload_id)`
- `uq_stg_bill_source` - `UNIQUE (tenant_id, source, source_bill_id)`

### Indexes

- `idx_stg_bill_status` - `CREATE INDEX idx_stg_bill_status ON public.stg_bills USING btree (status)`
- `idx_stg_bill_supplier` - `CREATE INDEX idx_stg_bill_supplier ON public.stg_bills USING btree (supplier_id)`
- `idx_stg_bill_tenant` - `CREATE INDEX idx_stg_bill_tenant ON public.stg_bills USING btree (tenant_id)`
- `idx_stg_bills_supplier` - `CREATE INDEX idx_stg_bills_supplier ON public.stg_bills USING btree (tenant_id, supplier_id)`
- `idx_stg_bills_tenant_status` - `CREATE INDEX idx_stg_bills_tenant_status ON public.stg_bills USING btree (tenant_id, status)`
- `stg_bills_pkey` - `CREATE UNIQUE INDEX stg_bills_pkey ON public.stg_bills USING btree (stg_bill_id)`
- `uq_stg_bill_source` - `CREATE UNIQUE INDEX uq_stg_bill_source ON public.stg_bills USING btree (tenant_id, source, source_bill_id)`

---

## Table: `stg_credit_notes`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `stg_credit_note_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_cn_id` | `text` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `raw_payload_id` | `uuid` | YES | None |
| `stg_invoice_id` | `uuid` | YES | None |
| `credit_note_number` | `text` | NO | None |
| `credit_note_date` | `date` | NO | None |
| `end_customer_id` | `uuid` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `amount` | `numeric(18,4)` | NO | None |
| `reason` | `text` | YES | None |
| `status` | `invoice_status` | NO | `'DRAFT'::invoice_status` |
| `sync_status` | `sync_status` | NO | `'PENDING'::sync_status` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `stg_credit_notes_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `stg_credit_notes_pkey` - `PRIMARY KEY (stg_credit_note_id)`
- `stg_credit_notes_raw_payload_id_fkey` - `FOREIGN KEY (raw_payload_id) REFERENCES raw_api_payloads(payload_id) ON DELETE SET NULL`
- `stg_credit_notes_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE SET NULL`
- `stg_credit_notes_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `uq_stg_cn_source` - `UNIQUE (tenant_id, source, source_cn_id)`

### Indexes

- `stg_credit_notes_pkey` - `CREATE UNIQUE INDEX stg_credit_notes_pkey ON public.stg_credit_notes USING btree (stg_credit_note_id)`
- `uq_stg_cn_source` - `CREATE UNIQUE INDEX uq_stg_cn_source ON public.stg_credit_notes USING btree (tenant_id, source, source_cn_id)`

---

## Table: `stg_invoice_line_items`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `line_item_id` | `uuid` | NO | `gen_random_uuid()` |
| `stg_invoice_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `line_number` | `smallint` | NO | None |
| `product_id` | `uuid` | YES | None |
| `product_name` | `text` | NO | None |
| `hsn_code` | `text` | YES | None |
| `description` | `text` | YES | None |
| `quantity` | `numeric(18,4)` | NO | None |
| `unit` | `text` | YES | None |
| `unit_price` | `numeric(18,4)` | NO | None |
| `discount_percent` | `numeric(6,3)` | NO | `0` |
| `discount_amount` | `numeric(18,4)` | NO | `0` |
| `tax_rate_id` | `uuid` | YES | None |
| `tax_rate_percent` | `numeric(6,3)` | NO | `0` |
| `tax_amount` | `numeric(18,4)` | NO | `0` |
| `line_total` | `numeric(18,4)` | NO | None |
| `cost_centre_id` | `uuid` | YES | None |

### Keys and Constraints

- `stg_invoice_line_items_cost_centre_id_fkey` - `FOREIGN KEY (cost_centre_id) REFERENCES dim_cost_centres(cost_centre_id) ON DELETE SET NULL`
- `stg_invoice_line_items_pkey` - `PRIMARY KEY (line_item_id)`
- `stg_invoice_line_items_product_id_fkey` - `FOREIGN KEY (product_id) REFERENCES dim_products(product_id) ON DELETE SET NULL`
- `stg_invoice_line_items_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE CASCADE`
- `stg_invoice_line_items_tax_rate_id_fkey` - `FOREIGN KEY (tax_rate_id) REFERENCES dim_tax_rates(tax_rate_id) ON DELETE SET NULL`
- `stg_invoice_line_items_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `stg_invoice_line_items_pkey` - `CREATE UNIQUE INDEX stg_invoice_line_items_pkey ON public.stg_invoice_line_items USING btree (line_item_id)`

---

## Table: `stg_invoices`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `stg_invoice_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_invoice_id` | `text` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `raw_payload_id` | `uuid` | YES | None |
| `raw_webhook_event_id` | `uuid` | YES | None |
| `upload_id` | `uuid` | YES | None |
| `invoice_number` | `text` | NO | None |
| `invoice_date` | `date` | NO | None |
| `due_date` | `date` | YES | None |
| `end_customer_id` | `uuid` | NO | None |
| `account_id` | `uuid` | YES | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `subtotal` | `numeric(18,4)` | NO | `0` |
| `discount_amount` | `numeric(18,4)` | NO | `0` |
| `tax_amount` | `numeric(18,4)` | NO | `0` |
| `total_amount` | `numeric(18,4)` | NO | None |
| `amount_paid` | `numeric(18,4)` | NO | `0` |
| `outstanding_amount` | `numeric(18,4)` | YES | None |
| `status` | `invoice_status` | NO | `'DRAFT'::invoice_status` |
| `gstin_seller` | `character(15)` | YES | None |
| `gstin_buyer` | `character(15)` | YES | None |
| `place_of_supply` | `text` | YES | None |
| `reverse_charge` | `boolean` | NO | `false` |
| `validation_flag` | `validation_flag` | NO | `'OK'::validation_flag` |
| `ocr_confidence` | `numeric(5,2)` | YES | None |
| `ocr_engine_used` | `ocr_engine` | YES | None |
| `sync_status` | `sync_status` | NO | `'PENDING'::sync_status` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `narration` | `text` | YES | None |
| `tcs_section_code` | `text` | YES | None |
| `tcs_rate_percent` | `numeric(5,2)` | YES | None |
| `tcs_amount` | `numeric(14,2)` | YES | None |
| `tds_section_id` | `uuid` | YES | None |
| `tds_rate` | `numeric(6,3)` | YES | None |
| `tds_amount` | `numeric(14,2)` | YES | `0` |
| `tds_base_amount` | `numeric(14,2)` | YES | None |
| `tds_status` | `text` | YES | `'PENDING'::text` |
| `original_amount` | `numeric(18,2)` | YES | None |
| `fx_rate_id` | `uuid` | YES | None |

### Keys and Constraints

- `stg_invoices_account_id_fkey` - `FOREIGN KEY (account_id) REFERENCES dim_ledger_accounts(account_id) ON DELETE SET NULL`
- `stg_invoices_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `stg_invoices_fx_rate_id_fkey` - `FOREIGN KEY (fx_rate_id) REFERENCES dim_fx_rates(rate_id)`
- `stg_invoices_pkey` - `PRIMARY KEY (stg_invoice_id)`
- `stg_invoices_raw_payload_id_fkey` - `FOREIGN KEY (raw_payload_id) REFERENCES raw_api_payloads(payload_id) ON DELETE SET NULL`
- `stg_invoices_raw_webhook_event_id_fkey` - `FOREIGN KEY (raw_webhook_event_id) REFERENCES raw_webhook_events(event_id) ON DELETE SET NULL`
- `stg_invoices_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `stg_invoices_upload_id_fkey` - `FOREIGN KEY (upload_id) REFERENCES raw_invoice_uploads(upload_id) ON DELETE SET NULL`
- `uq_stg_invoice_source` - `UNIQUE (tenant_id, source, source_invoice_id)`

### Indexes

- `idx_stg_inv_customer` - `CREATE INDEX idx_stg_inv_customer ON public.stg_invoices USING btree (end_customer_id)`
- `idx_stg_inv_due` - `CREATE INDEX idx_stg_inv_due ON public.stg_invoices USING btree (due_date)`
- `idx_stg_inv_status` - `CREATE INDEX idx_stg_inv_status ON public.stg_invoices USING btree (status)`
- `idx_stg_inv_sync` - `CREATE INDEX idx_stg_inv_sync ON public.stg_invoices USING btree (sync_status)`
- `idx_stg_inv_tenant` - `CREATE INDEX idx_stg_inv_tenant ON public.stg_invoices USING btree (tenant_id)`
- `stg_invoices_pkey` - `CREATE UNIQUE INDEX stg_invoices_pkey ON public.stg_invoices USING btree (stg_invoice_id)`
- `uq_stg_invoice_source` - `CREATE UNIQUE INDEX uq_stg_invoice_source ON public.stg_invoices USING btree (tenant_id, source, source_invoice_id)`

---

## Table: `stg_journal_entries`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `stg_journal_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_journal_id` | `text` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `raw_payload_id` | `uuid` | YES | None |
| `journal_number` | `text` | YES | None |
| `journal_date` | `date` | NO | None |
| `narration` | `text` | YES | None |
| `total_debit` | `numeric(18,4)` | NO | `0` |
| `total_credit` | `numeric(18,4)` | NO | `0` |
| `is_balanced` | `boolean` | YES | None |
| `sync_status` | `sync_status` | NO | `'PENDING'::sync_status` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `stg_journal_entries_pkey` - `PRIMARY KEY (stg_journal_id)`
- `stg_journal_entries_raw_payload_id_fkey` - `FOREIGN KEY (raw_payload_id) REFERENCES raw_api_payloads(payload_id) ON DELETE SET NULL`
- `stg_journal_entries_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `uq_stg_journal_source` - `UNIQUE (tenant_id, source, source_journal_id)`

### Indexes

- `stg_journal_entries_pkey` - `CREATE UNIQUE INDEX stg_journal_entries_pkey ON public.stg_journal_entries USING btree (stg_journal_id)`
- `uq_stg_journal_source` - `CREATE UNIQUE INDEX uq_stg_journal_source ON public.stg_journal_entries USING btree (tenant_id, source, source_journal_id)`

---

## Table: `stg_journal_entry_lines`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `entry_line_id` | `uuid` | NO | `gen_random_uuid()` |
| `stg_journal_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `line_number` | `smallint` | NO | None |
| `account_id` | `uuid` | NO | None |
| `cost_centre_id` | `uuid` | YES | None |
| `debit_amount` | `numeric(18,4)` | NO | `0` |
| `credit_amount` | `numeric(18,4)` | NO | `0` |
| `narration` | `text` | YES | None |

### Keys and Constraints

- `stg_journal_entry_lines_account_id_fkey` - `FOREIGN KEY (account_id) REFERENCES dim_ledger_accounts(account_id) ON DELETE RESTRICT`
- `stg_journal_entry_lines_cost_centre_id_fkey` - `FOREIGN KEY (cost_centre_id) REFERENCES dim_cost_centres(cost_centre_id) ON DELETE SET NULL`
- `stg_journal_entry_lines_pkey` - `PRIMARY KEY (entry_line_id)`
- `stg_journal_entry_lines_stg_journal_id_fkey` - `FOREIGN KEY (stg_journal_id) REFERENCES stg_journal_entries(stg_journal_id) ON DELETE CASCADE`
- `stg_journal_entry_lines_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `stg_journal_entry_lines_pkey` - `CREATE UNIQUE INDEX stg_journal_entry_lines_pkey ON public.stg_journal_entry_lines USING btree (entry_line_id)`

---

## Table: `stg_payments`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `stg_payment_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `source` | `data_source` | NO | None |
| `source_payment_id` | `text` | NO | None |
| `source_updated_at` | `timestamp with time zone` | NO | None |
| `stg_invoice_id` | `uuid` | YES | None |
| `end_customer_id` | `uuid` | NO | None |
| `bank_account_id` | `uuid` | YES | None |
| `payment_date` | `date` | NO | None |
| `amount` | `numeric(18,4)` | NO | None |
| `currency_code` | `character(3)` | NO | `'INR'::bpchar` |
| `payment_method` | `payment_method` | YES | None |
| `transaction_ref` | `text` | YES | None |
| `gateway` | `text` | YES | None |
| `status` | `payment_status` | NO | `'PENDING'::payment_status` |
| `is_reconciled` | `boolean` | NO | `false` |
| `sync_status` | `sync_status` | NO | `'PENDING'::sync_status` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `stg_payments_bank_account_id_fkey` - `FOREIGN KEY (bank_account_id) REFERENCES dim_bank_accounts(bank_account_id) ON DELETE SET NULL`
- `stg_payments_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE RESTRICT`
- `stg_payments_pkey` - `PRIMARY KEY (stg_payment_id)`
- `stg_payments_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE SET NULL`
- `stg_payments_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`
- `uq_stg_payment_source` - `UNIQUE (tenant_id, source, source_payment_id)`

### Indexes

- `stg_payments_pkey` - `CREATE UNIQUE INDEX stg_payments_pkey ON public.stg_payments USING btree (stg_payment_id)`
- `uq_stg_payment_source` - `CREATE UNIQUE INDEX uq_stg_payment_source ON public.stg_payments USING btree (tenant_id, source, source_payment_id)`

---

## Table: `supplier_bank_accounts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `account_number` | `text` | NO | None |
| `ifsc` | `text` | YES | None |
| `bank_name` | `text` | YES | None |
| `is_primary` | `boolean` | NO | `false` |
| `verified` | `boolean` | NO | `false` |
| `name_at_bank` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `supplier_bank_accounts_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_sba_supplier_primary` - `CREATE INDEX idx_sba_supplier_primary ON public.supplier_bank_accounts USING btree (supplier_id, is_primary)`
- `idx_sba_tenant_supplier` - `CREATE INDEX idx_sba_tenant_supplier ON public.supplier_bank_accounts USING btree (tenant_id, supplier_id)`
- `supplier_bank_accounts_pkey` - `CREATE UNIQUE INDEX supplier_bank_accounts_pkey ON public.supplier_bank_accounts USING btree (id)`

---

## Table: `supplier_contacts`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `name` | `text` | NO | None |
| `role` | `text` | YES | None |
| `email` | `text` | YES | None |
| `phone` | `text` | YES | None |
| `is_primary` | `boolean` | NO | `false` |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `agent_enabled` | `boolean` | NO | `false` |

### Keys and Constraints

- `supplier_contacts_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_sc_tenant_supplier` - `CREATE INDEX idx_sc_tenant_supplier ON public.supplier_contacts USING btree (tenant_id, supplier_id)`
- `supplier_contacts_pkey` - `CREATE UNIQUE INDEX supplier_contacts_pkey ON public.supplier_contacts USING btree (id)`

---

## Table: `supplier_gstins`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `supplier_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `gstin` | `text` | NO | None |
| `pan` | `text` | YES | None |
| `is_primary` | `boolean` | NO | `false` |
| `status` | `text` | NO | `'UNVERIFIED'::text` |
| `trade_name` | `text` | YES | None |
| `legal_name` | `text` | YES | None |
| `gstin_status` | `text` | YES | None |
| `error_message` | `text` | YES | None |
| `verified_at` | `timestamp with time zone` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `supplier_gstins_pkey` - `PRIMARY KEY (id)`
- `supplier_gstins_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id) ON DELETE CASCADE`
- `supplier_gstins_supplier_id_gstin_key` - `UNIQUE (supplier_id, gstin)`

### Indexes

- `idx_supplier_gstins_supplier` - `CREATE INDEX idx_supplier_gstins_supplier ON public.supplier_gstins USING btree (supplier_id)`
- `supplier_gstins_pkey` - `CREATE UNIQUE INDEX supplier_gstins_pkey ON public.supplier_gstins USING btree (id)`
- `supplier_gstins_supplier_id_gstin_key` - `CREATE UNIQUE INDEX supplier_gstins_supplier_id_gstin_key ON public.supplier_gstins USING btree (supplier_id, gstin)`

---

## Table: `supplier_gstns`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `gstn` | `character(15)` | NO | None |
| `label` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `supplier_gstns_pkey` - `PRIMARY KEY (id)`
- `supplier_gstns_tenant_id_gstn_key` - `UNIQUE (tenant_id, gstn)`

### Indexes

- `idx_sgstns_gstn` - `CREATE INDEX idx_sgstns_gstn ON public.supplier_gstns USING btree (tenant_id, gstn)`
- `idx_sgstns_supplier` - `CREATE INDEX idx_sgstns_supplier ON public.supplier_gstns USING btree (supplier_id)`
- `supplier_gstns_pkey` - `CREATE UNIQUE INDEX supplier_gstns_pkey ON public.supplier_gstns USING btree (id)`
- `supplier_gstns_tenant_id_gstn_key` - `CREATE UNIQUE INDEX supplier_gstns_tenant_id_gstn_key ON public.supplier_gstns USING btree (tenant_id, gstn)`

---

## Table: `tenant_chain_config`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `bigint` | NO | `nextval('tenant_chain_config_id_seq'::regclass)` |
| `tenant_id` | `uuid` | NO | None |
| `step_order` | `smallint` | NO | None |
| `label` | `character varying(100)` | NO | None |
| `role` | `character varying(50)` | NO | None |
| `locked` | `boolean` | YES | `false` |
| `updated_at` | `timestamp with time zone` | YES | `now()` |
| `department` | `character varying(100)` | YES | None |
| `is_snapshot` | `boolean` | YES | `false` |
| `assignees` | `jsonb` | YES | None |

### Keys and Constraints

- `tenant_chain_config_pkey` - `PRIMARY KEY (id)`

### Indexes

- `tenant_chain_config_pkey` - `CREATE UNIQUE INDEX tenant_chain_config_pkey ON public.tenant_chain_config USING btree (id)`
- `tenant_chain_config_unique_idx` - `CREATE UNIQUE INDEX tenant_chain_config_unique_idx ON public.tenant_chain_config USING btree (tenant_id, COALESCE(department, ''::character varying), step_order, is_snapshot)`

---

## Table: `tenant_priority_labels`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `p0` | `character varying(48)` | NO | `'P0'::character varying` |
| `p1` | `character varying(48)` | NO | `'P1'::character varying` |
| `p2` | `character varying(48)` | NO | `'P2'::character varying` |
| `p3` | `character varying(48)` | NO | `'P3'::character varying` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `updated_by` | `character varying(255)` | YES | None |

### Keys and Constraints

- `tenant_priority_labels_pkey` - `PRIMARY KEY (tenant_id)`

### Indexes

- `tenant_priority_labels_pkey` - `CREATE UNIQUE INDEX tenant_priority_labels_pkey ON public.tenant_priority_labels USING btree (tenant_id)`

---

## Table: `tenant_service`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `service_key` | `text` | NO | None |
| `enabled` | `boolean` | NO | `false` |
| `limits` | `jsonb` | NO | `'{}'::jsonb` |
| `config` | `jsonb` | NO | `'{}'::jsonb` |
| `enabled_at` | `timestamp with time zone` | YES | None |
| `disabled_at` | `timestamp with time zone` | YES | None |
| `updated_by` | `uuid` | YES | None |
| `notes` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `tenant_service_pkey` - `PRIMARY KEY (tenant_id, service_key)`
- `tenant_service_service_key_fkey` - `FOREIGN KEY (service_key) REFERENCES service_catalog(service_key)`
- `tenant_service_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_tenant_service_enabled` - `CREATE INDEX idx_tenant_service_enabled ON public.tenant_service USING btree (tenant_id) WHERE enabled`
- `idx_tenant_service_key` - `CREATE INDEX idx_tenant_service_key ON public.tenant_service USING btree (service_key) WHERE enabled`
- `tenant_service_pkey` - `CREATE UNIQUE INDEX tenant_service_pkey ON public.tenant_service USING btree (tenant_id, service_key)`

---

## Table: `tenant_usage`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `service_key` | `text` | NO | None |
| `metric` | `text` | NO | None |
| `period_month` | `date` | NO | None |
| `used` | `numeric` | NO | `0` |
| `last_event_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `tenant_usage_pkey` - `PRIMARY KEY (tenant_id, service_key, metric, period_month)`
- `tenant_usage_service_key_fkey` - `FOREIGN KEY (service_key) REFERENCES service_catalog(service_key)`
- `tenant_usage_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_tenant_usage_period` - `CREATE INDEX idx_tenant_usage_period ON public.tenant_usage USING btree (period_month DESC, tenant_id)`
- `tenant_usage_pkey` - `CREATE UNIQUE INDEX tenant_usage_pkey ON public.tenant_usage USING btree (tenant_id, service_key, metric, period_month)`

---

## Table: `user_email_connections`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `username` | `text` | NO | None |
| `provider` | `text` | NO | `'google'::text` |
| `email` | `text` | NO | None |
| `access_token` | `text` | NO | None |
| `refresh_token` | `text` | YES | None |
| `token_expires_at` | `timestamp with time zone` | YES | None |
| `scopes` | `text` | YES | None |
| `status` | `text` | NO | `'active'::text` |
| `connected_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `agent_last_scan_at` | `timestamp with time zone` | YES | None |

### Keys and Constraints

- `user_email_connections_pkey` - `PRIMARY KEY (id)`
- `user_email_connections_tenant_id_username_provider_key` - `UNIQUE (tenant_id, username, provider)`

### Indexes

- `idx_uec_user` - `CREATE INDEX idx_uec_user ON public.user_email_connections USING btree (tenant_id, username)`
- `user_email_connections_pkey` - `CREATE UNIQUE INDEX user_email_connections_pkey ON public.user_email_connections USING btree (id)`
- `user_email_connections_tenant_id_username_provider_key` - `CREATE UNIQUE INDEX user_email_connections_tenant_id_username_provider_key ON public.user_email_connections USING btree (tenant_id, username, provider)`

---

## Table: `users`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `integer` | NO | `nextval('users_id_seq'::regclass)` |
| `username` | `character varying(50)` | NO | None |
| `password_hash` | `text` | NO | None |
| `role` | `character varying(30)` | NO | None |
| `name` | `character varying(100)` | YES | None |
| `email` | `character varying(100)` | YES | None |
| `company_id` | `uuid` | NO | None |
| `department` | `character varying(100)` | YES | None |

### Keys and Constraints

- `users_pkey` - `PRIMARY KEY (id)`
- `users_username_key` - `UNIQUE (username)`

### Indexes

- `users_pkey` - `CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)`
- `users_username_key` - `CREATE UNIQUE INDEX users_username_key ON public.users USING btree (username)`

---

## Table: `vendor_activity_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `actor` | `text` | YES | None |
| `actor_role` | `text` | YES | None |
| `action` | `text` | NO | None |
| `title` | `text` | NO | None |
| `changes` | `jsonb` | YES | None |
| `meta` | `jsonb` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `vendor_activity_log_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_vendor_activity_log_supplier` - `CREATE INDEX idx_vendor_activity_log_supplier ON public.vendor_activity_log USING btree (tenant_id, supplier_id, created_at DESC)`
- `vendor_activity_log_pkey` - `CREATE UNIQUE INDEX vendor_activity_log_pkey ON public.vendor_activity_log USING btree (id)`

---

## Table: `vendor_doc_rows`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `table_id` | `uuid` | NO | None |
| `doc_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `row_number` | `integer` | NO | None |
| `data` | `jsonb` | NO | None |

### Keys and Constraints

- `vendor_doc_rows_pkey` - `PRIMARY KEY (table_id, row_number)`
- `vendor_doc_rows_table_id_fkey` - `FOREIGN KEY (table_id) REFERENCES vendor_doc_tables(id) ON DELETE CASCADE`

### Indexes

- `idx_vdoc_rows_data` - `CREATE INDEX idx_vdoc_rows_data ON public.vendor_doc_rows USING gin (data jsonb_path_ops)`
- `idx_vdoc_rows_doc` - `CREATE INDEX idx_vdoc_rows_doc ON public.vendor_doc_rows USING btree (doc_id)`
- `idx_vdoc_rows_vendor` - `CREATE INDEX idx_vdoc_rows_vendor ON public.vendor_doc_rows USING btree (tenant_id, supplier_id)`
- `vendor_doc_rows_pkey` - `CREATE UNIQUE INDEX vendor_doc_rows_pkey ON public.vendor_doc_rows USING btree (table_id, row_number)`

---

## Table: `vendor_doc_tables`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `doc_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `sheet_name` | `character varying(255)` | NO | None |
| `sheet_index` | `integer` | NO | None |
| `header_row` | `integer` | YES | None |
| `columns` | `jsonb` | NO | `'[]'::jsonb` |
| `row_count` | `integer` | NO | `0` |
| `truncated` | `boolean` | NO | `false` |
| `parsed_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `vendor_doc_tables_doc_id_fkey` - `FOREIGN KEY (doc_id) REFERENCES vendor_documents(id) ON DELETE CASCADE`
- `vendor_doc_tables_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_vdoc_tables_doc` - `CREATE INDEX idx_vdoc_tables_doc ON public.vendor_doc_tables USING btree (doc_id)`
- `idx_vdoc_tables_vendor` - `CREATE INDEX idx_vdoc_tables_vendor ON public.vendor_doc_tables USING btree (tenant_id, supplier_id)`
- `vendor_doc_tables_pkey` - `CREATE UNIQUE INDEX vendor_doc_tables_pkey ON public.vendor_doc_tables USING btree (id)`

---

## Table: `vendor_documents`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `supplier_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `file_name` | `character varying(255)` | NO | None |
| `file_path` | `text` | NO | None |
| `file_size` | `bigint` | YES | None |
| `uploaded_by` | `character varying(100)` | YES | None |
| `uploaded_at` | `timestamp with time zone` | YES | `now()` |
| `brand_id` | `uuid` | YES | None |
| `claims_status` | `text` | NO | `'PENDING'::text` |
| `claims_error` | `text` | YES | None |
| `doc_type` | `character varying(20)` | NO | `'contract'::character varying` |
| `doc_label` | `character varying(80)` | YES | None |
| `deleted_at` | `timestamp with time zone` | YES | None |
| `deleted_by` | `character varying(100)` | YES | None |
| `data_status` | `character varying(10)` | YES | None |
| `data_error` | `text` | YES | None |
| `recon_status` | `character varying(16)` | YES | None |
| `recon_error` | `text` | YES | None |
| `recon_stage` | `character varying(24)` | YES | None |
| `recon_progress` | `jsonb` | YES | None |
| `recon_started_at` | `timestamp with time zone` | YES | None |
| `content_sha256` | `character(64)` | YES | None |

### Keys and Constraints

- `vendor_documents_claims_status_check` - `CHECK ((claims_status = ANY (ARRAY['PENDING'::text, 'RUNNING'::text, 'DONE'::text, 'SKIPPED'::text, 'FAILED'::text])))`
- `vendor_documents_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_vdoc_claims_pending` - `CREATE INDEX idx_vdoc_claims_pending ON public.vendor_documents USING btree (tenant_id, uploaded_at) WHERE (claims_status = 'PENDING'::text)`
- `idx_vdoc_recon_pending` - `CREATE INDEX idx_vdoc_recon_pending ON public.vendor_documents USING btree (recon_status) WHERE ((recon_status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('RUNNING'::character varying)::text]))`
- `idx_vdoc_sha` - `CREATE INDEX idx_vdoc_sha ON public.vendor_documents USING btree (tenant_id, supplier_id, content_sha256)`
- `idx_vdoc_tenant_label` - `CREATE INDEX idx_vdoc_tenant_label ON public.vendor_documents USING btree (tenant_id, doc_label) WHERE (doc_label IS NOT NULL)`
- `vendor_documents_pkey` - `CREATE UNIQUE INDEX vendor_documents_pkey ON public.vendor_documents USING btree (id)`

---

## Table: `vendor_flow_runs`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `run_id` | `uuid` | NO | `gen_random_uuid()` |
| `flow_id` | `uuid` | YES | None |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `status` | `text` | NO | None |
| `steps` | `jsonb` | YES | None |
| `outputs` | `jsonb` | YES | None |
| `error` | `text` | YES | None |
| `run_by` | `text` | YES | None |
| `started_at` | `timestamp with time zone` | NO | `now()` |
| `finished_at` | `timestamp with time zone` | YES | None |
| `checks` | `jsonb` | YES | None |
| `invoice_id` | `uuid` | YES | None |

### Keys and Constraints

- `vendor_flow_runs_pkey` - `PRIMARY KEY (run_id)`

### Indexes

- `vendor_flow_runs_invoice_idx` - `CREATE INDEX vendor_flow_runs_invoice_idx ON public.vendor_flow_runs USING btree (tenant_id, invoice_id, started_at DESC) WHERE (invoice_id IS NOT NULL)`
- `vendor_flow_runs_pkey` - `CREATE UNIQUE INDEX vendor_flow_runs_pkey ON public.vendor_flow_runs USING btree (run_id)`
- `vendor_flow_runs_vendor_idx` - `CREATE INDEX vendor_flow_runs_vendor_idx ON public.vendor_flow_runs USING btree (tenant_id, supplier_id, started_at DESC)`

---

## Table: `vendor_flows`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `flow_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `name` | `text` | YES | None |
| `graph` | `jsonb` | NO | None |
| `updated_by` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
| `terms` | `jsonb` | NO | `'{}'::jsonb` |

### Keys and Constraints

- `vendor_flows_pkey` - `PRIMARY KEY (flow_id)`
- `vendor_flows_tenant_id_supplier_id_key` - `UNIQUE (tenant_id, supplier_id)`

### Indexes

- `vendor_flows_pkey` - `CREATE UNIQUE INDEX vendor_flows_pkey ON public.vendor_flows USING btree (flow_id)`
- `vendor_flows_tenant_id_supplier_id_key` - `CREATE UNIQUE INDEX vendor_flows_tenant_id_supplier_id_key ON public.vendor_flows USING btree (tenant_id, supplier_id)`

---

## Table: `vendor_item_aliases`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `alias_norm` | `text` | NO | None |
| `po_item_norm` | `text` | NO | None |
| `confirmed_by` | `character varying(100)` | YES | None |
| `created_at` | `timestamp with time zone` | YES | `now()` |
| `hits` | `integer` | NO | `0` |

### Keys and Constraints

- `vendor_item_aliases_pkey` - `PRIMARY KEY (tenant_id, supplier_id, alias_norm)`

### Indexes

- `vendor_item_aliases_pkey` - `CREATE UNIQUE INDEX vendor_item_aliases_pkey ON public.vendor_item_aliases USING btree (tenant_id, supplier_id, alias_norm)`

---

## Table: `vendor_logos`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `supplier_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `domain` | `text` | YES | None |
| `source` | `character varying(10)` | YES | None |
| `status` | `character varying(10)` | NO | None |
| `mime` | `character varying(40)` | YES | None |
| `image` | `bytea` | YES | None |
| `fetched_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `vendor_logos_pkey` - `PRIMARY KEY (supplier_id)`

### Indexes

- `idx_vlogo_tenant` - `CREATE INDEX idx_vlogo_tenant ON public.vendor_logos USING btree (tenant_id)`
- `vendor_logos_pkey` - `CREATE UNIQUE INDEX vendor_logos_pkey ON public.vendor_logos USING btree (supplier_id)`

---

## Table: `vendor_outreach_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `supplier_id` | `uuid` | NO | None |
| `tenant_id` | `uuid` | NO | None |
| `requested_by` | `text` | YES | None |
| `requested_at` | `timestamp with time zone` | NO | `now()` |
| `email_to` | `text` | YES | None |
| `subject` | `text` | YES | None |
| `body` | `text` | YES | None |
| `status` | `text` | NO | `'sent'::text` |
| `requested_fields` | `text[]` | YES | None |
| `sent_at` | `timestamp with time zone` | YES | None |
| `sent_by` | `text` | YES | None |
| `response_received_at` | `timestamp with time zone` | YES | None |
| `thread_id` | `text` | YES | None |
| `message_id` | `text` | YES | None |

### Keys and Constraints

- `fk_outreach_supplier` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id) ON DELETE CASCADE`
- `fk_outreach_tenant` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`
- `vendor_outreach_log_pkey` - `PRIMARY KEY (id)`

### Indexes

- `idx_outreach_pending_sent_at` - `CREATE INDEX idx_outreach_pending_sent_at ON public.vendor_outreach_log USING btree (tenant_id, status, sent_at) WHERE (status = 'PENDING'::text)`
- `idx_vol_supplier` - `CREATE INDEX idx_vol_supplier ON public.vendor_outreach_log USING btree (supplier_id)`
- `vendor_outreach_log_pkey` - `CREATE UNIQUE INDEX vendor_outreach_log_pkey ON public.vendor_outreach_log USING btree (id)`

---

## Table: `vendor_tds_config_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `log_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `override_id` | `uuid` | NO | None |
| `changed_by` | `uuid` | YES | None |
| `changed_at` | `timestamp with time zone` | NO | `now()` |
| `field_changed` | `text` | NO | None |
| `old_value` | `text` | YES | None |
| `new_value` | `text` | YES | None |
| `reason` | `text` | YES | None |

### Keys and Constraints

- `vendor_tds_config_log_override_id_fkey` - `FOREIGN KEY (override_id) REFERENCES dim_vendor_tds_overrides(override_id)`
- `vendor_tds_config_log_pkey` - `PRIMARY KEY (log_id)`

### Indexes

- `vendor_tds_config_log_pkey` - `CREATE UNIQUE INDEX vendor_tds_config_log_pkey ON public.vendor_tds_config_log USING btree (log_id)`

---

## Table: `vendor_tds_fy_state`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `state_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `supplier_id` | `uuid` | NO | None |
| `tds_section_id` | `uuid` | NO | None |
| `fy` | `text` | NO | None |
| `cumulative_billed` | `numeric(14,2)` | YES | `0` |
| `cumulative_tds_deducted` | `numeric(14,2)` | YES | `0` |
| `threshold_crossed` | `boolean` | YES | `false` |
| `threshold_crossed_on_bill_id` | `uuid` | YES | None |
| `catchup_pending` | `numeric(14,2)` | YES | `0` |
| `catchup_recovered` | `numeric(14,2)` | YES | `0` |
| `catchup_decision` | `text` | YES | None |
| `catchup_decided_by` | `uuid` | YES | None |
| `catchup_decided_on` | `timestamp with time zone` | YES | None |
| `replay_in_progress` | `boolean` | YES | `false` |
| `updated_at` | `timestamp with time zone` | YES | `now()` |

### Keys and Constraints

- `vendor_tds_fy_state_pkey` - `PRIMARY KEY (state_id)`
- `vendor_tds_fy_state_supplier_id_fkey` - `FOREIGN KEY (supplier_id) REFERENCES dim_suppliers(supplier_id)`
- `vendor_tds_fy_state_tds_section_id_fkey` - `FOREIGN KEY (tds_section_id) REFERENCES dim_tds_sections(tds_section_id)`
- `vendor_tds_fy_state_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id)`
- `vendor_tds_fy_state_tenant_id_supplier_id_tds_section_id_fy_key` - `UNIQUE (tenant_id, supplier_id, tds_section_id, fy)`

### Indexes

- `vendor_tds_fy_state_pkey` - `CREATE UNIQUE INDEX vendor_tds_fy_state_pkey ON public.vendor_tds_fy_state USING btree (state_id)`
- `vendor_tds_fy_state_tenant_id_supplier_id_tds_section_id_fy_key` - `CREATE UNIQUE INDEX vendor_tds_fy_state_tenant_id_supplier_id_tds_section_id_fy_key ON public.vendor_tds_fy_state USING btree (tenant_id, supplier_id, tds_section_id, fy)`

---

## Table: `vocab_aliases`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `alias_id` | `uuid` | NO | `gen_random_uuid()` |
| `kind` | `text` | NO | None |
| `code` | `text` | NO | None |
| `alias_text` | `text` | NO | None |
| `alias_norm` | `text` | NO | None |
| `scope_tenant_id` | `uuid` | YES | None |
| `scope_supplier_id` | `uuid` | YES | None |
| `context_doc_role` | `text` | YES | None |
| `source` | `text` | NO | `'SEED'::text` |
| `confirmed_by` | `character varying(100)` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `vocab_aliases_check` - `CHECK (((source = 'SEED'::text) OR (scope_tenant_id IS NOT NULL)))`
- `vocab_aliases_kind_code_fkey` - `FOREIGN KEY (kind, code) REFERENCES vocab_codes(kind, code)`
- `vocab_aliases_pkey` - `PRIMARY KEY (alias_id)`
- `vocab_aliases_source_check` - `CHECK ((source = ANY (ARRAY['SEED'::text, 'HUMAN'::text, 'LEARNED'::text])))`

### Indexes

- `vocab_aliases_pkey` - `CREATE UNIQUE INDEX vocab_aliases_pkey ON public.vocab_aliases USING btree (alias_id)`
- `vocab_aliases_uniq` - `CREATE UNIQUE INDEX vocab_aliases_uniq ON public.vocab_aliases USING btree (kind, alias_norm, COALESCE(context_doc_role, ''::text), COALESCE(scope_tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(scope_supplier_id, '00000000-0000-0000-0000-000000000000'::uuid))`

---

## Table: `vocab_codes`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `kind` | `text` | NO | None |
| `code` | `text` | NO | None |
| `label` | `text` | NO | None |
| `parent_code` | `text` | YES | None |
| `tier` | `character(1)` | NO | `'L'::bpchar` |
| `version_added` | `text` | NO | None |
| `deprecated` | `boolean` | NO | `false` |
| `replaced_by` | `text` | YES | None |

### Keys and Constraints

- `vocab_codes_pkey` - `PRIMARY KEY (kind, code)`
- `vocab_codes_tier_check` - `CHECK ((tier = ANY (ARRAY['N'::bpchar, 'X'::bpchar, 'L'::bpchar])))`

### Indexes

- `vocab_codes_pkey` - `CREATE UNIQUE INDEX vocab_codes_pkey ON public.vocab_codes USING btree (kind, code)`

---

## Table: `vocab_meta`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `key` | `text` | NO | None |
| `value` | `text` | NO | None |
| `at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `vocab_meta_pkey` - `PRIMARY KEY (key)`

### Indexes

- `vocab_meta_pkey` - `CREATE UNIQUE INDEX vocab_meta_pkey ON public.vocab_meta USING btree (key)`

---

## Table: `wf_audit_log`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `log_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `table_name` | `text` | NO | None |
| `entity_id` | `uuid` | NO | None |
| `action` | `audit_action` | NO | None |
| `user_id` | `uuid` | YES | None |
| `correlation_id` | `uuid` | YES | None |
| `old_values_jsonb` | `jsonb` | YES | None |
| `new_values_jsonb` | `jsonb` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `wf_audit_log_pkey` - `PRIMARY KEY (log_id)`
- `wf_audit_log_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_audit_tenant_time` - `CREATE INDEX idx_audit_tenant_time ON public.wf_audit_log USING btree (tenant_id, created_at)`
- `idx_wf_audit_entity` - `CREATE INDEX idx_wf_audit_entity ON public.wf_audit_log USING btree (tenant_id, table_name, entity_id)`
- `wf_audit_log_pkey` - `CREATE UNIQUE INDEX wf_audit_log_pkey ON public.wf_audit_log USING btree (log_id)`

---

## Table: `wf_escalations`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `escalation_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `task_id` | `uuid` | NO | None |
| `escalated_to` | `uuid` | YES | None |
| `reason` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `wf_escalations_pkey` - `PRIMARY KEY (escalation_id)`
- `wf_escalations_task_id_fkey` - `FOREIGN KEY (task_id) REFERENCES wf_tasks(task_id) ON DELETE CASCADE`
- `wf_escalations_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `wf_escalations_pkey` - `CREATE UNIQUE INDEX wf_escalations_pkey ON public.wf_escalations USING btree (escalation_id)`

---

## Table: `wf_nudges`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `nudge_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `task_id` | `uuid` | YES | None |
| `end_customer_id` | `uuid` | YES | None |
| `stg_invoice_id` | `uuid` | YES | None |
| `contact_id` | `uuid` | YES | None |
| `channel` | `nudge_channel` | NO | None |
| `template_id` | `text` | YES | None |
| `content_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `status` | `nudge_status` | NO | `'PENDING'::nudge_status` |
| `sent_at` | `timestamp with time zone` | YES | None |
| `delivered_at` | `timestamp with time zone` | YES | None |
| `error_message` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `wf_nudges_contact_id_fkey` - `FOREIGN KEY (contact_id) REFERENCES dim_end_customer_contacts(contact_id) ON DELETE SET NULL`
- `wf_nudges_end_customer_id_fkey` - `FOREIGN KEY (end_customer_id) REFERENCES dim_end_customers(end_customer_id) ON DELETE SET NULL`
- `wf_nudges_pkey` - `PRIMARY KEY (nudge_id)`
- `wf_nudges_stg_invoice_id_fkey` - `FOREIGN KEY (stg_invoice_id) REFERENCES stg_invoices(stg_invoice_id) ON DELETE SET NULL`
- `wf_nudges_task_id_fkey` - `FOREIGN KEY (task_id) REFERENCES wf_tasks(task_id) ON DELETE SET NULL`
- `wf_nudges_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE RESTRICT`

### Indexes

- `wf_nudges_pkey` - `CREATE UNIQUE INDEX wf_nudges_pkey ON public.wf_nudges USING btree (nudge_id)`

---

## Table: `wf_tasks`

### Columns

| Column | Type | Nullable | Default or generation expression |
|---|---|---|---|
| `task_id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `task_type` | `wf_task_type` | NO | None |
| `entity_type` | `wf_entity_type` | NO | None |
| `entity_id` | `uuid` | NO | None |
| `assignee_user_id` | `uuid` | YES | None |
| `status` | `wf_task_status` | NO | `'PENDING'::wf_task_status` |
| `priority` | `smallint` | NO | `3` |
| `due_at` | `timestamp with time zone` | YES | None |
| `completed_at` | `timestamp with time zone` | YES | None |
| `metadata_jsonb` | `jsonb` | NO | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `wf_tasks_pkey` - `PRIMARY KEY (task_id)`
- `wf_tasks_tenant_id_fkey` - `FOREIGN KEY (tenant_id) REFERENCES dim_tenants(tenant_id) ON DELETE CASCADE`

### Indexes

- `idx_wf_tasks_assignee` - `CREATE INDEX idx_wf_tasks_assignee ON public.wf_tasks USING btree (assignee_user_id)`
- `idx_wf_tasks_entity` - `CREATE INDEX idx_wf_tasks_entity ON public.wf_tasks USING btree (entity_type, entity_id)`
- `idx_wf_tasks_status` - `CREATE INDEX idx_wf_tasks_status ON public.wf_tasks USING btree (tenant_id, status, due_at)`
- `wf_tasks_pkey` - `CREATE UNIQUE INDEX wf_tasks_pkey ON public.wf_tasks USING btree (task_id)`

---

## Appendix scope

The following licensing and platform administration notes describe the application design. The live database inventory ends above.

# Licensing & Platform Admin (added 2026-08-15)

Defined in [`backend_ocr/app/licensing_schema.py`](../../backend_ocr/app/licensing_schema.py),
applied by the app's startup hook and by `scripts/licensing_migrate.py --target both`.
See [LICENSING_AND_ADMIN.md](../administration/LICENSING_AND_ADMIN.md) for the model and the runbook.

> Note: every table in this document above the Licensing heading comes from a live
> introspection pull, so the inventory is complete as of that pull. The tables in
> *this* section are documented by hand because the rationale matters; their live
> column definitions also appear in the generated inventory above.
>
> One discrepancy found on the 18 Nov 2026 pull: `vendor_doc_edits` is referenced by
> `routers/vendor_documents.py` and `routers/vendor_activity.py` but **does not exist
> in the dev database**. Either startup creation is conditional, or those code paths
> would fail on dev.

## Table: `service_catalog`

Mirror of the `SERVICES` registry in `backend_ocr/app/services.py`, upserted on every
boot so `tenant_service.service_key` has a foreign-key target. Rows are never
deleted; a service dropped from the registry gets `retired_at` stamped.

| Column | Type | Nullable | Default |
|---|---|---|---|
| `service_key` | `text` | `NO` | `NULL` |
| `display_name` | `text` | `NO` | `NULL` |
| `description` | `text` | `NO` | `''` |
| `category` | `text` | `NO` | `NULL` |
| `is_core` | `bool` | `NO` | `false` |
| `default_enabled` | `bool` | `NO` | `false` |
| `metered_unit` | `text` | `YES` | `NULL` |
| `sort_order` | `int4` | `NO` | `0` |
| `retired_at` | `timestamptz` | `YES` | `NULL` |
| `created_at` | `timestamptz` | `NO` | `now()` |
| `updated_at` | `timestamptz` | `NO` | `now()` |

**Primary keys:** `service_key`

---

## Table: `tenant_service`

**The source of truth for what a tenant may use.** A missing row means "inherit
`service_catalog.default_enabled`", so a newly added core service lights up for
every existing tenant without a backfill write.

| Column | Type | Nullable | Default |
|---|---|---|---|
| `tenant_id` | `uuid` | `NO` | `NULL` |
| `service_key` | `text` | `NO` | `NULL` |
| `enabled` | `bool` | `NO` | `false` |
| `limits` | `jsonb` | `NO` | `'{}'::jsonb` |
| `config` | `jsonb` | `NO` | `'{}'::jsonb` |
| `enabled_at` | `timestamptz` | `YES` | `NULL` |
| `disabled_at` | `timestamptz` | `YES` | `NULL` |
| `updated_by` | `uuid` | `YES` | `NULL` |
| `notes` | `text` | `YES` | `NULL` |
| `created_at` | `timestamptz` | `NO` | `now()` |
| `updated_at` | `timestamptz` | `NO` | `now()` |

**Primary keys:** `tenant_id`, `service_key`
**Foreign keys:**
- `tenant_id` -> `dim_tenants.tenant_id` (ON DELETE CASCADE)
- `service_key` -> `service_catalog.service_key`

`updated_by` deliberately has **no** FK to `platform_users`, so deleting an ops
account does not cascade away the licensing audit trail.

**Indexes:** `idx_tenant_service_enabled` (partial, `WHERE enabled`),
`idx_tenant_service_key` (partial, `WHERE enabled`) — answers "which tenants have FX?"

---

## Table: `service_package` / `service_package_item`

Onboarding prefills. Applying a package **copies** rows into `tenant_service`;
nothing resolves through a package at request time, so editing one never changes a
live tenant.

`service_package`: `package_id` uuid PK, `key` text UNIQUE, `name`, `description`,
`is_active` bool, `sort_order` int, `created_at`.
`service_package_item`: PK (`package_id`, `service_key`), `enabled` bool, `limits` jsonb.

---

## Table: `platform_users`

Ops accounts. Entirely separate from `users` — a different table, a different
signing key, and no tenant.

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `email` | `text` | `NO` | `NULL` |
| `password_hash` | `text` | `NO` | `NULL` |
| `name` | `text` | `NO` | `NULL` |
| `role` | `text` | `NO` | `'support'` |
| `is_active` | `bool` | `NO` | `true` |
| `last_login_at` | `timestamptz` | `YES` | `NULL` |
| `failed_logins` | `int4` | `NO` | `0` |
| `locked_until` | `timestamptz` | `YES` | `NULL` |
| `created_by` | `uuid` | `YES` | `NULL` |
| `created_at` / `updated_at` | `timestamptz` | `NO` | `now()` |

**Constraints:** `role IN ('owner','admin','support','readonly')`;
`uq_platform_users_email` UNIQUE on `lower(email)`

---

## Table: `platform_refresh_tokens`

Mirrors `auth_refresh_tokens` so rotation and reuse-detection behave identically.
`token_hash` (sha256) UNIQUE, `platform_user_id` FK CASCADE, `issued_at`,
`expires_at`, `revoked`, `revoked_at`, `replaced_by`.

---

## Table: `platform_impersonation`

One row per support session. `session_id` uuid PK (used as the token `jti`),
`platform_user_id` FK, `tenant_id` FK, `assumed_role`, `reason` (required, ≥10
chars), `read_only` bool, `issued_at`, `expires_at`, `revoked_at`.

---

## Table: `tenant_usage`

Monthly rollup. PK (`tenant_id`, `service_key`, `metric`, `period_month`), plus
`used` numeric and `last_event_at`. `period_month` is always the first of the month.

---

## Table: `admin_audit_log`

Append-only record of every ops action. `id` bigserial PK,
`actor_platform_user_id`, `actor_email`, `action` (e.g. `license.enable`,
`tenant.create`, `impersonation.start`), `target_type`, `target_id`, `tenant_id`,
`before`/`after` jsonb, `impersonation_id`, `ip`, `user_agent`, `created_at`.
Written in the same transaction as the change, so a rolled-back change can never
leave a log entry claiming it happened.

**Indexes:** by time, tenant, actor and action — all `DESC` on `created_at`.

---

## Table: `schema_migrations`

`label` text PK, `applied_at`. Guards the one-shot licensing backfill so it can
only ever apply once per database.

---

## Additions to `dim_tenants`

| Column | Type | Nullable | Default | Why |
|---|---|---|---|---|
| `pipeline_enabled` | `bool` | `NO` | `true` | DB-driven successor to the `PIPELINE_TENANT_ID` env list |
| `onboarded_at` | `timestamptz` | `YES` | `NULL` | Set by the onboarding transaction |
| `package_key` | `text` | `YES` | `NULL` | Provenance only — nothing resolves through it |
| `legal_name` | `text` | `YES` | `NULL` | Default brand name; replaces the hardcoded customer name |
| `primary_contact_email` | `text` | `YES` | `NULL` | |

`sap_matching_enabled` is retained for now: it is the source for the licensing
backfill. Drop it only after `sap_matching` has resolved through `tenant_service`
for a full release.

---
