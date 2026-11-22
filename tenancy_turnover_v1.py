"""Excel-only tenancy ledger. No database writes or inferred move-out dates."""
import calendar
import re

import pandas as pd


def _date(value):
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    return pd.to_datetime(value, errors="coerce", dayfirst=False)


def _months_rent(start, end, rate):
    """Daily pro-rata of each intersected calendar month, inclusive of both dates."""
    if pd.isna(start) or pd.isna(end) or start > end or rate <= 0:
        return 0.0
    cursor = pd.Timestamp(start).replace(day=1)
    end = pd.Timestamp(end).normalize()
    total = 0.0
    while cursor <= end:
        days = calendar.monthrange(cursor.year, cursor.month)[1]
        last = cursor + pd.offsets.MonthEnd(0)
        a = max(pd.Timestamp(start).normalize(), cursor)
        b = min(end, last)
        if a <= b:
            total += float(rate) * ((b-a).days+1)/days
        cursor += pd.DateOffset(months=1)
    return round(total, 2)


def tenancy_register(df, period_start, period_end):
    """One row per workbook tenancy; occupancy and lease expiry are distinct."""
    df = df.copy()
    a, b = pd.Timestamp(period_start).normalize(), pd.Timestamp(period_end).normalize()
    if a > b:
        raise ValueError("Report start must not be later than report end")
    if "Tenancy Record Status" not in df.columns or "Lease End Date" not in df.columns:
        raise ValueError("Upload the tenancy-history workbook with status and lease end date columns")
    if "Shop #" not in df.columns:
        df["Shop #"] = df["Shop / Unit #"]
    df["Shop #"] = pd.to_numeric(df["Shop #"], errors="coerce")
    df["Lease_Date_Parsed"] = pd.to_datetime(df["Lease Date"], errors="coerce")
    df["End_Actual"] = pd.to_datetime(df["Lease End Date"], errors="coerce")
    df["Tenancy_Status"] = df["Tenancy Record Status"].fillna("").astype(str).str.strip().str.casefold()
    df["Rent_Rate"] = pd.to_numeric(df["Monthly Rate"], errors="coerce").fillna(0)
    df["Tenancy_ID"] = [
        f"{str(int(unit)) if pd.notna(unit) else 'UNKNOWN'}:{start.strftime('%Y%m%d') if pd.notna(start) else 'NO_START'}:{i}"
        for i, (unit, start) in enumerate(zip(df["Shop #"], df["Lease_Date_Parsed"]), start=2)
    ]
    valid = {"current", "former", "vacancy"}
    df["Review_Required"] = (~df["Tenancy_Status"].isin(valid)
        | (df["Tenancy_Status"] != "vacancy") & df["Lease_Date_Parsed"].isna()
        | (df["Tenancy_Status"] == "former") & df["End_Actual"].isna()
        | (df["Tenancy_Status"] == "current") & df["End_Actual"].notna())
    df["Report_Status"] = df["Tenancy_Status"].str.title()
    df.loc[(df["Tenancy_Status"] == "current") & (df["Lease_Date_Parsed"] > b), "Report_Status"] = "Future"
    df.loc[df["Review_Required"], "Report_Status"] = "Needs review"
    df["Period_Start"] = df["Lease_Date_Parsed"].apply(lambda x: max(x, a) if pd.notna(x) else pd.NaT)
    df["Period_End"] = df["End_Actual"].apply(lambda x: min(x, b) if pd.notna(x) else b)
    df["Expected_Rent"] = df.apply(
        lambda r: _months_rent(r["Period_Start"], r["Period_End"], r["Rent_Rate"])
        if r["Tenancy_Status"] != "vacancy" and not r["Review_Required"] else 0.0, axis=1)
    df["Actual_Collected"] = 0.0
    df["Pending_Allocation"] = 0.0
    df["Arrears_Balance"] = df["Expected_Rent"]
    df["Enforcement_Status"] = "Not verified: review payments and opening balances"
    df["Period_Difference"] = df["Expected_Rent"]
    # A former tenancy ending before the reporting period has no new rent accrual.
    return df


