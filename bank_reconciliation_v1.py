"""Read-only reconciliation for an Excel KCB statement.

Bank movements are never excluded from this audit due to account coding,
tenant assignment, duplicate references, or reporting exclusions.
"""
from io import BytesIO
import pandas as pd

def reconcile_bank_ledger(bank, tolerance=0.01):
    required = ("Transaction Date", "Ledger Balance", "Money In Num", "Money Out Num")
    if bank is None or bank.empty:
        return pd.DataFrame(), pd.DataFrame(), {"rows": 0, "exceptions": 0, "difference": 0.0}
    missing = [c for c in required if c not in bank.columns]
    if missing:
        raise ValueError("Missing bank columns: " + ", ".join(missing))
    df = bank.copy().reset_index(drop=True)
    def amount(column):
        return pd.to_numeric(df[column].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
    df["Money IN (KSh)"] = amount("Money In Num").abs()
    df["Money OUT (KSh)"] = amount("Money Out Num").abs()
    df["Statement balance (KSh)"] = amount("Ledger Balance")
    df["Source row"] = df.index + 1
    df["Expected balance (KSh)"] = pd.NA
    df["Balance variance (KSh)"] = pd.NA
    df["Review status"] = "OK"
    df["Explanation"] = ""
    previous = None
    for idx in df.index:
        balance = df.at[idx, "Statement balance (KSh)"]
        money_in = df.at[idx, "Money IN (KSh)"]
        money_out = df.at[idx, "Money OUT (KSh)"]
        if pd.isna(balance) or pd.isna(money_in) or pd.isna(money_out):
            df.at[idx, "Review status"] = "Invalid numeric data"
            df.at[idx, "Explanation"] = "Missing or non-numeric bank movement/balance; review source"
        elif previous is None:
            df.at[idx, "Review status"] = "Opening reference"
            df.at[idx, "Explanation"] = "First row establishes starting balance; prior period is not available"
        else:
            expected = round(float(previous + money_in - money_out), 2)
            variance = round(float(balance - expected), 2)
            df.at[idx, "Expected balance (KSh)"] = expected
            df.at[idx, "Balance variance (KSh)"] = variance
            if abs(variance) > tolerance:
                df.at[idx, "Review status"] = "Needs investigation"
                df.at[idx, "Explanation"] = (
                    "Consecutive balances do not reconcile to this recorded movement. "
                    "Check omitted/filtered source rows, parsing and bank statement order."
                )
        # Retain the actual statement balance as the baseline, so each
        # discontinuity is shown at its own row rather than propagated.
        previous = balance if pd.notna(balance) else None
    exceptions = df[df["Review status"].isin(["Needs investigation", "Invalid numeric data"])].copy()
    diffs = pd.to_numeric(exceptions["Balance variance (KSh)"], errors="coerce").fillna(0)
    summary = {
        "rows": len(df),
        "exceptions": len(exceptions),
        "difference": round(float(diffs.sum()), 2),
        "opening": float(df.iloc[0]["Statement balance (KSh)"]) if pd.notna(df.iloc[0]["Statement balance (KSh)"]) else None,
        "closing": float(df.iloc[-1]["Statement balance (KSh)"]) if pd.notna(df.iloc[-1]["Statement balance (KSh)"]) else None,
        "total_in": round(float(df["Money IN (KSh)"].sum()), 2),
        "total_out": round(float(df["Money OUT (KSh)"].sum()), 2),
        "excluded_from_legacy_analysis": int(df.get("Excluded_From_Legacy_Analysis", pd.Series(False,index=df.index)).fillna(False).sum()),
    }
    return df, exceptions, summary

def export_reconciliation(df, exceptions, summary):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([
            ("Status", "UNVERIFIED — READ-ONLY"),
            ("Source bank rows", summary["rows"]),
            ("Unreconciled rows", summary["exceptions"]),
            ("Aggregate differences (KSh)", summary["difference"]),
            ("Excluded from legacy tenant analysis (still retained in audit)", summary["excluded_from_legacy_analysis"]),
            ("Important", "A discrepancy is not proof of a missing transaction; verify against the original bank statement."),
            ("Duplicate references", "Identical bank references do not establish duplicate transactions."),
            ("Production posting", "No accounting or tenant entries were changed."),
        ],columns=["Measure","Value"]).to_excel(writer,sheet_name="Summary",index=False)
        exceptions.to_excel(writer,sheet_name="Exceptions",index=False)
        df.to_excel(writer,sheet_name="All Bank Rows",index=False)
    return output.getvalue()
