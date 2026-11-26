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


def cheque_return_candidates(plan):
    """Find offsetting cheque credit/debit pairs without changing bank records.

    Same-day equal/opposite cheques are candidates only. A subsequent credit
    with matching cheque details is a possible re-bank, NOT proved by the
    earlier offset and never approved as rent here.
    """
    from collections import defaultdict
    from decimal import Decimal

    if plan.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES":
        raise ValueError("Cheque review requires a Stage 1D dry-run plan")

    groups = defaultdict(lambda: {"credit": [], "debit": []})
    rows = plan.get("bank_movements", [])
    for source_row, row in enumerate(rows, 1):
        amount = Decimal(str(row["amount"]))
        if amount == 0:
            continue
        direction = "credit" if amount > 0 else "debit"
        description = " ".join(str(row.get("description", "")).lower().split())
        if not any(x in description for x in ("chq", "cheque", "check")):
            continue
        # A reversal must share cheque evidence, not just amount/date.
        reference = str(row.get("reference", "")).strip().lower()
        import re
        cheque = re.search(r"\\b(?:chq|cheque|check)\\s*(?:no\\.?\\s*)?0*(\\d{3,})\\b",
                           description)
        if not cheque:
            continue
        key = (row["transaction_date"], abs(amount), reference,
               cheque.group(1))
        groups[key][direction].append((source_row, row))

    candidates = []
    for key, sides in sorted(groups.items(), key=lambda item: str(item[0])):
        # When there is more than one of either side, do not guess pairing.
        if len(sides["credit"]) != 1 or len(sides["debit"]) != 1:
            continue
        credit_pos, credit = sides["credit"][0]
        debit_pos, debit = sides["debit"][0]
        candidates.append({
            "cheque_number": key[3],
            "transaction_date": key[0],
            "amount_ksh": str(key[1]),
            "bank_reference": key[2],
            "credit_row_id": credit.get("legacy_bank_row_id", ""),
            "debit_row_id": debit.get("legacy_bank_row_id", ""),
            "credit_source_row": credit_pos,
            "debit_source_row": debit_pos,
            "net_amount_ksh": "0.00",
            "review_status": "PROPOSED_RETURN_PAIR — verify against bank",
        })
    return candidates
