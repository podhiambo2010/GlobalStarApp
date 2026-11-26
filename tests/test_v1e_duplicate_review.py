import unittest

from migration_review_v1e import ambiguous_bank_rows, collision_summary


class DuplicateReviewTests(unittest.TestCase):
    def test_identical_rows_remain_separate_and_unresolved(self):
        base = {
            "legacy_bank_row_id": "different",
            "fingerprint": "same-fingerprint",
            "transaction_date": "2025-11-25",
            "direction": "credit",
            "amount": "20000.00",
            "reference": "SHARED",
            "description": "Two separate bank credits",
            "migration_status": "ambiguous_identical_rows",
        }
        plan = {
            "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "bank_movements": [
                dict(base, legacy_bank_row_id="row-a"),
                dict(base, legacy_bank_row_id="row-b"),
                dict(base, legacy_bank_row_id="row-c",
                     fingerprint="other", migration_status="new_staging_candidate"),
            ],
        }
        rows = ambiguous_bank_rows(plan)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["legacy_bank_row_id"] for r in rows], ["row-a", "row-b"])
        self.assertEqual(collision_summary(rows)["collision_groups"], 1)
        self.assertFalse(collision_summary(rows)["ready_for_import"])
        self.assertTrue(all("UNRESOLVED" in r["review_status"] for r in rows))
        self.assertEqual(plan["bank_movements"][0]["legacy_bank_row_id"], "row-a")

    def test_unpaired_ambiguous_marker_is_rejected(self):
        plan = {"mode": "DRY_RUN_ONLY_NO_DB_WRITES", "bank_movements": [{
            "fingerprint": "x", "migration_status": "ambiguous_identical_rows",
        }]}
        with self.assertRaisesRegex(ValueError, "Incomplete collision"):
            ambiguous_bank_rows(plan)

    def test_requires_dryrun_plan(self):
        with self.assertRaisesRegex(ValueError, "dry-run"):
            ambiguous_bank_rows({"mode": "PRODUCTION"})


if __name__ == "__main__":
    unittest.main()
