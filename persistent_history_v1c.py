"""Stage 1C: deterministic, review-first KCB statement staging.

Never silently decide whether two identical-looking rows are one bank event
or two distinct credits; such groups need a bank-issued unique identifier.
This module has no database credentials and makes no accounting postings.
"""
from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

BASELINE = date(2025, 9, 1)


def _money(value):
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid bank amount") from exc
    if not number.is_finite() or number == 0 or number.as_tuple().exponent < -2:
        raise ValueError("Bank movement must have a nonzero amount with <=2 decimals")
    return number.quantize(Decimal("0.01"))


def statement_digest(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()


def fingerprint(account_key, transaction_date, amount, description, reference=None,
                unique_bank_id=None):
    """Stable across overlapping files, not derived from workbook row number."""
    if not account_key or not description:
        raise ValueError("Bank account and narration are required")
    if not isinstance(transaction_date, date):
        raise ValueError("Transaction date must be a date")
    identifying = {
        "account": str(account_key).strip(),
        "date": transaction_date.isoformat(),
        "amount": str(_money(amount)),
        "description": re.sub(r"\s+", " ", str(description)).strip().casefold(),
        "reference": str(reference or "").strip().casefold(),
        "bank_id": str(unique_bank_id or "").strip().casefold(),
    }
    return hashlib.sha256(json.dumps(identifying, sort_keys=True).encode()).hexdigest()


def plan_statement_import(account_key, rows, existing_fingerprints=()):
    """Return stages; identical-looking rows are held for manual duplicate verification."""
    existing = set(existing_fingerprints)
    prepared = []
    for row in rows:
        fp = fingerprint(account_key, row["transaction_date"], row["amount"],
                         row["description"], row.get("reference"),
                         row.get("unique_bank_id"))
        prepared.append((fp, row))
    counts = Counter(fp for fp, _ in prepared)
    staged, duplicated, ambiguous, possible_overlap = [], [], [], []
    for fp, row in prepared:
        result = {"fingerprint": fp, "row": row}
        if counts[fp] > 1 and not row.get("unique_bank_id"):
            ambiguous.append(result)
        elif fp in existing and row.get("unique_bank_id"):
            duplicated.append(result)
        elif fp in existing:
            possible_overlap.append(result)
        else:
            staged.append(result)
    return {"new": staged, "already_seen": duplicated,
            "possible_overlap": possible_overlap,
            "ambiguous_same_statement": ambiguous}


def opening_baseline(tenancies, as_of=BASELINE):
    """Prepare ZERO *rent* openings only for tenancies that had commenced.
    
    Deposit assumptions and refunds belong in separate deposit accounts.
    No assumptions about cash payments are generated here.
    """
    output = []
    for tenancy in tenancies:
        start = tenancy.get("start_date")
        if start is None:
            continue
        if not isinstance(start, date):
            raise ValueError("Tenancy start_date must be date")
        if start > as_of or tenancy.get("status") == "vacancy":
            continue
        output.append({
            "tenancy_id": str(tenancy["tenancy_id"]),
            "baseline_date": as_of.isoformat(),
            "amount": "0.00",
            "evidence_state": "assumed_zero",
            "evidence_note": "Owner-authorized opening RENT balance assumption, "
                             "not historical debt or cash verification.",
        })
    return output


def proposed_receipt_split(receipt_amount, outstanding_deposit, matched_tenancy,
                           verified_receipt=False):
    """Suggest, never autoapprove, deposit-first handling for new tenants."""
    received = _money(receipt_amount)
    if received < 0:
        raise ValueError("Deposit-first split accepts incoming credits only")
    deposit = Decimal(str(outstanding_deposit))
    if not deposit.is_finite() or deposit < 0:
        raise ValueError("Outstanding deposit must be nonnegative")
    if not matched_tenancy or not verified_receipt:
        return {"status": "manual_identity_or_receipt_review", "deposit": None,
                "remainder": None}
    applied = min(received, deposit)
    return {
        "status": "proposed_only_verify_rent_period",
        "deposit": str(applied.quantize(Decimal("0.01"))),
        "remainder": str((received - applied).quantize(Decimal("0.01"))),
    }