def _tx_date(value):
    if isinstance(value, str):
        raw = value.strip()
        if re.fullmatch(r"\d{2}[./]\d{2}[./]\d{4}", raw):
            return pd.to_datetime(raw.replace(".", "/"), format="%d/%m/%Y", errors="coerce")
    return pd.to_datetime(value, errors="coerce", dayfirst=True)


def classify_credits(bank, register, map_shop, period_start, period_end, reviews=None, old_overrides=None, old_ignored=None):
    """Conservative matching: unique tenant identity AND tenancy dates required.

    Neither a shop number nor a shared bank reference proves payer identity.
    Uncertain credits are never assigned to a tenant.
    """
    from bank_review_v1 import apply_reviews
    bank = apply_reviews(bank, register, reviews or {}, old_overrides, old_ignored)
    payments = bank[(bank["Money In Num"] > 0) & (bank["Valid_Credit"] == True)].copy()
    payments["Payment_Date_Parsed"] = payments["Transaction Date"].map(_tx_date)
    a, b = pd.Timestamp(period_start), pd.Timestamp(period_end)
    payments = payments[payments["Payment_Date_Parsed"].between(a, b)].copy()
    payments["Tenancy_ID"] = None
    payments["Allocation_Status"] = "Review required"
    for status, label in [
        ("Excluded (reviewed)", "Excluded (reviewed)"),
        ("Pending (reviewed)", "Pending (reviewed)"),
        ("Legacy decision: reverify", "Legacy decision: reverify"),
        ("Stale tenancy assignment: reverify", "Stale tenancy assignment: reverify"),
    ]:
        payments.loc[payments["Review_Status"] == status, "Allocation_Status"] = label
    for idx, p in payments.iterrows():
        if p["Review_Status"] == "Assigned (reviewed)":
            payments.at[idx, "Tenancy_ID"] = p["Reviewed_Tenancy_ID"]
            payments.at[idx, "Allocation_Status"] = "Assigned (reviewed)"
            continue
        if p["Review_Status"] != "Unreviewed":
            continue
        text = (" ".join(str(p.get(c, "")) for c in ["Transaction Details", "Customers Name"])).upper()
        date = p["Payment_Date_Parsed"]
        shop = map_shop(p.get("Transaction Details", ""), "", p.get("Customers Name", ""))
        candidates = register[
            (register["Shop #"] == shop)
            & (~register["Review_Required"])
            & (register["Tenancy_Status"] != "vacancy")
            & (register["Lease_Date_Parsed"] <= date)
            & (register["End_Actual"].isna() | (register["End_Actual"] >= date))
        ]
        if len(candidates) != 1:
            continue
        tenant = candidates.iloc[0]
        name = str(tenant["Tenant Name"]).upper()
        tokens = [t for t in re.findall(r"[A-Z]{5,}", name)
                  if t not in {"LIMITED", "HOLDINGS", "AFRICA", "KENYA", "ENTERPRISES", "COMPANY"}]
        # Matching a meaningful name token prevents one unit's successor from inheriting credits.
        if not tokens or not any(t in text for t in tokens):
            continue
        payments.at[idx, "Tenancy_ID"] = tenant["Tenancy_ID"]
        payments.at[idx, "Allocation_Status"] = "Identified (verify before notice)"
    sums = (payments[payments["Allocation_Status"] == "Assigned (reviewed)"]
            .dropna(subset=["Tenancy_ID"]).groupby("Tenancy_ID")["Money In Num"].sum())
    register = register.copy()
    register["Actual_Collected"] = register["Tenancy_ID"].map(sums).fillna(0)
    provisional = (payments[payments["Allocation_Status"] == "Identified (verify before notice)"]
                   .dropna(subset=["Tenancy_ID"]).groupby("Tenancy_ID")["Money In Num"].sum())
    register["Provisional_Credits"] = register["Tenancy_ID"].map(provisional).fillna(0)
    register["Period_Difference"] = register["Expected_Rent"] - register["Actual_Collected"]
    register["Arrears_Balance"] = register["Period_Difference"]
    # This is NOT lifetime arrears: pre-period opening balances and deposit movements
    # are not established by the statement and cannot be inferred safely.
    return register, payments
