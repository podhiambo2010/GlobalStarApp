"""Section 04A — local evidence inventory. NEVER writes, migrates, or repairs sources.

Run:
    python section04a_evidence_audit.py --backup D:\\Projects\\GlobalStarApp_Backup_20261126
Optional: --output D:\\Projects\\GlobalStarApp_Backup_20261126\\GSIL_Section04A_live_comparison.json

All amounts and decisions remain as stored. Produces an evidence-only report.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


FILES = {
    "live_reviews": "tenancy_bank_reviews_v1.json",
    "audit_history": "tenancy_bank_review_history_v1.json",
    "clearances": "cheque_clearance_reviews_v1h.json",
    "allocations": "cheque_allocations_v1i.json",
    "ignored": "ignored_transactions.json",
    "reassignments": "reassignments.json",
}
BACKUP_REVIEWS = "GlobalStar_V1_Tenancy_Bank_Review_Backup.json"


def read_json(path: Path, *, optional=False):
    if not path.is_file():
        if optional:
            return None, {"present": False}
        raise ValueError(f"Required evidence file missing: {path.name}; do not replace it with old data")
    original = path.read_bytes()
    try:
        data = json.loads(original.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid evidence JSON: {path.name}; preserve the original file") from exc
    return data, {"present": True, "sha256": sha256(original).hexdigest(), "bytes": len(original)}


def summarize(root: Path, backup: Path):
    original = {}
    integrity = {}
    for key, filename in FILES.items():
        original[key], integrity[key] = read_json(root / filename,
                                                 optional=key in {"ignored", "reassignments"})
    exported, integrity["archived_reviews"] = read_json(backup / BACKUP_REVIEWS)
    reviews, events = original["live_reviews"], original["audit_history"]
    if not isinstance(reviews, dict) or not isinstance(exported, dict):
        raise ValueError("Live and archived reviews must be JSON objects")
    if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
        raise ValueError("Audit history must be an array of event objects")
    if any(not isinstance(v, dict) for v in reviews.values()):
        raise ValueError("A live review is malformed; no decisions were changed")
    if any(not isinstance(v, dict) for v in exported.values()):
        raise ValueError("An archived review is malformed")
    for key in ("clearances", "allocations"):
        if not isinstance(original[key], dict) or not isinstance(original[key].get("history"), list):
            raise ValueError(f"Invalid append-only evidence structure: {FILES[key]}")
    live_ids, archive_ids = set(reviews), set(exported)
    conflicts = [rowid for rowid in sorted(live_ids & archive_ids)
                 if reviews[rowid] != exported[rowid]]
    orphaned_audit_ids = set()
    audit_counts = Counter()
    audit_ids = set()
    for event in events:
        action = str(event.get("action", "missing"))
        audit_counts[action] += 1
        rowid = str(event.get("bank_row_id", ""))
        if rowid:
            audit_ids.add(rowid)
            if rowid not in live_ids:
                orphaned_audit_ids.add(rowid)
    cheque_hist = original["clearances"]["history"]
    allocation_hist = original["allocations"]["history"]
    latest_clearance = {}
    for e in cheque_hist:
        if not isinstance(e, dict) or not e.get("original_credit_row_id"):
            raise ValueError("Malformed cheque clearance event")
        latest_clearance[str(e["original_credit_row_id"])] = e
    latest_allocation = {}
    for e in allocation_hist:
        if not isinstance(e, dict) or not e.get("successful_credit_row_id"):
            raise ValueError("Malformed cheque allocation event")
        latest_allocation[str(e["successful_credit_row_id"])] = e
    unposted = [e for e in latest_allocation.values() if e.get("rent_posted") is False]
    unexpected_postings = [e for e in latest_allocation.values() if e.get("rent_posted") is not False]
    status = "REQUIRES_MANUAL_RECONCILIATION" if conflicts or orphaned_audit_ids or unexpected_postings or (live_ids != archive_ids) else "EVIDENCE_INVENTORIED_NOT_AUTHORIZED_FOR_MIGRATION"
    return {
        "mode": "SECTION_04A_READ_ONLY_EVIDENCE_INVENTORY",
        "migration_authorized": False,
        "supabase_writes": 0,
        "source_writes": 0,
        "status": status,
        "integrity": integrity,
        "live_decisions": len(reviews),
        "archived_decisions": len(exported),
        "live_decision_types": dict(sorted(Counter(str(v.get("decision", "unknown")) for v in reviews.values()).items())),
        "archived_decision_types": dict(sorted(Counter(str(v.get("decision", "unknown")) for v in exported.values()).items())),
        "ids_in_both": len(live_ids & archive_ids),
        "only_in_live": sorted(live_ids - archive_ids),
        "only_in_archive": sorted(archive_ids - live_ids),
        "content_conflicts_for_shared_ids": conflicts,
        "audit_events": len(events),
        "audit_actions": dict(sorted(audit_counts.items())),
        "audit_ids_not_in_live_register": sorted(orphaned_audit_ids),
        "live_review_ids_without_audit_event": sorted(live_ids - audit_ids),
        "cheque_clearance_history_events": len(cheque_hist),
        "latest_cheques": len(latest_clearance),
        "cheque_allocation_history_events": len(allocation_hist),
        "latest_unposted_allocation_count": len(unposted),
        "unexpected_allocation_posting_status_count": len(unexpected_postings),
        "notes": [
            "Historical references cannot automatically override individual bank-row reviews.",
            "Audit omissions or differing archive records are not automatically lost or duplicated payments.",
            "Append-only cheque amendments must be preserved in chronological history.",
            "Inspect unresolved differences before a separate authorized write migration.",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--backup", type=Path, required=True)
    p.add_argument("--output", type=Path, help="Optional JSON output file; never overwrite")
    args = p.parse_args(argv)
    try:
        result = summarize(args.root, args.backup)
    except (OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}")
        return 1
    print("Section 04A local evidence inventory — NO database writes")
    for key in ("status", "live_decisions", "archived_decisions", "ids_in_both",
                "audit_events", "cheque_clearance_history_events",
                "cheque_allocation_history_events", "latest_unposted_allocation_count"):
        print(f"{key}: {result[key]}")
    for key in ("only_in_live", "only_in_archive", "content_conflicts_for_shared_ids",
                "audit_ids_not_in_live_register"):
        print(f"{key}: {len(result[key])}")
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print("Diagnostic report saved:", args.output)
        except FileExistsError:
            print("BLOCKED: diagnostic output already exists; original not overwritten")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
