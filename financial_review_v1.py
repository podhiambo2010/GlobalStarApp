"""Excel-only bank movement review. Not a tax computation or statutory P&L."""
from io import BytesIO
import pandas as pd

def financial_period(fy_end: int, period: str, subperiod: str = ""):
    """Company financial year ends 30 June; dates are inclusive."""
    start_year = int(fy_end) - 1
    annual_start = pd.Timestamp(start_year, 7, 1)
    annual_end = pd.Timestamp(int(fy_end), 6, 30)
    if period == "Annual":
        return annual_start, annual_end
    if period == "Bi-Annual":
        if subperiod == "H1":
            return annual_start, pd.Timestamp(start_year, 12, 31)
        if subperiod == "H2":
            return pd.Timestamp(int(fy_end), 1, 1), annual_end
    if period == "Quarterly":
        periods = {
            "Q1": (pd.Timestamp(start_year, 7, 1), pd.Timestamp(start_year, 9, 30)),
            "Q2": (pd.Timestamp(start_year, 10, 1), pd.Timestamp(start_year, 12, 31)),
            "Q3": (pd.Timestamp(int(fy_end), 1, 1), pd.Timestamp(int(fy_end), 3, 31)),
            "Q4": (pd.Timestamp(int(fy_end), 4, 1), annual_end),
        }
        if subperiod in periods:
            return periods[subperiod]
    raise ValueError("Unsupported reporting period selection")

def review_bank_movements(bank: pd.DataFrame, start, end):
    if bank is None or bank.empty:
        return pd.DataFrame(), {"complete": False, "reason": "No bank rows", "in": 0.0, "out": 0.0}
    df = bank.copy()
    df["Review_Date"] = pd.to_datetime(
        df["Transaction Date"].astype(str).str.strip(), format="%d.%m.%Y", errors="coerce"
    )
    for col in ("Money In Num", "Money Out Num"):
        if col not in df:
            raise ValueError(f"Missing required bank amount column: {col}")
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).abs()
    valid_dates = df["Review_Date"].dropna()
    coverage_start = valid_dates.min() if not valid_dates.empty else pd.NaT
    coverage_end = valid_dates.max() if not valid_dates.empty else pd.NaT
    complete = bool(pd.notna(coverage_start) and pd.notna(coverage_end)
                    and coverage_start <= start and coverage_end >= end)
    period_df = df.loc[df["Review_Date"].between(start, end, inclusive="both")].copy()
    nonmovement = (period_df["Money In Num"] == 0) & (period_df["Money Out Num"] == 0)
    summary = {
        "complete": complete,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "rows": len(period_df),
        "nonmovement": int(nonmovement.sum()),
        "in": float(period_df["Money In Num"].sum()),
        "out": float(period_df["Money Out Num"].sum()),
    }
    return period_df, summary

def excel_review_export(period_df, summary, start, end):
    """Evidence export without tax assertions; workbook kept in memory."""
    notes = [
        ("Report", "BANK MOVEMENTS — UNVERIFIED REVIEW ONLY"),
        ("Selected period", f"{start:%d %b %Y} to {end:%d %b %Y}"),
        ("Coverage complete", "Yes" if summary["complete"] else "NO — MISSING SOURCE PERIOD"),
        ("Total money in (all sources, NOT rental income)", summary["in"]),
        ("Total money out (all purposes, NOT deductible expenses)", summary["out"]),
        ("Unclassified transactions", summary["rows"]),
        ("Taxable profit", "NOT CALCULATED"),
        ("KRA tax payable", "NOT CALCULATED"),
        ("Review requirement", "Reconcile previous periods, credits, reversals, account transfers, loan principal versus interest, tenant receipts and accruals."),
    ]
    dest = BytesIO()
    with pd.ExcelWriter(dest, engine="openpyxl") as w:
        pd.DataFrame(notes, columns=["Field", "Value"]).to_excel(w, sheet_name="Read Me", index=False)
        period_df.to_excel(w, sheet_name="Bank Movements", index=False)
    return dest.getvalue()
