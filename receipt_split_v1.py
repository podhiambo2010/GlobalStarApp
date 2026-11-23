"""Excel-only, row-specific receipt splits; accounting categories remain separate.

Deposit liability is not income. Advance rent is held until its contractual
period is verified; this module never posts automatic income or tax entries.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
import pandas as pd

from bank_review_v1 import load_review, write_review

KINDS = {"security_deposit", "advance_rent", "current_rent"}
CENT = Decimal("0.01")


def cents(value):
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError("Every component needs a valid amount")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Each component must be positive")
    return int(amount * 100)


def _date(value):
    try:
        value = pd.to_datetime(value, errors="raise")
    except (ValueError, TypeError):
        raise ValueError("A valid rental period date is required")
    if pd.isna(value):
        raise ValueError("A valid rental period date is required")
    return value.date()


def validate_split(row, tenancy, components, existing_decision=None):
    """Return canonical allocation components; exact cents and occupancy guards."""
    if not components or not isinstance(components, list):
        raise ValueError("Add at least one allocation component")
    bank_amount = cents(row.get("Money In Num"))
    if float(row.get("Money Out Num", 0) or 0) < 0:
        raise ValueError("Cannot split a debit as incoming rent")
    if existing_decision and existing_decision.get("decision") == "assign":
        raise ValueError("A full rent assignment exists. Resolve it before splitting.")
    if tenancy is None or bool(tenancy.get("Review_Required", True)):
        raise ValueError("The selected tenancy requires validation")
    if tenancy.get("Tenancy_Status") == "vacancy":
        raise ValueError("Cannot allocate a receipt to vacancy")
    start = _date(tenancy["Lease_Date_Parsed"])
    end = None if pd.isna(tenancy.get("End_Actual")) else _date(tenancy["End_Actual"])
    canonical = []
    total = 0
    for item in components:
        kind = str(item.get("kind", "")).strip()
        if kind not in KINDS:
            raise ValueError("Unsupported allocation category")
        amount = cents(item.get("amount"))
        total += amount
        detail = {"kind": kind, "amount_cents": amount, "period_start": None,
                  "period_end": None}
        if kind in {"advance_rent", "current_rent"}:
            begin = _date(item.get("period_start"))
            finish = _date(item.get("period_end"))
            if finish < begin:
                raise ValueError("Rent period end precedes its start")
            if begin < start or (end is not None and finish > end):
                raise ValueError("Rent periods must lie within the selected tenancy")
            detail["period_start"] = begin.isoformat()
            detail["period_end"] = finish.isoformat()
        canonical.append(detail)
    if total != bank_amount:
        raise ValueError(
            f"Allocation total KSh {total/100:,.2f} must equal original bank credit "
            f"KSh {bank_amount/100:,.2f}"
        )
    return canonical


def create_receipt_split(existing, bank_row_id, tenancy_id, row, tenancy,
                         components, evidence, actor=""):
    if not str(evidence).strip():
        raise ValueError("Documentary evidence / reason is required")
    if not str(bank_row_id).strip() or not str(tenancy_id).strip():
        raise ValueError("Bank row and individual tenancy must be selected")
    if bank_row_id in existing:
        raise ValueError("This bank row already has a split; use a reviewed correction workflow")
    validated = validate_split(row, tenancy, components)
    updated = dict(existing)
    updated[bank_row_id] = {
        "tenancy_id": str(tenancy_id),
        "original_amount_cents": cents(row.get("Money In Num")),
        "components": validated,
        "evidence": str(evidence).strip(),
        "actor": str(actor),
        "bank_reference": str(row.get("Ref_Clean", "")),
        "transaction_date": str(row.get("Transaction Date", "")),
    }
    return updated


def summarize_splits(register, stored, bank):
    """Attach split liability/advance and cash classification, not earned income."""
    result = register.copy()
    result["Deposit_Received"] = 0.0
    result["Advance_Rent_Received"] = 0.0
    result["Split_Current_Rent_Received"] = 0.0
    valid_ids = set(result["Tenancy_ID"].astype(str))
    bank_by_id = {str(row["Bank_Row_ID"]): row for _, row in bank.iterrows()}
    for bank_id, split in stored.items():
        if bank_id not in bank_by_id:
            continue
        target = str(split.get("tenancy_id", ""))
        if target not in valid_ids:
            continue
        source = bank_by_id[bank_id]
        if cents(source.get("Money In Num")) != split.get("original_amount_cents"):
            continue
        column_map = {
            "security_deposit": "Deposit_Received",
            "advance_rent": "Advance_Rent_Received",
            "current_rent": "Split_Current_Rent_Received",
        }
        for item in split.get("components", []):
            column = column_map.get(item.get("kind"))
            if column:
                mask = result["Tenancy_ID"] == target
                result.loc[mask, column] += float(item["amount_cents"]) / 100
    return result


def load_splits(path):
    return load_review(path)


def save_splits(path, entries):
    write_review(path, entries)
