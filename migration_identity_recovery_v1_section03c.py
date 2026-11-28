"""Section 03C: historical review identity evidence, strictly read-only.

Investigates the existing append-only bank-review history first. Optional
historical statement frames may supply exact archived bank-row identity.
No inferred reference matches and no changes to reviews, bank data or Supabase.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json

from bank_review_v1 import bank_row_ids
from migration_classification_v1_section03a import _read_reviews

HISTORY_FILE = "tenancy_bank_review_history_v1.json"
REQUIRED_COLUMNS = ("Transaction Date", "Value Date", "Transaction Details",
                    "Money In Num", "Money Out Num")


def _read_history(root):
    path = Path(root) / HISTORY_FILE
    if not path.is_file():
        return [], None
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError("Bank review audit history is malformed; inspection blocked")
    return raw, hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_historical_identity(discrepancy, full_source, root=".", historical_bank=None):
    """Only reporting; historical bank-row exact ID is evidence, not a reassignment."""
    if not isinstance(discrepancy, dict) or discrepancy.get("mode") != "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES":
        raise ValueError("Run original Section 03B discrepancy report first")
    if not isinstance(full_source, dict) or full_source.get("mode") != "SECTION_03B_FULL_SOURCE_DIAGNOSTIC_NO_WRITES":
        raise ValueError("Run full original statement verification before Section 03C")
    reviews, review_path = _read_reviews(root)
    signature = hashlib.sha256(review_path.read_bytes()).hexdigest()
    if signature != discrepancy.get("review_register_sha256"):
        raise ValueError("Review register changed since Section 03B; rerun earlier checks")
    missing = full_source.get("unmatched_review_evidence", [])
    if (not isinstance(missing, list) or len(missing) != discrepancy.get("unmatched_historical_reviews")
            or {r["historical_bank_row_id"] for r in missing}
               != {r["historical_bank_row_id"] for r in discrepancy.get("unmatched_review_details", [])}):
        raise ValueError("Discrepancy inventories differ; rerun full-source verification")
    history, history_sha = _read_history(root)
    by_row = defaultdict(list)
    for event in history:
        rowid = str(event.get("bank_row_id", "")).strip()
        if rowid:
            by_row[rowid].append(event)
    archived = {}
    archive_sha = None
    archive_rows = 0
    if historical_bank is not None:
        if not hasattr(historical_bank, "columns") or not set(REQUIRED_COLUMNS).issubset(historical_bank.columns):
            raise ValueError("Historical file requires normalized date, narration and debit/credit columns")
        if "Ref_Clean" not in historical_bank.columns and "Bank Reference Number" not in historical_bank.columns:
            raise ValueError("Historical file needs Ref_Clean or Bank Reference Number")
        frame = historical_bank.copy(deep=True)
        computed = bank_row_ids(frame)
        if len(set(computed)) != len(computed):
            raise ValueError("Historical statement produced duplicate bank IDs")
        for row_id in computed:
            archived.setdefault(row_id, 0)
            archived[row_id] += 1
        archive_rows = len(frame)
        # Hash of the canonical computed identity sequence, not sensitive narrations.
        archive_sha = hashlib.sha256("\n".join(computed).encode("utf-8")).hexdigest()
    out = []
    states = Counter()
    for record in missing:
        rowid = record["historical_bank_row_id"]
        events = by_row.get(rowid, [])
        in_archive = rowid in archived
        if in_archive:
            state = "exact_bank_row_id_found_in_historical_statement"
        elif events:
            state = "audit_history_found_bank_row_not_in_supplied_statements"
        elif historical_bank is not None:
            state = "not_found_in_historical_statement_or_audit"
        else:
            state = "no_matching_audit_event_historical_statement_not_provided"
        states[state] += 1
        out.append({
            "historical_bank_row_id": rowid,
            "original_review_decision": record["review_decision"],
            "historical_tenancy_id": record["review_tenancy_id"],
            "matching_audit_events": len(events),
            "audit_actions": " | ".join(str(e.get("action", "")) for e in events),
            "exact_row_id_in_historical_statement": in_archive if historical_bank is not None else None,
            "identity_evidence_status": state,
            "original_review_preserved": True,
            "automatically_reassigned": False,
            "bank_payment_posted": False,
        })
    return {
        "mode": "SECTION_03C_HISTORICAL_IDENTITY_DIAGNOSTIC_NO_WRITES",
        "original_unmatched_reviews": len(missing),
        "historical_review_audit_file_present": history_sha is not None,
        "historical_audit_events_total": len(history),
        "historical_audit_sha256": history_sha,
        "historical_statement_provided": historical_bank is not None,
        "historical_statement_rows": archive_rows,
        "historical_statement_identity_sha256": archive_sha,
        "evidence_categories": dict(sorted(states.items())),
        "review_records": out,
        "stale_tenancy_details_unchanged": full_source.get("stale_tenancy_evidence", []),
        "interpretation": (
            "Matching a historical ID proves only that the same generated row identity "
            "appeared in that source; it does not prove financial posting, tenancy ownership "
            "or equivalence to a row in the current statement."
        ),
        "approved_imports": 0,
        "approved_rent_postings": 0,
        "local_writes": False,
        "supabase_writes": False,
    }
