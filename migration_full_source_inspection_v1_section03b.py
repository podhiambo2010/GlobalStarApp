"""Section 03B extension: examine every original statement row, including zeros.

Source is an in-memory KCB dataframe already loaded by GlobalStarApp.
No database or local-file mutations. ID equivalence is tested exactly;
reference-only guesses NEVER cause a historical decision to be reassigned.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path

from bank_review_v1 import bank_row_ids
from migration_classification_v1_section03a import _read_reviews


def _amount(value):
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Bank value is missing or malformed") from exc
    if not number.is_finite():
        raise ValueError("Bank value is not finite")
    return number


def inspect_full_source(plan, discrepancy, bank_frame, root="."):
    if plan.get("schema") != "gs_streamlit_v1" or plan.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES":
        raise ValueError("Invalid source migration plan")
    if discrepancy.get("mode") != "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES":
        raise ValueError("Run Section 03B investigation before full-statement inspection")
    if not hasattr(bank_frame, "columns"):
        raise ValueError("Original bank dataframe unavailable")
    required = {"Transaction Date", "Money In Num", "Money Out Num", "Bank_Row_ID"}
    if not required.issubset(set(bank_frame.columns)):
        raise ValueError("Required original bank columns unavailable")
    reviews, path = _read_reviews(root)
    if hashlib.sha256(path.read_bytes()).hexdigest() != discrepancy.get("review_register_sha256"):
        raise ValueError("Historical review evidence changed; rerun Section 03A and 03B")
    expected_unmatched = {r["historical_bank_row_id"] for r in discrepancy.get("unmatched_review_details", [])}
    source_ids = {str(r.get("legacy_bank_row_id", "")).strip() for r in plan["bank_movements"]}
    if expected_unmatched != set(reviews).difference(source_ids):
        raise ValueError("Historical unmatched-review set changed; rerun investigation")
    frame = bank_frame.copy(deep=True)
    recorded_ids = frame["Bank_Row_ID"].astype(str).tolist()
    if len(set(recorded_ids)) != len(recorded_ids):
        raise ValueError("Duplicate original bank row ID; cannot determine historical identities")
    # Verify the generated ID algorithm is consistent with the current loaded source.
    # Never alter the IDs or substitute newly generated identities.
    regenerated = bank_row_ids(frame)
    ids_consistent = recorded_ids == regenerated
    zero_ids = set()
    all_ids = set(recorded_ids)
    for _, row in frame.iterrows():
        amount_in = _amount(row["Money In Num"])
        amount_out = _amount(row["Money Out Num"])
        if amount_in == 0 and amount_out == 0:
            zero_ids.add(str(row["Bank_Row_ID"]))
    details = []
    statuses = Counter()
    for review in discrepancy["unmatched_review_details"]:
        original_id = review["historical_bank_row_id"]
        if original_id in zero_ids:
            state = "exact_id_zero_amount_original_statement_row"
        elif original_id in all_ids:
            state = "exact_id_in_full_source_but_absent_from_migration_rows"
        else:
            state = "not_in_current_full_statement_by_exact_row_id"
        statuses[state] += 1
        details.append({
            "historical_bank_row_id": original_id,
            "review_decision": review["review_decision"],
            "review_tenancy_id": review["review_tenancy_id"],
            "full_source_match_state": state,
            "preserve_original_decision": True,
            "auto_remap_allowed": False,
        })
    tenancy_ids = {str(t["tenancy_id"]) for t in plan.get("tenancies", [])}
    stale_detail = []
    for record in discrepancy.get("stale_tenancy_details", []):
        prior_id = str(record["review_tenancy_id"])
        # A unit-prefix coincidence is only a search hint, not a matched tenancy.
        prefix = prior_id.split(":", 1)[0]
        possible = [t for t in plan["tenancies"]
                    if str(t.get("unit_code", "")).strip() == prefix]
        stale_detail.append({
            "bank_row_id": record["bank_row_id"],
            "historical_tenancy_id": prior_id,
            "still_absent_from_register": prior_id not in tenancy_ids,
            "same_unit_tenancy_ids_for_manual_investigation":
                [str(t["tenancy_id"]) for t in possible],
            "historical_tenancy_reidentified": False,
            "auto_assignment_allowed": False,
        })
    return {
        "mode": "SECTION_03B_FULL_SOURCE_DIAGNOSTIC_NO_WRITES",
        "schema": "gs_streamlit_v1",
        "total_original_statement_rows_in_memory": len(frame),
        "nonzero_migration_rows": len(plan["bank_movements"]),
        "zero_amount_original_rows": len(zero_ids),
        "row_id_algorithm_consistent_with_source": ids_consistent,
        "unmatched_reviews_inspected": len(details),
        "unmatched_match_categories": dict(sorted(statuses.items())),
        "unmatched_review_evidence": details,
        "stale_tenancy_evidence": stale_detail,
        "scope_note": "An absent exact row ID is not evidence that the bank transaction never occurred. Earlier statement exports may be necessary.",
        "approved_imports": 0,
        "approved_rent_postings": 0,
        "local_writes": False,
        "supabase_writes": False,
    }
