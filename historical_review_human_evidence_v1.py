"""Human-readable bank evidence for historical reviews, no allocations or writes.

An audit event stores bank reference and review timestamp, NOT the original
bank movement date, amount or particulars. Display nearby/current-statement
references as *candidates* only; human review remains mandatory.
"""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import hashlib
import json
import pandas as pd

from migration_identity_recovery_v1_section03c import _read_history
from migration_classification_v1_section03a import _read_reviews


def build_human_review_sheet(discrepancy, frame, root="."):
    if discrepancy.get("mode") != "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES":
        raise ValueError("Section 03B report required before historical review")
    reviews, review_path = _read_reviews(root)
    actual_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()
    if actual_sha != discrepancy.get("review_register_sha256"):
        raise ValueError("Historical review register has changed; rerun Section 03B")
    required = {"Bank_Row_ID", "Transaction Date", "Transaction Details",
                "Ref_Clean", "Money In Num", "Money Out Num"}
    if not hasattr(frame, "columns") or not required.issubset(set(frame.columns)):
        raise ValueError("Current original statement is missing required transaction columns")
    rows = frame.copy(deep=True)
    if rows["Bank_Row_ID"].astype(str).duplicated().any():
        raise ValueError("Current bank transaction identity is not unique")
    current_ids = set(rows["Bank_Row_ID"].astype(str))
    unmatched = discrepancy.get("unmatched_review_details", [])
    if any(entry.get("historical_bank_row_id") in current_ids for entry in unmatched):
        raise ValueError("A historical row is now present in the current source; rerun diagnostics")
    audit, _ = _read_history(root)
    by_id = defaultdict(list)
    for event in audit:
        row_id = str(event.get("bank_row_id", "")).strip()
        if row_id:
            by_id[row_id].append(event)
    cases = []
    candidate_rows = []
    for i, item in enumerate(unmatched, 1):
        old_id = str(item["historical_bank_row_id"])
        events = by_id.get(old_id, [])
        refs = list(dict.fromkeys(str(e.get("bank_reference", "")).strip()
                                  for e in events if str(e.get("bank_reference", "")).strip()
                                  and str(e.get("bank_reference", "")).lower() != "nan"))
        candidates = rows[rows["Ref_Clean"].astype(str).str.strip().isin(refs)] if refs else rows.iloc[0:0]
        cases.append({
            "case": i,
            "previous_decision": str(item.get("review_decision", "")),
            "previous_tenancy_id": str(item.get("review_tenancy_id") or ""),
            "bank_references_from_audit": " | ".join(refs),
            "last_review_recorded_utc": str(events[-1].get("timestamp_utc", "")) if events else "",
            "audit_reason": " | ".join(str(e.get("reason", "")).strip() for e in events if e.get("reason")),
            "current_statement_reference_candidates": len(candidates),
            "original_transaction_date_proven": False,
            "original_amount_proven": False,
            "status": "review_current_bank_particulars" if len(candidates) else "no_same_reference_in_current_statement",
            "historical_bank_row_id": old_id,
        })
        for _, current in candidates.iterrows():
            candidate_rows.append({
                "case": i,
                "transaction_date": str(current.get("Transaction Date", "")),
                "value_date": str(current.get("Value Date", "")),
                "money_in_ksh": current.get("Money In Num", 0),
                "money_out_ksh": current.get("Money Out Num", 0),
                "bank_reference": str(current.get("Ref_Clean", "")),
                "full_particulars": str(current.get("Transaction Details", "")),
                "candidate_only_not_a_verified_match": True,
            })
    statement = [{
        "transaction_date": str(row.get("Transaction Date", "")),
        "value_date": str(row.get("Value Date", "")),
        "money_in_ksh": row.get("Money In Num", 0),
        "money_out_ksh": row.get("Money Out Num", 0),
        "bank_reference": str(row.get("Ref_Clean", "")),
        "full_particulars": str(row.get("Transaction Details", "")),
        "bank_row_id": str(row.get("Bank_Row_ID", "")),
    } for _, row in rows.iterrows()]
    return {
        "mode": "HUMAN_READABLE_HISTORICAL_REVIEW_NO_WRITES",
        "cases": cases,
        "reference_candidates": candidate_rows,
        "full_current_statement": statement,
        "original_statement_rows": len(statement),
        "historical_cases": len(cases),
        "review_edits": 0,
        "supabase_writes": False,
        "rent_postings": 0,
    }
