"""Audited, locally stored opening-balance evidence for Stage 1B.

Opening balances are NOT inferred from bank descriptions or rent differences.
Values are never posted to invoices, notices, or the tenancy workbook.
"""
import json
import os
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

SCHEMA = 1


def load_openings(path):
    if not os.path.exists(path):
        return {"schema": SCHEMA, "balances": {}, "history": []}
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA
            or not isinstance(data.get("balances"), dict)
            or not isinstance(data.get("history"), list)):
        raise ValueError("Opening-balance file has an unknown schema; restore a verified backup.")
    return data


def record_opening(path, tenancy_id, as_of, signed_amount, evidence, actor="Local reviewer"):
    """Positive amount = debit due; negative = tenant credit. Append-only audit."""
    if not tenancy_id or not str(tenancy_id).strip():
        raise ValueError("Exact tenancy ID is required")
    if not isinstance(as_of, date):
        raise ValueError("Opening date is required")
    if not str(evidence).strip() or len(str(evidence).strip()) < 10:
        raise ValueError("Provide at least 10 characters describing source evidence")
    try:
        amount = Decimal(str(signed_amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Opening amount must be numeric") from exc
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        raise ValueError("Opening amount must have at most two decimal places")
    cents = int(amount * 100)
    data = load_openings(path)
    key = str(tenancy_id)
    previous = data["balances"].get(key)
    updated = {
        "tenancy_id": key, "as_of": as_of.isoformat(),
        "amount_cents": cents, "evidence": str(evidence).strip(),
        "actor": str(actor), "recorded_utc": datetime.now(timezone.utc).isoformat()
    }
    if previous and all(previous.get(k) == updated[k] for k in
                        ("as_of", "amount_cents", "evidence")):
        return False
    data["balances"][key] = updated
    data["history"].append({
        "action": "opening_verified" if previous is None else "opening_revised",
        "previous": previous, "new": updated,
    })
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".opening_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def evidence_view(register, data, reporting_start):
    """Join exact tenancy IDs; flag dates rather than adding incompatible figures."""
    from pandas import DataFrame, to_datetime, to_numeric
    frame = register.copy()
    balance = data.get("balances", {})
    frame["Opening_Balance_KSh"] = frame["Tenancy_ID"].map(
        lambda x: balance.get(str(x), {}).get("amount_cents"))
    frame["Opening_Balance_KSh"] = to_numeric(frame["Opening_Balance_KSh"], errors="coerce") / 100
    frame["Opening_As_Of"] = frame["Tenancy_ID"].map(
        lambda x: balance.get(str(x), {}).get("as_of"))
    frame["Opening_Evidence"] = frame["Tenancy_ID"].map(
        lambda x: balance.get(str(x), {}).get("evidence"))
    frame["Opening_Status"] = frame.apply(
        lambda r: "Not supplied" if r["Tenancy_ID"] not in balance
        else ("Date differs from statement start — not applied"
              if r["Opening_As_Of"] != reporting_start.isoformat()
              else "Evidence recorded — balance requires reconciliation"),
        axis=1
    )
    return frame
