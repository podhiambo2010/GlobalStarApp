"""Stage 1D: read-only, source-preserving reconciliation manifest.

This module does NOT connect to Supabase or alter local evidence. A dry run is
mandatory before any database ingestion. It keeps bank row identity, legacy
decisions, and opening-balance assumptions separate.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from persistent_history_v1c import fingerprint

REVIEW_FILES = (
    "tenancy_bank_reviews_v1.json",
    "tenancy_bank_review_history_v1.json",
    "tenancy_receipt_splits_v1.json",
    "ignored_transactions.json",
    "reassignments.json",
    "opening_balances_v1.json",
    "bank_reporting_baseline_v1.json",
)


def _date(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError("Unrecognized bank date: " + raw[:40])


def _amount(raw):
    try:
        amount = Decimal(str(raw).replace(",", "").strip())
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("Invalid amount") from exc
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        raise ValueError("Invalid amount precision")
    return amount.quantize(Decimal("0.01"))


def evidence_inventory(folder="."):
    """File names, existence, hash and structural validity; never edit data."""
    root = Path(folder)
    records = []
    for name in REVIEW_FILES:
        path = root / name
        entry = {"name": name, "exists": path.is_file()}
        if path.is_file():
            raw = path.read_bytes()
            entry["sha256"] = hashlib.sha256(raw).hexdigest()
            entry["bytes"] = len(raw)
            try:
                obj = json.loads(raw)
                if name == "opening_balances_v1.json":
                    valid = (isinstance(obj, dict)
                             and isinstance(obj.get("balances"), dict)
                             and isinstance(obj.get("history"), list))
                    entry["items"] = len(obj.get("balances", {})) if valid else None
                else:
                    valid = isinstance(obj, (dict, list))
                    entry["items"] = len(obj) if valid else None
                entry["valid_json_structure"] = bool(valid)
            except (UnicodeDecodeError, json.JSONDecodeError):
                entry["valid_json_structure"] = False
                entry["items"] = None
        records.append(entry)
    return records


def bank_overlap_dry_run(frame, account_key, previously_seen=()):
    """Use original unfiltered movements, holding identical-looking rows.

    Repeated transaction details across statements are NOT automatically
    discarded. Reference numbers are not guaranteed globally unique.
    """
    if not str(account_key).strip():
        raise ValueError("Specify bank account identity to prevent cross-account merging")
    rows = []
    seen = set(previously_seen)
    for _, r in frame.iterrows():
        incoming = _amount(r.get("Money In Num", 0))
        outgoing = _amount(r.get("Money Out Num", 0))
        if incoming == 0 and outgoing == 0:
            continue
        if incoming != 0 and outgoing != 0:
            raise ValueError("A bank row contains both money in and money out")
        direction = "credit" if incoming != 0 else "debit"
        amount = incoming if incoming != 0 else -outgoing
        day = _date(r.get("Transaction Date"))
        ref = str(r.get("Ref_Clean", "")).strip()
        if ref.casefold() == "nan":
            ref = ""
        desc = str(r.get("Transaction Details", "")).strip()
        bank_id = r.get("Bank Unique ID")  # only use when actually issued by bank
        if not bank_id or str(bank_id).strip().lower() == "nan":
            bank_id = None
        fp = fingerprint(account_key, day, amount, desc, ref, bank_id)
        rows.append({
            "legacy_bank_row_id": str(r.get("Bank_Row_ID", "")),
            "fingerprint": fp, "transaction_date": day.isoformat(),
            "amount": str(amount), "direction": direction,
            "reference": ref, "description": desc,
            "bank_unique_id": str(bank_id) if bank_id else None,
        })
    counts = Counter(r["fingerprint"] for r in rows)
    for row in rows:
        fp = row["fingerprint"]
        if counts[fp] > 1:
            row["migration_status"] = "ambiguous_identical_rows"
        elif fp in seen and row["bank_unique_id"]:
            row["migration_status"] = "previously_imported_verified_identifier"
        elif fp in seen:
            row["migration_status"] = "possible_overlap_review"
        else:
            row["migration_status"] = "new_staging_candidate"
    return rows


def prepare_local_migration(register, bank, opening_data, account_key,
                            folder=".", previously_seen=()):
    """Return JSON-serializable plan. No external I/O except reading inventory."""
    if not isinstance(opening_data, dict) or not isinstance(
        opening_data.get("balances"), dict
    ):
        raise ValueError("Opening balance evidence must be validated first")
    identities = {}
    for _, item in register.iterrows():
        tid = str(item.get("Tenancy_ID", "")).strip()
        if not tid or tid == "nan":
            raise ValueError("Tenancy record lacks an exact ID")
        if tid in identities:
            raise ValueError("Duplicate tenancy ID: " + tid)
        identities[tid] = {
            "tenancy_id": tid,
            "unit_code": str(item.get("Shop #", "")).strip(),
            "tenant_name": str(item.get("Tenant Name", "")).strip(),
            "report_status": str(item.get("Report_Status", "")).strip(),
            "tenancy_status": str(item.get("Tenancy_Status", "")).strip(),
        }
    for tid in opening_data["balances"]:
        if tid not in identities:
            raise ValueError("Opening evidence contains unknown tenancy ID: " + tid)
    movements = bank_overlap_dry_run(bank, account_key, previously_seen)
    inventory = evidence_inventory(folder)
    invalid = [i["name"] for i in inventory
               if i["exists"] and not i.get("valid_json_structure")]
    if invalid:
        raise ValueError("Invalid evidence JSON; do not migrate: " + ", ".join(invalid))
    opening_rows = []
    for tid, entry in opening_data["balances"].items():
        amount = entry.get("amount_cents")
        if not isinstance(amount, int):
            raise ValueError("Opening-balance cents missing or malformed for " + tid)
        opening_rows.append({
            "tenancy_id": tid, "as_of": entry.get("as_of"),
            "amount": str((Decimal(amount)/100).quantize(Decimal("0.01"))),
            "evidence": entry.get("evidence"), "actor": entry.get("actor"),
            "recorded_utc": entry.get("recorded_utc"),
            "state": "assumed_zero" if amount == 0 and "assum" in str(
                entry.get("evidence", "")).lower() else "requires_evidence_review",
        })
    summary = Counter(r["migration_status"] for r in movements)
    return {
        "schema": "gs_streamlit_v1",
        "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
        "source": "local Streamlit evidence",
        "tenancies": list(identities.values()),
        "opening_balances": opening_rows,
        "bank_movements": movements,
        "evidence_inventory": inventory,
        "summary": {
            "tenancies": len(identities),
            "opening_balance_entries": len(opening_rows),
            "bank_movements": len(movements),
            **dict(summary),
            "missing_evidence_files": [e["name"] for e in inventory if not e["exists"]],
        }
    }


def summary_only(plan):
    """Safe UI summary; no customer names, account numbers or descriptions."""
    return dict(plan["summary"])
