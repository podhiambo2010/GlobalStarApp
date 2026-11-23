"""Read-only dashboard grouping of bank receipts by their existing review outcome.

No writes, no re-matching, and no reference-based deduplication. Each bank
transaction is shown using its original Bank_Row_ID.
"""
from collections import OrderedDict

GROUPS = OrderedDict([
    ("Needs manual review", (
        "Review required", "Pending (reviewed)",
        "Legacy decision: reverify", "Stale tenancy assignment: reverify",
    )),
    ("Automatically identified — not approved", (
        "Identified (verify before notice)",
        "Identified (legacy override, verify tenancy)",
    )),
    ("Approved tenancy allocations", ("Assigned (reviewed)",)),
    ("Split deposits / advance rent", ("Split (reviewed)",)),
    ("Excluded transactions", ("Excluded (reviewed)", "Excluded (legacy)")),
])


def group_bank_credits(credits):
    """Return ordered views without changing or dropping any original rows.

    Raise rather than silently hide missing IDs, duplicate IDs or new statuses.
    """
    if not {"Bank_Row_ID", "Allocation_Status"}.issubset(credits.columns):
        raise ValueError("Bank review data is missing row identity or allocation status")
    if credits["Bank_Row_ID"].isna().any() or (
        credits["Bank_Row_ID"].astype(str).str.strip() == ""
    ).any():
        raise ValueError("Some bank credits have no stable bank-row identity")
    if credits["Bank_Row_ID"].astype(str).duplicated().any():
        raise ValueError("Duplicate Bank_Row_ID values require reconciliation before displaying")
    all_statuses = {status for labels in GROUPS.values() for status in labels}
    unknown = set(credits["Allocation_Status"].dropna().astype(str)) - all_statuses
    if credits["Allocation_Status"].isna().any() or unknown:
        raise ValueError(f"Unrecognised bank credit classification(s): {sorted(unknown)}")
    return OrderedDict(
        (label, credits.loc[credits["Allocation_Status"].isin(statuses)].copy())
        for label, statuses in GROUPS.items()
    )
