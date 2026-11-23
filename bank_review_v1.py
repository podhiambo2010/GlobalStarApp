"""Row-specific, Excel-only bank review decisions; legacy reference decisions remain read-only."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _norm(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _numeric(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def bank_row_ids(frame):
    """Stable content fingerprint; identical rows distinguished by occurrence.

    This is not a universal banking identifier: adding an identical earlier row
    can change occurrence ordinals. Such cases require manual verification.
    """
    seen = {}
    result = []
    for _, row in frame.iterrows():
        parts = [
            _norm(row.get("Transaction Date", "")),
            _norm(row.get("Value Date", "")),
            _norm(row.get("Ref_Clean", row.get("Bank Reference Number", ""))),
            _norm(row.get("Transaction Details", "")),
            _numeric(row.get("Money In Num", 0)),
            _numeric(row.get("Money Out Num", 0)),
        ]
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
        seen[digest] = seen.get(digest, 0) + 1
        result.append(f"{digest}:{seen[digest]}")
    return result


def load_review(path):
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Review store has an invalid format")
    return data


def write_review(path, entries):
    """Atomic local replacement; no database access."""
    import tempfile
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent), delete=False,
        prefix=".review-", suffix=".tmp"
    ) as temp:
        json.dump(entries, temp, indent=2, ensure_ascii=False)
        temp.flush()
        os.fsync(temp.fileno())
        temp_path = temp.name
    os.replace(temp_path, target)


def record_decision(entries, row_id, decision, tenancy_id=None, reason=""):
    if not row_id or not isinstance(row_id, str):
        raise ValueError("Select a specific bank row")
    if decision not in {"assign", "exclude", "pending", "restore"}:
        raise ValueError("Invalid review decision")
    if decision == "assign" and not tenancy_id:
        raise ValueError("Select an individual tenancy")
    if decision in {"exclude", "restore"} and not reason.strip():
        raise ValueError("Exclusions require a reason")
    updated = dict(entries)
    updated[row_id] = {
        "decision": decision,
        "tenancy_id": str(tenancy_id) if decision == "assign" else None,
        "reason": str(reason).strip(),
    }
    return updated


def apply_reviews(bank, register, entries, old_overrides=None, old_ignored=None):
    """Attach reviewed classifications without deleting original bank records.

    Legacy reference-based outcomes are shown, never silently assigned.
    """
    frame = bank.copy()
    if "Bank_Row_ID" not in frame.columns:
        frame["Bank_Row_ID"] = bank_row_ids(frame)
    frame["Review_Status"] = "Unreviewed"
    frame["Reviewed_Tenancy_ID"] = None
    frame["Legacy_Decision"] = ""
    old_overrides = old_overrides or {}
    old_ignored = old_ignored or {}
    valid = set(register["Tenancy_ID"].astype(str))
    # Reference-only legacy decisions may cover several bank transactions.
    ref_counts = frame["Ref_Clean"].astype(str).str.strip().value_counts()
    for idx, row in frame.iterrows():
        ref = str(row.get("Ref_Clean", "")).strip()
        if ref in old_overrides:
            frame.at[idx, "Legacy_Decision"] = f"Earlier shop override: {old_overrides[ref]}"
        if ref in old_ignored:
            frame.at[idx, "Legacy_Decision"] = (
                str(frame.at[idx, "Legacy_Decision"]) + " Earlier reference exclusion"
            ).strip()
        entry = entries.get(row["Bank_Row_ID"])
        if entry and entry.get("decision") == "restore":
            frame.at[idx, "Review_Status"] = "Unreviewed"
            continue
        if entry is None:
            if frame.at[idx, "Legacy_Decision"]:
                if ref in old_ignored and ref_counts.get(ref, 0) == 1:
                    frame.at[idx, "Review_Status"] = "Excluded (legacy)"
                elif ref in old_overrides and ref_counts.get(ref, 0) == 1:
                    frame.at[idx, "Review_Status"] = "Legacy shop mapping: verify tenancy"
                else:
                    frame.at[idx, "Review_Status"] = "Legacy decision: reverify"
            continue
        action = entry.get("decision")
        if action == "exclude":
            frame.at[idx, "Review_Status"] = "Excluded (reviewed)"
        elif action == "pending":
            frame.at[idx, "Review_Status"] = "Pending (reviewed)"
        elif action == "assign":
            tid = str(entry.get("tenancy_id") or "")
            if tid in valid:
                frame.at[idx, "Review_Status"] = "Assigned (reviewed)"
                frame.at[idx, "Reviewed_Tenancy_ID"] = tid
            else:
                frame.at[idx, "Review_Status"] = "Stale tenancy assignment: reverify"
    return frame


def append_review_event(path, *, bank_row_id, reference, action, reason, previous, actor):
    """Append-only audit events; atomically replace the history document."""
    history = load_event_history(path)
    history.append({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "bank_row_id": str(bank_row_id),
        "bank_reference": str(reference),
        "action": str(action),
        "previous_decision": str(previous),
        "reason": str(reason).strip(),
        "actor": str(actor).strip(),
    })
    write_event_history(path, history)


def write_event_history(path, events):
    import tempfile
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent), delete=False,
        prefix=".review-history-", suffix=".tmp",
    ) as temp:
        json.dump(events, temp, indent=2, ensure_ascii=False)
        temp.flush()
        os.fsync(temp.fileno())
        temp_path = temp.name
    os.replace(temp_path, target)


def load_event_history(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as handle:
        events = json.load(handle)
    if not isinstance(events, list):
        raise ValueError("Review history must be a JSON list")
    return events
