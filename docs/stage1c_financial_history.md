# Stage 1C — Streamlit V1 financial history (2026-11-26)

Supabase project: **GlobalStarInvestmentsDB**. Dedicated private schema: `gs_streamlit_v1`.

## Migration state

Created eight private tables: `tenancies`, `opening_rent_balances`,
`deposit_accounts`, `import_batches`, `bank_movements`,
`batch_movements`, `allocation_reviews`, `audit_events`.

These are separate from `public.bank_cumulative_movements` and all other
existing GlobalStar project tables. RLS is enabled and public/client access
revoked; direct authenticated Streamlit access is **not yet configured**.
No historical bank statements, tenant rows, or payment decisions have been
copied to this schema yet. Do not assume the schema is a live accounting ledger.

## Business rules

* Baseline: **2025-09-01**, **zero assumed RENT opening only**, not a verified zero debt.
* Existing tenants: contract deposits can be recorded in `deposit_accounts`
  as historically assumed paid; NEVER record these assumptions as bank cash.
* Former tenants: if a deposit is believed refunded, use
  `refund_state='assumed_refunded'` rather than a verified refund transaction.
* New tenants: after identifying tenancy and verifying receipt, suggest
  deposit-first allocations. Review rent versus advance-rent period separately.
* Same entity, different unit: separate `tenancy_id` and deposit account;
  Mowlem Units 10 and 13 must not be merged.
* Do not infer that a missing deposit is paid from an unrelated arrangement
  or KSh 6,000 receipts without source evidence.
* Import bank statements as batches. Keep raw original credit/debit rows,
  source-account identity, references and timestamps.
* A matching `fingerprint` is not by itself absolute evidence of a duplicate;
  preserve rows with ambiguous identity for manual review.
* The uploaded statement starting **2025-09-21** cannot prove that there were
  no transactions between **2025-09-01 and 2025-09-20**. Show that gap.
* All rent arrears, notices, collection reminders, eTIMS postings, and
  accounting exports stay disabled until full reconciliation and validation.

## Local code

`persistent_history_v1c.py` supplies fingerprinting, tentative import
staging, zero-opening eligibility and proposed deposit-first splitting.
`tests/test_v1c_persistent_history.py` covers high-risk cases.

Streamlit's **Arrears Payment Reminders** has an opt-in initializer for
missing zero opening RENT balances dated 2025-09-01. Until sync is built,
that initializer writes the local audited `opening_balances_v1.json`, **not**
the Supabase tables. Backup the local file before changing branches/machines.
Do not treat local writes as database persistence.

## Next gated tasks before activating importer

1. Inspect/backup legacy local JSON and worksheet decisions, map tenancy IDs,
   bank-row IDs, and reviewed splits without rematching/overwriting them.
2. Configure an authenticated backend with appropriate minimal database roles.
   Never embed Supabase secrets in browser-delivered Streamlit code or GitHub.
3. Implement transaction-scoped staging to `gs_streamlit_v1`, dry-run counts,
   ambiguous overlap reporting, and exact accounting reconciliation.
4. Verify source identities and file dates. Only confirm money movements and
   deposit refunds against documentary evidence.
5. Run Python tests locally and security/performance advisors; confirm users
   cannot access private data through unauthenticated APIs.
