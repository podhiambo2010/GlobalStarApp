"""Lease overview: occupancy is governed by tenancy history, not original term expiry.

Calculated contractual dates are advisory. A renewed flag without a documented
new commencement/end does not prove that a new contract exists.
"""
import pandas as pd


def _stamp(value):
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    return pd.to_datetime(value, errors="coerce")


def _duration_column(frame):
    """Only explicit duration fields, not dates or free-text monthly rate."""
    normalized = {str(c).strip().casefold(): c for c in frame.columns}
    for label in ("lease status (months)", "lease period (months)",
                  "lease duration (months)", "lease term (months)",
                  "lease status months", "lease period", "lease duration",
                  "lease term"):
        if label in normalized:
            return normalized[label]
    return None


def build_lease_overview(frame, as_of=None):
    """Create read-only, tenancy-aware legal and occupancy review columns."""
    out = frame.copy()
    now = pd.Timestamp(as_of if as_of is not None else pd.Timestamp.today()).normalize()
    dates = out["Lease_Date_Parsed"] if "Lease_Date_Parsed" in out else out.get("Lease Date")
    if dates is None:
        raise ValueError("Lease overview requires Lease Date")
    out["Lease_Date_Parsed"] = pd.to_datetime(dates, errors="coerce")
    status_col = "Tenancy Record Status"
    has_history = status_col in out and "Lease End Date" in out
    if has_history:
        occupancy = out[status_col].fillna("").astype(str).str.strip().str.casefold()
        departure = pd.to_datetime(out["Lease End Date"], errors="coerce")
    else:
        occupancy = pd.Series(["unknown"] * len(out), index=out.index)
        departure = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")

    duration_col = _duration_column(out)
    duration = (
        pd.to_numeric(out[duration_col], errors="coerce")
        if duration_col else pd.Series(float("nan"), index=out.index)
    )
    renewed_col = next((c for c in out if str(c).strip().casefold() == "lease renewed (yes/no)"), None)
    renewed = (
        out[renewed_col].fillna("").astype(str).str.strip().str.casefold()
        if renewed_col else pd.Series([""] * len(out), index=out.index)
    )

    ends, occupants, contract_statuses, notes = [], [], [], []
    for idx in out.index:
        start = out.at[idx, "Lease_Date_Parsed"]
        number = duration.loc[idx]
        original_end = pd.NaT
        if pd.notna(start) and pd.notna(number) and 0 < number <= 600 and float(number).is_integer():
            original_end = start + pd.DateOffset(months=int(number))
        ends.append(original_end)
        state = occupancy.loc[idx]
        left = departure.loc[idx]
        if not has_history:
            occupancy_label = "Unverified — history workbook required"
        elif state == "vacancy":
            occupancy_label = "Vacant"
        elif state == "former":
            occupancy_label = "Former" if pd.notna(left) else "Former — departure date missing"
        elif state == "current":
            if pd.notna(left):
                occupancy_label = "Needs review — current with departure date"
            elif pd.isna(start):
                occupancy_label = "Needs review — commencement missing"
            elif start > now:
                occupancy_label = "Future tenancy"
            else:
                occupancy_label = "Current"
        else:
            occupancy_label = "Needs review — unknown status"
        occupants.append(occupancy_label)

        if pd.isna(start):
            contract = "Start date missing — verify"
        elif renewed.loc[idx] == "yes":
            contract = "Renewal recorded — verify agreement/dates"
        elif pd.isna(original_end):
            contract = "Contract term missing — verify"
        elif original_end < now:
            contract = "Original term expired — verify renewal"
        elif original_end <= now + pd.Timedelta(days=60):
            contract = "Term ending soon — review"
        else:
            contract = "Within recorded original term"
        contract_statuses.append(contract)
        note = []
        if state == "former" and pd.isna(left):
            note.append("Enter actual departure date")
        if state == "current" and pd.notna(left):
            note.append("Current record conflicts with departure date")
        if state == "current" and pd.notna(original_end) and original_end < now:
            note.append("Current occupancy remains current; confirm renewal or holding-over terms")
        if state == "vacancy" and pd.notna(start):
            note.append("Vacant unit: confirm historical tenancy row is not reused")
        notes.append("; ".join(note))

    out["Original_Term_End_Estimate"] = ends
    out["Occupancy_Status"] = occupants
    out["Contract_Review_Status"] = contract_statuses
    out["Lease_Review_Note"] = notes
    out["Recorded_Departure_Date"] = departure
    out["Renewal_Recorded"] = renewed
    return out
