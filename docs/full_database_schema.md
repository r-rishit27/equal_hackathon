# Full Database Schema Documentation

Snapshot of the `public` schema in `postgres` on 21 November 2026 (PostgreSQL 17.9). The schema contains 4 tables and 0 enum types.

## Enum Types

The public schema defines no enum types.

## Table: `disbursement_gateway_calls`

### Columns

| Column | Type | Nullable | Default |
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

## Table: `disbursement_overrides`

### Columns

| Column | Type | Nullable | Default |
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

## Table: `fact_disbursements`

### Columns

| Column | Type | Nullable | Default |
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
| `nbfc_name` | `text` | YES | None |
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
| `is_overridden` | `boolean` | NO | `false` |
| `override_id` | `uuid` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |
| `updated_at` | `timestamp with time zone` | NO | `now()` |
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

## Table: `remitter_accounts`

### Columns

| Column | Type | Nullable | Default |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `tenant_id` | `uuid` | NO | None |
| `account_number` | `text` | NO | None |
| `bank_name` | `text` | NO | None |
| `ifsc` | `text` | YES | None |
| `bank_provider` | `text` | NO | `'ICICI'::text` |
| `balance` | `numeric` | NO | `5000000` |
| `notify_email` | `text` | YES | None |
| `nbfc_name` | `text` | YES | None |
| `created_at` | `timestamp with time zone` | NO | `now()` |

### Keys and Constraints

- `remitter_accounts_pkey` - `PRIMARY KEY (id)`
- `remitter_accounts_tenant_id_account_number_key` - `UNIQUE (tenant_id, account_number)`

### Indexes

- `remitter_accounts_pkey` - `CREATE UNIQUE INDEX remitter_accounts_pkey ON public.remitter_accounts USING btree (id)`
- `remitter_accounts_tenant_id_account_number_key` - `CREATE UNIQUE INDEX remitter_accounts_tenant_id_account_number_key ON public.remitter_accounts USING btree (tenant_id, account_number)`

---

## Appendix scope

The following licensing and platform administration notes describe the application design. The live database inventory ends above.

# Licensing & Platform Admin (added 2026-08-15)

Defined in [`backend_ocr/app/licensing_schema.py`](../backend_ocr/app/licensing_schema.py),
applied by the app's startup hook and by `scripts/licensing_migrate.py --target both`.
See [LICENSING_AND_ADMIN.md](LICENSING_AND_ADMIN.md) for the model and the runbook.

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
