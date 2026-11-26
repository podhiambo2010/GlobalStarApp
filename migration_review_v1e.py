"""Stage 1E: non-destructive review of identical-looking bank movement rows.

A matching fingerprint is a REVIEW FLAG, not proof of duplication.
No bank receipt, assignment, exclusion or ledger is modified here.
"""
from collections import defaultdict


def ambiguous_bank_rows(plan):
    """Show every original row in each collision group, retaining source order."""
    if plan.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES":
        raise ValueError("Stage 1E requires an unmodified Stage 1D dry-run plan")
    groups = defaultdict(list)
    for position, row in enumerate(plan.get("bank_movements", []), 1):
        if row.get("migration_status") == "ambiguous_identical_rows":
            groups[str(row["fingerprint"])].append((position, row))
    review = []
    for group_number, (fp, entries) in enumerate(sorted(groups.items()), 1):
        # Preserve all collisions, including more than two matching bank rows.
        if len(entries) < 2:
            raise ValueError("Incomplete collision group; rerun Stage 1D")
        for position, row in entries:
            review.append({
                "collision_group": group_number,
                "group_size": len(entries),
                "source_row": position,
                "legacy_bank_row_id": row.get("legacy_bank_row_id", ""),
                "transaction_date": row["transaction_date"],
                "direction": row["direction"],
                "amount_ksh": row["amount"],
                "reference": row.get("reference", ""),
                "description": row.get("description", ""),
                "bank_unique_id": row.get("bank_unique_id"),
                "fingerprint": fp,
                "review_status": "UNRESOLVED — inspect original bank statement",
            })
    return review


def collision_summary(rows):
    return {
        "ambiguous_rows": len(rows),
        "collision_groups": len({r["collision_group"] for r in rows}),
        "ready_for_import": len(rows) == 0,
    }
