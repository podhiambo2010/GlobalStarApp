"""Read-only tenant payment allocation review for Excel-only GlobalStarApp V1.
Does not write, alter arrears, or promote suspected payments to rent.
"""
from io import BytesIO
import pandas as pd

def review_excluded_credits(full_bank, active_bank, tenants, overrides=None, ignored_refs=None):
    overrides = overrides or {}
    ignored_refs = ignored_refs or {}
    if full_bank is None or full_bank.empty:
        return pd.DataFrame(), {"excluded_credits": 0, "amount": 0.0}
    full = full_bank.copy()
    active = active_bank.copy() if active_bank is not None else pd.DataFrame()
    full["Money In Num"] = pd.to_numeric(full["Money In Num"], errors="coerce").fillna(0)
    excluded = full.loc[(full.get("Excluded_From_Legacy_Analysis", False) == True) & (full["Money In Num"] > 0)].copy()
    if excluded.empty:
        return pd.DataFrame(), {"excluded_credits": 0, "amount": 0.0}
    tenant_rows = []
    if tenants is not None and not tenants.empty and "Tenant Name" in tenants:
        for _, t in tenants.iterrows():
            name = str(t.get("Tenant Name", "")).strip()
            shop = t.get("Shop #", "")
            if name and name.lower() != "nan":
                tenant_rows.append((shop, name))
    active_keys = set()
    if not active.empty:
        for _, a in active.iterrows():
            active_keys.add((
                str(a.get("Transaction Date", "")).strip(),
                str(a.get("Ref_Clean", a.get("Bank Reference Number", ""))).strip(),
                round(float(pd.to_numeric(a.get("Money In Num", 0), errors="coerce") or 0), 2),
                str(a.get("Transaction Details", "")).strip(),
            ))
    def review_row(row):
        ref = str(row.get("Ref_Clean", row.get("Bank Reference Number", ""))).strip()
        desc = str(row.get("Transaction Details", "")).upper()
        amount = float(row["Money In Num"])
        source_key = (str(row.get("Transaction Date", "")).strip(), ref, round(amount, 2), str(row.get("Transaction Details", "")).strip())
        matched = [(shop, name) for shop, name in tenant_rows
                   if len(name) >= 5 and name.upper() in desc]
        # Short tenant names may be missed; do not infer positive matches from amounts.
        if len(matched) == 1:
            suggestion = f"Possible tenant: {matched[0][1]} (Unit {matched[0][0]})"
        elif len(matched) > 1:
            suggestion = "Multiple tenant-name matches — investigate"
        else:
            suggestion = "Unidentified credit — investigate"
        if ref in overrides:
            suggestion += f" | Saved override: Unit {overrides[ref]} (NOT VERIFIED)"
        if ref in ignored_refs:
            suggestion += " | Previously ignored by reference"
        if source_key in active_keys:
            risk = "Matching transaction also appears in legacy analysis; do not post twice"
        else:
            risk = "Excluded from legacy analysis; prior posting still unverified"
        return pd.Series({
            "Transaction ID (source row)": row.get("Original_Statement_Row", ""),
            "Transaction date": row.get("Transaction Date", ""),
            "Bank reference": ref,
            "Description (source)": row.get("Transaction Details", ""),
            "Money IN (KSh)": amount,
            "Suggested tenant / classification": suggestion,
            "Existing legacy row match": source_key in active_keys,
            "Review risk": risk,
            "Decision": "Needs evidence — no allocation",
            "Evidence required": "Tenant rent ledger, prior workbook allocations, payer confirmation and lease dates",
        })
    audit = excluded.apply(review_row, axis=1).reset_index(drop=True)
    return audit, {"excluded_credits": len(audit), "amount": float(audit["Money IN (KSh)"].sum())}

def export_allocation_review(audit, summary):
    with BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame([
                ("Report", "READ-ONLY / UNVERIFIED tenant allocation review"),
                ("Excluded money-IN records", summary["excluded_credits"]),
                ("Total credits pending verification", summary["amount"]),
                ("Posting", "NONE — no rent balance or source workbook changes"),
                ("Warning", "Bank reconciliation does not imply tenant allocation."),
                ("Duplicate protection", "Bank reference alone is not a unique transaction ID."),
            ], columns=["Control", "Value"]).to_excel(writer, sheet_name="Control Summary", index=False)
            audit.to_excel(writer, sheet_name="Review Required", index=False)
        return buf.getvalue()
