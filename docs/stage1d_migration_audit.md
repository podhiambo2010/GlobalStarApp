# Stage 1D — Migration audit gate

**Status:** dry run implemented; NO database writes enabled.

The Stage 1D panel is under **Arrears Payment Reminders**. Use the
already reviewed tenant-history workbook and ORIGINAL KCB statement.
Run **Analyze local history (read-only)**. It inventories the local
review JSON evidence and provides a downloadable private manifest.

Before approving a database synchronization:
1. Compare expected **19 eligible historical openings** (or the latest
   source count) against manifest `opening_balance_entries`. Do not
   assume a count verifies every amount/date: verify `as_of`,
   `amount`, and `evidence` separately.
2. Confirm `opening_balances_v1.json`, `tenancy_bank_reviews_v1.json`,
   `tenancy_receipt_splits_v1.json`, review history, legacy overrides
   and exclusions are included or explicitly accounted for.
3. Resolve `ambiguous_identical_rows` and `possible_overlap_review`
   before bank movement posting. Bank reference alone is not a unique ID.
4. Preserve **Mowlem Unit 10 and Unit 13** as separate tenancy/deposit
   records. Do not automatically label unverified deposits as cash.
5. Verify 1 Sep 2025 baseline against coverage beginning 21 Sep 2025:
   the intervening days are NOT represented in the bank source.
6. Do not classify a customer's whole incoming payment as rent when
   it includes security deposits or advance payments.
7. Keep all reminder dispatch, eTIMS transmission and debt collection
   disabled throughout reconciliation.

## Data protection

`gs_streamlit_v1` is a private schema in the existing Supabase
GlobalStarInvestmentsDB project. It is NOT yet connected to the
Streamlit runtime and remains empty. The eight-table schema was
created in Stage 1C and all app roles currently lack access.

Stage 1D creates a **manifest on demand only in Streamlit memory**.
It never changes JSON evidence, database records, tenancy workbook or
bank statement. Downloaded manifests may contain bank narrations,
tenancy identities and evidence notes. Keep them off public GitHub.

## Acceptance

```powershell
cd D:\Projects\GlobalStarApp
git fetch origin
git switch --track origin/feature/v1d-migration-dryrun-20261126
python -m unittest tests.test_v1c_persistent_history tests.test_v1d_migration_dryrun -v
python -m streamlit run app_frontend.py --server.port 8502
```

A successful dry run must report no malformed JSON, list the expected
tenancy/opening counts, and show bank overlap review categories.
Do not execute synchronization until a subsequent, authenticated,
transaction-safe uploader is built and this report has been reviewed.
