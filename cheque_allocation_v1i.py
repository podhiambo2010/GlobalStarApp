"""Stage 1I: auditable cleared-cheque allocation decisions, WITHOUT ledger posting.

The register is independent of Stage 1H and original bank rows. Any application
to the rent ledger must occur in a later, idempotent posting workflow.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import tempfile

VERSION = 1
STATUS = "allocation_approved_ledger_pending"


def _load(path):
    p = Path(path)
    if not p.exists():
        return {"schema_version": VERSION, "history": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != VERSION or not isinstance(data.get("history"), list):
        raise ValueError("Unrecognized allocation register; refusing to overwrite")
    for event in data["history"]:
        if not isinstance(event, dict) or "successful_credit_row_id" not in event:
            raise ValueError("Invalid audit history; refusing to overwrite")
    return data


def latest_allocations(path):
    result = {}
    for event in _load(path)["history"]:
        result[event["successful_credit_row_id"]] = event
    return result


def _latest_clearances(clearance_path):
    from cheque_clearance_v1h import latest_reviews
    return latest_reviews(clearance_path)


def eligible_clearance(clearance_path, successful_credit_row_id):
    current = [
        event for event in _latest_clearances(clearance_path).values()
        if event.get("successful_credit_row_id") == successful_credit_row_id
    ]
    if len(current) != 1:
        raise ValueError("Credit must resolve to exactly one current Stage 1H clearance")
    event = current[0]
    if (event.get("status") != "bank_cleared_pending_allocation"
            or not event.get("verified_bank_posting")
            or not event.get("checked_no_later_reversal")
            or event.get("rent_posted") is not False):
        raise ValueError("Stage 1H does not support allocation of this credit")
    return event


def record_allocation(path, clearance_path, *, successful_credit_row_id,
                      tenancy_id, rent_period, amount_ksh, reviewer,
                      explanation, verified_period, verified_amount,
                      confirmed, amend=False, correction_reason=""):
    source = eligible_clearance(clearance_path, successful_credit_row_id)
    if str(tenancy_id) != str(source["tenancy_id"]):
        raise ValueError("Tenancy differs from the current Stage 1H clearance")
    if not (verified_period and verified_amount and confirmed):
        raise ValueError("Independent period, amount and receipt confirmations required")
    if len(str(reviewer).strip()) < 3 or len(str(explanation).strip()) < 15:
        raise ValueError("Reviewer and allocation evidence (15+ characters) required")
    try:
        period = date.fromisoformat(str(rent_period))
        amount = Decimal(str(amount_ksh)).quantize(Decimal("0.01"))
        credit = Decimal(str(source["amount_ksh"])).quantize(Decimal("0.01"))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("Invalid rent period or monetary value") from exc
    if period.day != 1:
        raise ValueError("Rent period must be the first day of the corresponding month")
    if amount <= 0 or amount != credit:
        raise ValueError("This workflow allocates the complete cheque credit only")
    if str(source["successful_credit_date"]) != "2025-11-11":
        raise ValueError("Expected successful posting on 11 November 2025")
    data = _load(path)
    latest = latest_allocations(path).get(str(successful_credit_row_id))
    if latest and not amend:
        raise ValueError("This successful bank credit is already allocated; use audited amendment")
    if amend and not latest:
        raise ValueError("No prior allocation exists to amend")
    if amend and len(str(correction_reason).strip()) < 20:
        raise ValueError("Amendment requires a reason of at least 20 characters")
    if latest and latest.get("status") != STATUS:
        raise ValueError("Prior allocation is in an unexpected state; investigate")
    if latest and (str(latest.get("tenancy_id")) == str(tenancy_id)
                   and latest.get("rent_period") == period.isoformat()
                   and latest.get("amount_ksh") == str(amount)):
        raise ValueError("Allocation is unchanged; no duplicate audit event permitted")
    event = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": STATUS,
        "cheque_number": str(source["cheque_number"]),
        "original_credit_row_id": str(source["original_credit_row_id"]),
        "returned_debit_row_id": str(source["returned_debit_row_id"]),
        "successful_credit_row_id": str(source["successful_credit_row_id"]),
        "successful_credit_reference": str(source["successful_credit_reference"]),
        "successful_credit_date": str(source["successful_credit_date"]),
        "tenancy_id": str(tenancy_id),
        "tenant_name": str(source["tenant_name"]),
        "rent_period": period.isoformat(),
        "amount_ksh": str(amount),
        "reviewer": str(reviewer).strip(),
        "explanation": str(explanation).strip(),
        "verified_period": True,
        "verified_amount": True,
        "rent_posted": False,
        "amendment": bool(amend),
        "correction_reason": str(correction_reason).strip() if amend else "",
        "prior_recorded_at_utc": latest["recorded_at_utc"] if latest else None,
    }
    data["history"].append(event)
    root = Path(path)
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root.parent,
                                         prefix=".cheque_allocation_", suffix=".tmp",
                                         delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return event
