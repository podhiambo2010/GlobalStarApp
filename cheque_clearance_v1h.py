"""Stage 1H: local, append-only cheque clearance evidence; no ledger postings.

Treat returned deposit and debit as zero net cash. A later positive credit may
only be marked bank-cleared after manual evidence review. This register does
not assign rent, update bank rows, or authorize migration.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import tempfile

SCHEMA_VERSION = 1
STATUSES = ("bank_cleared_pending_allocation", "not_cleared", "needs_investigation")


def _check_candidate(candidate, later):
    if len(candidate.get("later_credit_candidates", [])) != 1:
        raise ValueError("Clearance requires exactly one unambiguous later credit")
    identified = candidate["later_credit_candidates"][0]
    if identified.get("bank_row_id") != later.get("bank_row_id"):
        raise ValueError("Later credit must match the displayed original bank row")
    required = ("credit_row_id", "debit_row_id", "cheque_number", "amount_ksh")
    if any(not str(candidate.get(field, "")).strip() for field in required):
        raise ValueError("Incomplete cheque return evidence")
    if not str(later.get("bank_row_id", "")).strip() or not str(later.get("reference", "")).strip():
        raise ValueError("Missing later bank credit identity or reference")
    try:
        amount = Decimal(str(candidate["amount_ksh"]))
        later_amount = Decimal(str(later["amount_ksh"]))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid cheque amount") from exc
    if amount <= 0 or later_amount != amount:
        raise ValueError("Later credit amount does not match returned cheque")
    if str(later["date"]) <= str(candidate["transaction_date"]):
        raise ValueError("Later posting must follow the return date")


def record_clearance(path, candidate, later, *, tenancy_id, tenant_name,
                     status, reviewer, explanation, verified_bank_posting,
                     checked_no_later_reversal, corrective_review=False, correction_reason=""):
    """Append a review event, retaining any earlier decision as historical evidence.

    No record is created unless the reviewer explicitly confirms both bank
    posting and absence of later reversal for a cleared decision.
    """
    _check_candidate(candidate, later)
    if status not in STATUSES:
        raise ValueError("Unknown clearance status")
    if not str(tenancy_id).strip() or not str(tenant_name).strip():
        raise ValueError("Exact tenancy is required; do not infer by cheque narration")
    if len(str(reviewer).strip()) < 3 or len(str(explanation).strip()) < 15:
        raise ValueError("Reviewer and specific supporting evidence are required")
    if status == "bank_cleared_pending_allocation" and (
        not verified_bank_posting or not checked_no_later_reversal
    ):
        raise ValueError("Clearance requires confirmed bank posting and reversal review")
    root = Path(path)
    if root.exists():
        data = json.loads(root.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("history"), list):
            raise ValueError("Unexpected register format; do not overwrite")
    else:
        data = {"schema_version": SCHEMA_VERSION, "history": []}
    event = {
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "cheque_number": str(candidate["cheque_number"]),
        "amount_ksh": str(candidate["amount_ksh"]),
        "original_credit_row_id": str(candidate["credit_row_id"]),
        "returned_debit_row_id": str(candidate["debit_row_id"]),
        "successful_credit_row_id": str(later["bank_row_id"]),
        "successful_credit_reference": str(later["reference"]),
        "successful_credit_date": str(later["date"]),
        "tenancy_id": str(tenancy_id),
        "tenant_name": str(tenant_name),
        "status": status,
        "reviewer": str(reviewer).strip(),
        "explanation": str(explanation).strip(),
        "verified_bank_posting": bool(verified_bank_posting),
        "checked_no_later_reversal": bool(checked_no_later_reversal),
        "rent_posted": False,
        "allocation_approved": False,
    }
    # Keep the original review. An explicit correction may change the tenancy
    # only for the SAME cheque and the SAME later bank credit.
    conflicts = [
        old for old in data["history"]
        if old.get("successful_credit_row_id") == event["successful_credit_row_id"]
        and (old.get("original_credit_row_id") != event["original_credit_row_id"]
             or old.get("tenancy_id") != event["tenancy_id"])
    ]
    if conflicts:
        if any(old.get("original_credit_row_id") != event["original_credit_row_id"]
               for old in conflicts):
            raise ValueError("Later credit assigned to another cheque; investigate")
        if not corrective_review or len(str(correction_reason).strip()) < 20:
            raise ValueError("Historical tenancy conflict: confirm correction and give a reason (20+ characters)")
        event["corrects_prior_tenancy"] = True
        event["correction_reason"] = str(correction_reason).strip()
        event["previous_tenancy_ids"] = sorted({str(old["tenancy_id"]) for old in conflicts})
    elif corrective_review:
        raise ValueError("No historical tenancy mismatch to correct")
    if data["history"] and data["history"][-1] == event:
        return event
    data["history"].append(event)
    root.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root.parent,
                                         prefix=".cheque_review_", suffix=".tmp",
                                         delete=False) as handle:
            tmp_path = handle.name
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, root)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return event


def latest_reviews(path):
    root = Path(path)
    if not root.exists():
        return {}
    data = json.loads(root.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("history"), list):
        raise ValueError("Unexpected clearance register structure")
    latest = {}
    for event in data["history"]:
        latest[event["original_credit_row_id"]] = event
    return latest
