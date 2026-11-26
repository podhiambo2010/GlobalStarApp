"""Section 03 — conservative, evidence-preserving migration preview.

Read-only: inspect Stage 1D plan, local append-only cheque evidence and Section 02
snapshot. Never mutate local evidence, grant approval, connect, or post to database.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from supabase_compare_v1_readonly import SCHEMA, TABLES

CHEQUE_CLEARANCES = "cheque_clearance_reviews_v1h.json"
CHEQUE_ALLOCATIONS = "cheque_allocations_v1i.json"
REVIEW_EVIDENCE = "tenancy_bank_reviews_v1.json"


def _load_history(root, filename):
    path = Path(root) / filename
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(raw, dict) or raw.get("schema_version") != 1
            or not isinstance(raw.get("history"), list)
            or not all(isinstance(item, dict) for item in raw["history"])):
        raise ValueError(f"Invalid {filename}; preview blocked")
    return raw["history"]


def _review_inventory(root):
    path = Path(root) / REVIEW_EVIDENCE
    if not path.is_file():
        return {"present": False, "records": 0, "decisions": {},
                "notices": ["Original tenancy review register not found locally"]}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Local tenancy bank review register must be a JSON object")
    decisions = Counter()
    for value in data.values():
        if not isinstance(value, dict):
            raise ValueError("Invalid tenancy bank review entry; preview blocked")
        decisions[str(value.get("decision", "unknown"))] += 1
    return {"present": True, "records": len(data),
            "decisions": dict(decisions), "notices": []}


def build_migration_preview(plan, comparison, root="."):
    """A non-authorizing manifest. Rows are intentionally all HELD for review."""
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA or plan.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES":
        raise ValueError("Section 03 requires a valid Stage 1D read-only manifest")
    if not isinstance(comparison, dict) or comparison.get("mode") != "READ_ONLY_COMPARISON_NO_IMPORT" or comparison.get("schema") != SCHEMA:
        raise ValueError("Section 03 requires a completed Section 02 read-only comparison")
    counts = comparison.get("remote_counts", {})
    if not isinstance(counts, dict) or set(counts) != set(TABLES) or any(not isinstance(counts[t], int) or counts[t] < 0 for t in TABLES):
        raise ValueError("Incomplete remote count snapshot")
    movements = plan.get("bank_movements")
    tenancies = plan.get("tenancies")
    if not isinstance(movements, list) or not isinstance(tenancies, list):
        raise ValueError("Invalid original bank or tenancy inventory")
    if (comparison.get("local_tenancies") != len(tenancies)
            or comparison.get("local_bank_rows") != len(movements)):
        raise ValueError("Section 02 snapshot does not match local source counts; compare again")
    if any(not isinstance(r, dict) for r in movements):
        raise ValueError("Invalid source bank row")
    bank_ids = [str(r.get("legacy_bank_row_id", "")).strip() for r in movements]
    # Missing or repeated IDs mean evidence cannot be mapped one-to-one.
    id_counts = Counter(bank_ids)
    duplicate_ids = sum(v - 1 for k, v in id_counts.items() if k and v > 1)
    missing_ids = sum(not k for k in bank_ids)
    fps = Counter(str(row.get("fingerprint", "")).strip() for row in movements)
    repeated_fingerprints = sum(v > 1 for k, v in fps.items() if k)
    status_counts = dict(Counter(str(row.get("migration_status", "unspecified"))
                                 for row in movements))
    clearance = _load_history(root, CHEQUE_CLEARANCES)
    allocations = _load_history(root, CHEQUE_ALLOCATIONS)
    reviews = _review_inventory(root)
    missing_evidence = list(plan.get("summary", {}).get("missing_evidence_files", []))
    # Evidence from an older Stage 1D plan must not be silently considered current.
    current_inventory = {x["name"]: x for x in plan.get("evidence_inventory", [])
                         if isinstance(x, dict) and "name" in x}
    changed = []
    for name in (CHEQUE_CLEARANCES, CHEQUE_ALLOCATIONS, REVIEW_EVIDENCE):
        item = current_inventory.get(name)
        path = Path(root) / name
        if item and item.get("exists") and path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                changed.append(name)
    latest_clearance = {str(item.get("original_credit_row_id")): item
                        for item in (clearance or [])}
    latest_allocation = {str(item.get("successful_credit_row_id")): item
                         for item in (allocations or [])}
    cheque_original_ids = {str(e.get("original_credit_row_id")) for e in latest_clearance.values()}
    cheque_return_ids = {str(e.get("returned_debit_row_id")) for e in latest_clearance.values()}
    cheque_success_ids = {str(e.get("successful_credit_row_id")) for e in latest_clearance.values()}
    cheque_ids = cheque_original_ids | cheque_return_ids | cheque_success_ids
    cheque_source_rows = sum(row_id in cheque_ids for row_id in bank_ids)
    held_reasons = {
        "unverified_individual_review": len(movements),
        "missing_legacy_row_id": missing_ids,
        "duplicate_legacy_row_id": duplicate_ids,
        "duplicate_fingerprint_groups": repeated_fingerprints,
        "cheque_related_source_rows": cheque_source_rows,
    }
    notes = [
        "No row is approved to import; 455 local rows does not mean 455 eligible receipts.",
        "Returned cheque original credits and reversal debits remain bank evidence, not rent income.",
        "Stage 1I approvals are NOT ledger postings and must remain pending.",
        "Bank reference alone cannot prove transaction identity or remove apparent duplicates.",
        "Tenancy review counts are inventory only; each decision requires bank-row-level matching before migration.",
        "Refresh Section 02 immediately before any future proposed import.",
    ]
    if changed:
        notes.append("Source JSON changed since Stage 1D inventory; rebuild the dry-run manifest.")
    return {
        "mode": "SECTION_03_PREVIEW_ONLY_NO_WRITES",
        "schema": SCHEMA,
        "local_tenancies": len(tenancies),
        "local_bank_rows": len(movements),
        "remote_counts_at_comparison": dict(counts),
        "preview_held_rows": len(movements),
        "approved_to_import_rows": 0,
        "approved_rent_postings": 0,
        "bank_row_statuses": status_counts,
        "held_reasons": held_reasons,
        "tenancy_reviews": reviews,
        "stage_1h_current_cheque_clearances": len(latest_clearance),
        "stage_1i_current_rent_allocations_not_posted": len(latest_allocation),
        "stage_1h_file_present": clearance is not None,
        "stage_1i_file_present": allocations is not None,
        "source_files_changed_since_stage_1d": changed,
        "missing_evidence_from_stage_1d": missing_evidence,
        "notes": notes,
    }
