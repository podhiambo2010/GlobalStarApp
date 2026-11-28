# Section 04B — Permanent reconciliation register: design for approval

**Status:** DRAFT / NO DATABASE CHANGES / NO MIGRATION AUTHORIZED  
**Application:** `podhiambo2010/GlobalStarApp`, Streamlit reconciliation  
**Database:** `GlobalStarInvestmentsDB`, isolated `gs_streamlit_v1` schema  
**Do not confuse with:** Commercial GlobalStarApp tables under `public`

## Verified starting state

- `gs_streamlit_v1` has eight existing tables: `tenancies`, `opening_rent_balances`, `deposit_accounts`, `import_batches`, `bank_movements`, `batch_movements`, `allocation_reviews`, `audit_events`.
- All eight were empty at the latest read-only inspection. Every existing table has RLS enabled.
- `allocation_reviews.movement_id` requires an existing `bank_movements` record. Many original historical decisions refer to bank-row identities from earlier statement versions, which have not been imported. Do NOT force those old reviews into this table.
- Section 04A: 53 live and 53 archived bank reviews; all IDs and record contents agree. 65 historical audit events. Four cheque clearance history events, two cheque allocation history events, two latest approvals pending actual ledger posting.
- Five historical audit events absent from the ordinary bank-review register all have action `split_receipt`. Validate them separately against `tenancy_receipt_splits_v1.json` (the Section 04A correction is committed, awaiting local confirmation).

## Record categories and precedence

1. **Bank evidence** — original statement file identity, original bank row, transaction date, value date, amount, sign, full narration, reference, account and source version. Treat a shared reference as a group hint, not proof of one transaction.
2. **Review decisions** — assign tenant, exclude non-rent, pending, or a separately validated split receipt. Immutable versions and reasons; never overwrite prior review history.
3. **Receipt splits** — separate components for security deposit liability, advance rent, current rent; totals must equal original credited amount. Require audited corrections rather than double posting or a competing full-rent assignment.
4. **Cheque lifecycle** — original deposit, reversal debit, eventual successfully cleared credit. Only a cleared credit is eligible for rent allocation; none of the original/reversal entries counts as rental income.
5. **Cheque allocation approvals** — preserve periods, amount, reviewer and status `allocation_approved_ledger_pending`. Approval does not equal ledger posting.
6. **Legacy reference-only exclusions/reassignments** — retain as historical hints, never automatically apply to every row with the same reference.
7. **Unmatched historical IDs** — preserve prior decision, original row ID and audit event. If no exact identity is available in the currently loaded statement, do not manufacture dates, amounts or a new matching row.

## Proposed additional tables (not yet created)

### `gs_streamlit_v1.reconciliation_evidence_sources`
- `id` UUID primary key
- `source_kind` text, enumerated and constrained (live review register, archived review register, review audit log, legacy ignored/reassignments, split register, cheque clearance, cheque allocation, statement source)
- `source_filename` text; `sha256` char(64); `captured_at` timestamptz
- `record_count` integer; `import_state` text (proposed/staged/verified/rejected)
- `note` text
- Unique identity by hash + source-kind; content is never silently replaced.

### `gs_streamlit_v1.reconciliation_decision_events`
- `id` bigint generated primary key
- `source_id` references evidence source; `source_record_key` text; `source_event_index` integer
- `historical_bank_row_id` text nullable (preserve exactly), `bank_reference` text nullable
- `decision_class` constrained text: assign / exclude / pending / split_receipt / cheque_clearance / cheque_rent_allocation / correction
- `tenant_identity_as_reviewed` text nullable; `decision_payload` JSONB (component periods, names and amounts as originally reviewed; not automatically posted)
- `reviewer` text nullable; `reviewed_at` timestamptz nullable; `reason` text nullable
- `supersedes_event_id` bigint nullable for explicitly reviewed amendments
- `identity_resolution_state` constrained text: exact_row / candidate_only / unmatched
- `posting_state` constrained text: not_applicable / evidence_only / approved_ledger_pending / posted_verified
- `recorded_at` timestamptz default now()
- Unique (source_id, source_record_key, source_event_index) to make repeated imports idempotent.
- Never directly update or delete historical events; add a new event to document an amendment.
- Do not equate the stored `historical_bank_row_id` with `bank_movements.id` unless independently established.

### `gs_streamlit_v1.reconciliation_movement_links`
- `id` bigint generated primary key
- `decision_event_id` references evidence event
- `movement_id` nullable FK to `bank_movements`
- `statement_identity` text nullable, `match_state` constrained: proposed / verified / rejected
- `evidence_note`, `reviewed_by`, `reviewed_at` required for a verified link
- Unique verified linkage constraints designed with allowance for genuine split allocations.
- Never promote a reference-only candidate to verified; require dates, amounts, direction, narration and identity evidence.

## Security and authorization design

- Retain existing **restricted SELECT-only** Streamlit connection; do not extend its privileges.
- Additional tables should be private within `gs_streamlit_v1`, with RLS enabled from creation. No blanket `anon`, `authenticated`, or `PUBLIC` grants.
- A separate, narrowly scoped operator/import identity is required later; review writer permissions in a separate approval step. Do not grant `postgres` or `service_role` access to the client.
- Financial source files are never deleted or mutated by migration; store hashes in Supabase rather than passwords, private local paths, or unrestricted copies of entire bank files.
- Migration requires explicit operator approval, staging preview, row counts, source hash verification, duplicate detection and rollback procedure.
- **No insertion into existing `allocation_reviews` or rent ledger** until bank movements, tenancy identity, and ledger rules have each been independently validated.

## Streamlit UX requirements

- On every upload, show **Action Required** (new/ambiguous) separately from **Resolved / History** and **Approved — Posting Pending**.
- For confirmed bank-to-mobile reversal groups such as `FT26284R9HMB`, show the outgoing payments + associated reversed amounts as an audited net-zero non-rental group. Do not hide every bank row that shares this reference; distinguish the four actual rows.
- The two returned cheques (Mash 4525; Dreamline 4680) are already resolved at clearance/allocation stage. Show them as bank-cleared and allocation-approved, but still ledger pending.
- History remains searchable by full particulars, date, amount, tenant and reference. If an earlier bank row is absent from current uploaded statement, explain which evidence is missing rather than reopening a settled review.
- Saved decisions are locked by default; revisions require explicit reason and an appended audit record.

## Gates before applying any DDL or imports

1. Run updated Section 04A locally; confirm the five split-receipt audit IDs exist in the dedicated split register and inspect any genuinely missing split records.
2. Back up the live 65-event audit log and live split register into the protected backup directory; do not overwrite earlier copies.
3. Produce a read-only **normalized staging manifest** with source hashes, record IDs, chronological amendments and candidate statuses. Verify the 53 reviews + all split receipts + cheque history without duplicates.
4. Review DDL and least-privilege role model before any schema write.
5. Only after explicit authorization: create new tables, verify RLS/permissions, dry-run staging, and approve an idempotent source-by-source import.
6. Ledger posting remains a separate accounting approval workflow.

**This document records design only. No SQL has been executed, no database records imported, and no rent posted.**
