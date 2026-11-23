"""Pinned Excel-only bank baseline; never claim missing bank statements are covered."""
import json
from datetime import date, datetime
from pathlib import Path
from bank_review_v1 import write_review

DEFAULT_BASELINE = date(2025, 9, 21)

def load_baseline(path):
    target = Path(path)
    if not target.exists():
        return DEFAULT_BASELINE
    with target.open(encoding="utf-8") as handle:
        saved = json.load(handle)
    if not isinstance(saved, dict) or not isinstance(saved.get("baseline_date"), str):
        raise ValueError("Invalid pinned reporting-start configuration")
    return date.fromisoformat(saved["baseline_date"])

def save_baseline(path, baseline):
    if isinstance(baseline, datetime):
        baseline = baseline.date()
    if not isinstance(baseline, date):
        raise ValueError("Choose a valid reporting start date")
    write_review(path, {"baseline_date": baseline.isoformat()})

def coverage_message(baseline, statement_start, statement_end):
    if isinstance(statement_start, datetime):
        statement_start = statement_start.date()
    if isinstance(statement_end, datetime):
        statement_end = statement_end.date()
    if baseline > statement_end:
        return "outside", "Pinned baseline is after the uploaded bank statement; no cumulative reporting is possible."
    if baseline < statement_start:
        return "gap", ("The uploaded statement starts after the pinned baseline. "
            "Earlier transactions are not loaded; do not interpret its totals as cumulative.")
    return "covered", ("Uploaded statement covers the pinned baseline through its ending date. "
        "This does not verify accounting balances or continuity with any older upload.")
