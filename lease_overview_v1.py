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


def expired_current_leases(overview, as_of=None):
    """Only current occupants whose *recorded original* term has expired.

    No alert for former occupants, vacancies, future occupants, or missing terms.
    A renewal flag alone does not establish a replacement expiry date.
    """
    now = pd.Timestamp(as_of if as_of is not None else pd.Timestamp.today()).normalize()
    required = {"Occupancy_Status", "Original_Term_End_Estimate"}
    if not required.issubset(overview.columns):
        raise ValueError("Lease overview has not been calculated")
    ends = pd.to_datetime(overview["Original_Term_End_Estimate"], errors="coerce")
    result = overview.loc[
        overview["Occupancy_Status"].eq("Current") & ends.lt(now)
    ].copy()
    result["Days_Past_Original_Term"] = (now - ends.loc[result.index]).dt.days
    return result.sort_values(["Original_Term_End_Estimate", "Shop #"], kind="stable")



def occupancy_audit(overview):
    """Count occupied physical units, and expose conflicts without guessing.

    A 'Current' tenancy record is not proof of a distinct occupied shop:
    repeated shop numbers, missing unit numbers and conflicting vacancy
    records must be investigated before finalizing an occupancy report.
    """
    if "Shop #" not in overview or "Occupancy_Status" not in overview:
        raise ValueError("Shop # and calculated occupancy status are required")
    data = overview.copy()
    status = data["Occupancy_Status"].fillna("").astype(str)
    current = status.eq("Current")
    data["_unit"] = data["Shop #"].apply(
        lambda value: str(value).strip().casefold()
        if pd.notna(value) and str(value).strip() else "")
    current_rows = data.loc[current]
    by_unit = current_rows.loc[current_rows["_unit"].ne("")].groupby("_unit", sort=False)
    occupied_units = set(by_unit.groups)
    duplicated_units = {unit for unit, group in by_unit if len(group) > 1}
    vacancy_units = set(data.loc[status.eq("Vacant") & data["_unit"].ne(""), "_unit"])
    conflicting_units = duplicated_units | (occupied_units & vacancy_units)
    missing_unit = current & data["_unit"].eq("")
    conflict_current = current & data["_unit"].isin(conflicting_units)
    issues = data.loc[missing_unit | conflict_current |
                      status.str.contains("Needs review|Unverified", case=False)].copy()
    if not issues.empty:
        def issue(row):
            if row["Occupancy_Status"] != "Current":
                return row["Occupancy_Status"]
            if not row["_unit"]:
                return "Current tenancy lacks identifiable shop/unit"
            if row["_unit"] in duplicated_units:
                return "Multiple current tenancy records for this unit"
            return "Unit appears both occupied and vacant"
        issues["Occupancy_Audit_Issue"] = issues.apply(issue, axis=1)
    return {
        "current_records": int(current.sum()),
        "unique_occupied_units": len(occupied_units),
        "uncontested_occupied_units": len(occupied_units - conflicting_units),
        "former_records": int(status.eq("Former").sum()),
        "vacant_units": len(vacancy_units - occupied_units),
        "conflicting_units": len(conflicting_units),
        "issues": issues.drop(columns=["_unit"]),
    }
