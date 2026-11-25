"""Owner-attested security-deposit tracking, separate from bank receipt allocations.

This file records evidence status; it never creates or reallocates bank receipts.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

UNIT_LABELS = {10: "Mowlem Holdings — Unit 10", 13: "Mowlem Holdings — Unit 13"}
EXPECTED = {10: 75000.0, 13: 60000.0}
DEFAULT_RECORDS = {
    "10": {"unit": 10, "expected": 75000.0, "owner_reported_paid": 75000.0,
           "status": "Owner-confirmed paid; bank evidence pending",
           "evidence": "Owner confirmation, 2026-11-25. Historic bank statement may not cover deposit date."},
    "13": {"unit": 13, "expected": 60000.0, "owner_reported_paid": 0.0,
           "status": "Owner-confirmed unpaid",
           "evidence": "Owner confirmation, 2026-11-25. No payment reported."},
}

def _validate_record(unit, record):
    unit = int(unit)
    if unit not in EXPECTED:
        raise ValueError("Only Mowlem Units 10 and 13 are in this controlled review.")
    expected = EXPECTED[unit]
    paid = float(record["owner_reported_paid"])
    if not (0 <= paid <= expected):
        raise ValueError("Owner-reported deposit received must be between zero and the contractual deposit.")
    allowed = {"Owner-confirmed paid; bank evidence pending", "Owner-confirmed unpaid",
               "Part-paid; bank evidence pending", "Bank-verified"}
    if record["status"] not in allowed:
        raise ValueError("Invalid deposit review status")
    if record["status"] == "Bank-verified" and not str(record.get("evidence", "")).strip():
        raise ValueError("Bank verification requires an evidence reference.")
    if record["status"] == "Owner-confirmed unpaid" and paid:
        raise ValueError("Unpaid status cannot have a positive received amount.")
    return {"unit": unit, "expected": expected, "owner_reported_paid": round(paid, 2),
            "status": record["status"], "evidence": str(record.get("evidence", "")).strip()}

def load_records(path):
    path = Path(path)
    if not path.exists():
        return {"records": {k: dict(v) for k, v in DEFAULT_RECORDS.items()}, "history": []}
    with path.open("r", encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), dict) or not isinstance(doc.get("history"), list):
        raise ValueError("Deposit review file is invalid; restore its backup before making changes.")
    for k in ("10", "13"):
        if k not in doc["records"]:
            raise ValueError("Deposit review file is missing a Mowlem unit; do not reset its history.")
        _validate_record(int(k), doc["records"][k])
    return doc

def update_record(path, unit, paid, status, evidence, actor="Owner"):
    path = Path(path)
    unit = int(unit)
    new_record = _validate_record(unit, {"owner_reported_paid": paid, "status": status, "evidence": evidence})
    doc = load_records(path)
    old = doc["records"][str(unit)]
    if old == new_record:
        return False
    doc["records"][str(unit)] = new_record
    doc["history"].append({"at_utc": datetime.now(timezone.utc).isoformat(), "unit": unit,
                           "actor": actor, "previous": old, "new": new_record})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return True

def overview_rows(doc):
    result = []
    for unit in (10, 13):
        rec = _validate_record(unit, doc["records"][str(unit)])
        paid = rec["owner_reported_paid"]
        result.append({"Unit": unit, "Tenant": "Mowlem Holdings",
                       "Contractual deposit (KSh)": rec["expected"],
                       "Owner-reported received (KSh)": paid,
                       "Owner-reported unpaid (KSh)": round(rec["expected"] - paid, 2),
                       "Evidence status": rec["status"],
                       "Evidence / note": rec["evidence"]})
    return result
