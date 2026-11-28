"""Section 04B read-only staging manifest for reviewed evidence.

No database imports, ledger posting, JSON source changes or automatic matches.
Output is a local, confidential, full-detail staging manifest; keep it off Git.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path

from section04a_evidence_audit import FILES, BACKUP_REVIEWS, read_json, summarize

MODE = "SECTION_04B_READ_ONLY_STAGING_MANIFEST"


def _money(raw):
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Malformed allocation monetary amount") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Invalid allocation amount or precision")
    return amount


def build_manifest(root, backup):
    root, backup = Path(root), Path(backup)
    comparison = summarize(root, backup)
    if comparison["status"] != "EVIDENCE_INVENTORIED_NOT_AUTHORIZED_FOR_MIGRATION":
        raise ValueError("Section 04A reported conflicts or missing evidence; migration preview blocked")
    if comparison["split_register_ids_without_split_audit"]:
        raise ValueError("Split register contains entries lacking an audit action")
    if comparison["live_review_ids_without_audit_event"]:
        raise ValueError("Live review decisions lacking audit events require inspection")
    originals = {}
    for key, name in FILES.items():
        originals[key], _ = read_json(root / name, optional=key in {"ignored", "reassignments"})
    archive, _ = read_json(backup / BACKUP_REVIEWS)
    # Section 04A already establishes the exact same record contents for the 53
    # overlapping decisions. Retain both hashes; don't merge by bank reference.
    reviews = originals["live_reviews"]
    if reviews != archive:
        raise ValueError("Live reviews disagree with archival decisions")
    histories = {
        "individual_review_audit": originals["audit_history"],
        "cheque_clearance": originals["clearances"]["history"],
        "cheque_allocation": originals["allocations"]["history"],
    }
    events = []
    for kind, items in histories.items():
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Malformed event in {kind} index {i}")
            events.append({
                "source_kind": kind,
                "source_record_key": str(item.get("bank_row_id")
                    or item.get("original_credit_row_id")
                    or item.get("successful_credit_row_id") or ""),
                "source_event_index": i,
                "historical_evidence_only": True,
                "payload": item,
            })
    for key, item in sorted(reviews.items()):
        events.append({
            "source_kind": "current_individual_review",
            "source_record_key": str(key),
            "source_event_index": 0,
            "historical_evidence_only": True,
            "payload": item,
        })
    for key, item in sorted(originals["receipt_splits"].items()):
        events.append({
            "source_kind": "current_receipt_split",
            "source_record_key": str(key),
            "source_event_index": 0,
            "historical_evidence_only": True,
            "payload": item,
        })
    # Legacy mappings and ignored references are hints ONLY, never decisions
    # to automatically apply to new statement rows.
    for name, item in (("legacy_reference_ignored", originals["ignored"]),
                       ("legacy_reference_reassignment", originals["reassignments"])):
        for key, value in sorted((item or {}).items()):
            events.append({
                "source_kind": name,
                "source_record_key": str(key),
                "source_event_index": 0,
                "historical_evidence_only": True,
                "reference_only_cannot_autopost": True,
                "payload": value,
            })
    latest_clearances = {}
    for e in histories["cheque_clearance"]:
        latest_clearances[e["original_credit_row_id"]] = e
    latest_allocations = {}
    for e in histories["cheque_allocation"]:
        latest_allocations[e["successful_credit_row_id"]] = e
    approved = []
    for e in latest_allocations.values():
        if e.get("rent_posted") is not False:
            raise ValueError("A posted or uncertain allocation is outside the read-only manifest")
        matches = [c for c in latest_clearances.values()
                   if c.get("successful_credit_row_id") == e.get("successful_credit_row_id")]
        if len(matches) != 1 or matches[0].get("status") != "bank_cleared_pending_allocation":
            raise ValueError("No unique approved clearance for cheque allocation")
        cleared = matches[0]
        if (str(cleared.get("tenancy_id")) != str(e.get("tenancy_id")) or
            str(cleared.get("cheque_number")) != str(e.get("cheque_number"))):
            raise ValueError("Allocation does not match latest verified cheque review")
        periods = e.get("allocations") or [{
            "rent_period": e.get("rent_period"), "amount_ksh": e.get("amount_ksh")
        }]
        if sum((_money(x.get("amount_ksh")) for x in periods), Decimal("0")) != _money(e.get("amount_ksh")):
            raise ValueError("Cheque period allocation does not equal approved cleared amount")
        approved.append({
            "cheque_number": str(e.get("cheque_number")),
            "successful_credit_row_id": str(e.get("successful_credit_row_id")),
            "approved_allocation_ksh": str(e["amount_ksh"]),
            "periods": periods,
            "posting_state": "APPROVED_LEDGER_PENDING",
        })
    keys = [(e["source_kind"], e["source_record_key"], e["source_event_index"]) for e in events]
    if len(keys) != len(set(keys)):
        raise ValueError("Repeated staging identity; cannot safely plan migration")
    counts = Counter(e["source_kind"] for e in events)
    return {
        "mode": MODE, "schema": "gs_streamlit_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "PREVIEW_NOT_AUTHORIZED_FOR_IMPORT",
        "supabase_writes": 0, "rent_postings": 0, "source_writes": 0,
        "import_approved": False,
        "source_integrity": comparison["integrity"],
        "comparison": {
            "live_reviews": comparison["live_decisions"],
            "archived_reviews": comparison["archived_decisions"],
            "audit_events": comparison["audit_events"],
            "receipt_splits": comparison["receipt_split_records"],
            "matching_split_audit_ids": comparison["split_receipt_audit_ids_verified_in_split_register"],
            "unresolved_audit_ids": comparison["audit_ids_not_in_live_register"],
            "review_conflicts": comparison["content_conflicts_for_shared_ids"],
        },
        "staging_event_counts": dict(sorted(counts.items())),
        "staging_events": events,
        "approved_allocations_still_unposted": approved,
        "notes": [
            "Audit log events and current review snapshots are distinct evidence types, not duplicate payment postings.",
            "Legacy reference-only exclusions or assignments are historical hints, not automatic new-bank-row decisions.",
            "A cleared cheque is not the same as a rent ledger posting.",
            "This manifest contains private financial evidence: do not commit it to source control.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(args.root, args.backup)
        # Exclusive create: refuses overwriting previous evidence.
        with args.output.open("x", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        print("Section 04B preview generated (NO DATABASE WRITES)")
        print("Audit events:", manifest["comparison"]["audit_events"])
        print("Receipt splits:", manifest["comparison"]["receipt_splits"])
        print("Staging evidence records:", len(manifest["staging_events"]))
        print("Cheque allocations still unposted:", len(manifest["approved_allocations_still_unposted"]))
        print("Manifest saved privately:", args.output)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("BLOCKED:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
