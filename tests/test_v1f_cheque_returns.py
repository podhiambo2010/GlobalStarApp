import unittest
from migration_review_v1e import cheque_return_candidates


def row(id, amount, cheque, reference="REF"):
    return {
        "legacy_bank_row_id": id,
        "transaction_date": "2025-11-10",
        "amount": str(amount),
        "direction": "credit" if amount > 0 else "debit",
        "description": f"Chq Dep CHQ00{cheque} DREAMLINE",
        "reference": reference,
        "migration_status": "new_staging_candidate",
    }


class ChequeReturnTests(unittest.TestCase):
    def test_equal_opposite_cheque_is_candidate_not_deleted(self):
        plan = {
            "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "bank_movements": [row("a", 30000, 4680), row("b", -30000, 4680)]
        }
        before = repr(plan)
        candidates = cheque_return_candidates(plan)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["net_amount_ksh"], "0.00")
        self.assertEqual(candidates[0]["credit_row_id"], "a")
        self.assertEqual(candidates[0]["debit_row_id"], "b")
        self.assertEqual(repr(plan), before)

    def test_later_successful_rebank_credit_is_separate_candidate(self):
        later_mash = row("mash-rebank", 60000, 4525)
        later_mash["transaction_date"] = "2025-11-11"
        later_dream = row("dream-rebank", 30000, 4680)
        later_dream["transaction_date"] = "2025-11-11"
        plan = {"mode": "DRY_RUN_ONLY_NO_DB_WRITES",
                "bank_movements": [
                    row("dream-original", 30000, 4680),
                    row("mash-original", 60000, 4525),
                    row("mash-returned", -60000, 4525),
                    row("dream-returned", -30000, 4680),
                    later_mash, later_dream,
                ]}
        pairs = cheque_return_candidates(plan)
        self.assertEqual(len(pairs), 2)
        self.assertEqual({p["cheque_number"] for p in pairs}, {"4525", "4680"})
        self.assertTrue(all(len(p["later_credit_candidates"]) == 1 for p in pairs))
        self.assertEqual({p["later_credit_candidates"][0]["bank_row_id"]
                          for p in pairs}, {"dream-rebank", "mash-rebank"})

    def test_different_cheque_or_amount_is_not_assumed_reversal(self):
        plan = {"mode": "DRY_RUN_ONLY_NO_DB_WRITES",
                "bank_movements": [row("a", 30000, 4680), row("b", -30000, 4681),
                                   row("c", -20000, 4680)]}
        self.assertEqual(cheque_return_candidates(plan), [])

    def test_multiple_same_side_not_silently_paired(self):
        plan = {"mode": "DRY_RUN_ONLY_NO_DB_WRITES",
                "bank_movements": [row("a", 30000, 4680), row("b", 30000, 4680),
                                   row("c", -30000, 4680)]}
        self.assertEqual(cheque_return_candidates(plan), [])

    def test_non_dry_run_rejected(self):
        with self.assertRaises(ValueError):
            cheque_return_candidates({"mode": "LIVE"})


if __name__ == "__main__":
    unittest.main()
