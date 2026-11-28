"""Section 03B: investigate historical review mismatches, WITHOUT any writes.

The review dictionary is the authoritative preserved decision record. Discrepancy
reporting never restores, remaps, deletes, assigns or authorizes ledger posting.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

from migration_classification_v1_section03a import _read_reviews


def investigate_discrepancies(plan, classification, root="."):
    if (not isinstance(plan, dict) or plan.get("schema") != "gs_streamlit_v1"
            or plan.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES"):
        raise ValueError("Requires an original Stage 1D no-write manifest")
    if (not isinstance(classification, dict)
            or classification.get("mode") != "SECTION_03A_EVIDENCE_CLASSIFICATION_ONLY_NO_WRITES"
            or classification.get("schema") != "gs_streamlit_v1"):
        raise ValueError("Requires a current Section 03A classification")
    rows = plan.get("bank_movements")
    tenancies = plan.get("tenancies")
    if not isinstance(rows, list) or not isinstance(tenancies, list):
        raise ValueError("Malformed source inventory")
    if len(rows) != classification.get("total_original_bank_rows"):
        raise ValueError("Stage 03A snapshot differs from local bank inventory")
    source_ids = [str(row.get("legacy_bank_row_id", "")).strip() for row in rows]
    if any(not x for x in source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("Unreliable bank-row identifiers; investigate source first")
    tenant_ids = {str(t.get("tenancy_id", "")).strip() for t in tenancies}
    reviews, review_path = _read_reviews(root)
    actual_hash = hashlib.sha256(review_path.read_bytes()).hexdigest()
    if actual_hash != classification.get("review_register_sha256"):
        raise ValueError("Review register changed after Section 03A; rerun classification")
    if classification.get("matched_review_decisions") != len(set(reviews) & set(source_ids)):
        raise ValueError("Review-match count changed after Section 03A")
    if classification.get("orphan_review_decisions") != len(set(reviews) - set(source_ids)):
        raise ValueError("Unmatched-review count changed after Section 03A")
    if classification.get("classified_rows") != len(rows):
        raise ValueError("Invalid Section 03A original-row count")
    # Validate the audited cheque documents have not changed since classification.
    for name, expected_key in (
        ("cheque_clearance_reviews_v1h.json", "cheque_clearance_sha256"),
        ("cheque_allocations_v1i.json", "cheque_allocation_sha256"),
    ):
        path = Path(root) / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != classification.get(expected_key):
            raise ValueError("Cheque evidence changed since Section 03A; rerun classification")
    orphan = []
    invalid_tenants = []
    present = set(source_ids)
    for row_id, decision in sorted(reviews.items()):
        action = str(decision["decision"])
        tenant_id = str(decision.get("tenancy_id") or "")
        if row_id not in present:
            orphan.append({
                "historical_bank_row_id": row_id,
                "review_decision": action,
                "review_tenancy_id": tenant_id,
                "tenancy_still_in_register": bool(tenant_id and tenant_id in tenant_ids),
                "state": "historical_review_preserved_not_in_current_nonzero_bank_rows",
                "manual_resolution_required": True,
            })
        elif action == "assign" and tenant_id not in tenant_ids:
            invalid_tenants.append({
                "bank_row_id": row_id,
                "review_tenancy_id": tenant_id,
                "state": "assignment_tenancy_missing_from_current_register",
                "manual_resolution_required": True,
            })
    source_zero_exclusion_note = (
        "The Stage 1D manifest excludes zero-amount movements. An unmatched historical "
        "review may refer to a zero-value bank marker, a different statement version, "
        "or a changed row identifier. This report cannot determine which."
    )
    return {
        "mode": "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES",
        "schema": "gs_streamlit_v1",
        "original_review_count": len(reviews),
        "matched_review_count": len(reviews) - len(orphan),
        "unmatched_historical_reviews": len(orphan),
        "unmatched_decisions_by_type": dict(sorted(Counter(x["review_decision"] for x in orphan).items())),
        "stale_tenancy_assignments_in_current_bank_rows": len(invalid_tenants),
        "unmatched_review_details": orphan,
        "stale_tenancy_details": invalid_tenants,
        "source_statement_rows_not_claimed_as_all_reconciled": len(rows),
        "possible_causes_not_confirmed": [source_zero_exclusion_note,
            "Compare bank-row fingerprints and original files privately; never remap by reference alone."],
        "historical_files_pending": list(classification.get("historical_file_warnings", [])),
        "review_register_sha256": actual_hash,
        "approved_imports": 0,
        "approved_rent_postings": 0,
        "evidence_written": False,
    }
