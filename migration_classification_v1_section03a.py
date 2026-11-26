"""Section 03A — source-row evidence classification, NO DB WRITES.

Never infer payment approval or tenant assignment from a bank reference alone.
This returns counts and non-sensitive held classifications, not a posting plan.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

from migration_preview_v1_section03 import (
    CHEQUE_CLEARANCES, CHEQUE_ALLOCATIONS, REVIEW_EVIDENCE, _load_history
)

DECISIONS = frozenset(("assign", "exclude", "pending", "restore"))


def _read_reviews(root):
    path = Path(root) / REVIEW_EVIDENCE
    if not path.exists():
        raise ValueError("Original tenancy-bank review register missing; classification blocked")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Expected bank-row-keyed tenancy review dictionary")
    for key, entry in data.items():
        if not isinstance(key, str) or not key or not isinstance(entry, dict):
            raise ValueError("Malformed review entry or bank row ID")
        if entry.get("decision") not in DECISIONS:
            raise ValueError("Unrecognized review decision; manual inspection required")
        if entry["decision"] == "assign" and not str(entry.get("tenancy_id") or "").strip():
            raise ValueError("Assigned review missing tenancy identity")
    return data, path


def _audit_integrity(history, kind):
    if history is None:
        raise ValueError(f"Missing {kind} audit history; cannot establish cheque integrity")
    required = ("successful_credit_row_id", "original_credit_row_id", "returned_debit_row_id")
    if any(not all(str(event.get(field, "")).strip() for field in required)
           for event in history):
        raise ValueError(f"Incomplete {kind} audit history")
    return history


def classify_evidence(plan, preview, root="."):
    if plan.get("schema") != "gs_streamlit_v1" or plan.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES":
        raise ValueError("Invalid local dry-run plan")
    if preview.get("mode") != "SECTION_03_PREVIEW_ONLY_NO_WRITES" or preview.get("schema") != "gs_streamlit_v1":
        raise ValueError("Section 03 preview required")
    rows = plan.get("bank_movements", [])
    tenancies = plan.get("tenancies", [])
    if not isinstance(rows, list) or not isinstance(tenancies, list):
        raise ValueError("Malformed migration inventory")
    if len(rows) != preview.get("local_bank_rows") or len(tenancies) != preview.get("local_tenancies"):
        raise ValueError("Stale Section 03 preview; repeat comparison and preview")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid bank row")
    ids = [str(row.get("legacy_bank_row_id", "")).strip() for row in rows]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Bank row IDs missing or duplicated; cannot classify safely")
    t_ids = [str(t.get("tenancy_id", "")).strip() for t in tenancies]
    if any(not x for x in t_ids) or len(set(t_ids)) != len(t_ids):
        raise ValueError("Tenancy IDs missing or duplicated")
    valid_tenants = set(t_ids)
    reviews, review_path = _read_reviews(root)
    review_integrity = hashlib.sha256(review_path.read_bytes()).hexdigest()
    clearances = _audit_integrity(_load_history(root, CHEQUE_CLEARANCES), CHEQUE_CLEARANCES)
    allocations = _audit_integrity(_load_history(root, CHEQUE_ALLOCATIONS), CHEQUE_ALLOCATIONS)
    # Append-only histories: latest event wins, prior versions remain available.
    latest_c = {event["successful_credit_row_id"]: event for event in clearances}
    latest_a = {event["successful_credit_row_id"]: event for event in allocations}
    for key, event in latest_a.items():
        source = latest_c.get(key)
        if (source is None or source.get("tenancy_id") != event.get("tenancy_id")
                or event.get("rent_posted") is not False):
            raise ValueError("Stage 1I cheque allocation conflicts with current Stage 1H review")
    cheque_classes = {}
    for event in latest_c.values():
        for key, reason in (
            ("original_credit_row_id", "returned_cheque_original_deposit"),
            ("returned_debit_row_id", "returned_cheque_reversal_debit"),
            ("successful_credit_row_id", "later_cleared_cheque_credit"),
        ):
            row_id = str(event[key])
            if row_id in cheque_classes and cheque_classes[row_id] != reason:
                raise ValueError("One bank row is linked to conflicting cheque roles")
            cheque_classes[row_id] = reason

    counts = Counter()
    rows_out = []
    source_ids = set(ids)
    for row in rows:
        row_id = str(row["legacy_bank_row_id"]).strip()
        decision = reviews.get(row_id)
        action = decision["decision"] if decision else "unreviewed"
        reason = cheque_classes.get(row_id)
        if reason:
            classification = reason
        elif action == "exclude":
            classification = "excluded_reviewed"
        elif action == "pending":
            classification = "pending_review"
        elif action == "restore":
            classification = "restored_requires_reassessment"
        elif action == "assign":
            if str(decision["tenancy_id"]) not in valid_tenants:
                classification = "assigned_stale_tenancy"
            else:
                classification = "assigned_reviewed_not_posted"
        else:
            classification = "unreviewed"
        counts[classification] += 1
        rows_out.append({
            "bank_row_id": row_id,
            "classification": classification,
            "review_decision": action,
            "direction": str(row.get("direction", "")),
            "migration_status": str(row.get("migration_status", "")),
            "migration_approved": False,
            "rent_posted": False,
        })
    orphan_reviews = sorted(set(reviews) - source_ids)
    orphan_cheque_rows = sorted(set(cheque_classes) - source_ids)
    if orphan_cheque_rows:
        raise ValueError("Cheque history refers to bank rows outside current uploaded statement")
    if len(latest_c) != len(latest_a):
        # An unallocated clearance is allowed, but must never be portrayed as posted.
        pass
    return {
        "mode": "SECTION_03A_EVIDENCE_CLASSIFICATION_ONLY_NO_WRITES",
        "schema": "gs_streamlit_v1",
        "total_original_bank_rows": len(rows),
        "classified_rows": len(rows_out),
        "classification_counts": dict(sorted(counts.items())),
        "matched_review_decisions": sum(row["review_decision"] != "unreviewed" for row in rows_out),
        "orphan_review_decisions": len(orphan_reviews),
        "cheque_related_bank_rows": sum(bool(row["bank_row_id"] in cheque_classes) for row in rows_out),
        "stage_1h_current_cheques": len(latest_c),
        "stage_1i_current_allocation_decisions_not_posted": len(latest_a),
        "review_register_sha256": review_integrity,
        "cheque_clearance_sha256": hashlib.sha256((Path(root) / CHEQUE_CLEARANCES).read_bytes()).hexdigest(),
        "cheque_allocation_sha256": hashlib.sha256((Path(root) / CHEQUE_ALLOCATIONS).read_bytes()).hexdigest(),
        "historical_file_warnings": list(preview.get("missing_evidence_from_stage_1d", [])),
        "approved_imports": 0,
        "approved_rent_postings": 0,
        "all_rows_held": True,
        "row_classifications": rows_out,
    }
