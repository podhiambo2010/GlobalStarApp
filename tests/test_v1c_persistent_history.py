import unittest
from datetime import date
from persistent_history_v1c import (
    BASELINE, statement_digest, fingerprint, plan_statement_import,
    opening_baseline, proposed_receipt_split
)


class PersistentHistoryTests(unittest.TestCase):
    def test_sha_repeatable(self):
        self.assertEqual(statement_digest(b"same"), statement_digest(b"same"))
        self.assertNotEqual(statement_digest(b"same"), statement_digest(b"different"))

    def test_overlapping_statement_deduplication(self):
        row = {"transaction_date": date(2025, 9, 21), "amount": "20000",
               "description": " M-Pesa   Rent ", "reference": "ABC"}
        plan = plan_statement_import("KCB-account", [row])
        self.assertEqual(len(plan["new"]), 1)
        other = dict(row, description="M-Pesa Rent")
        rerun = plan_statement_import("KCB-account", [other],
                                     {plan["new"][0]["fingerprint"]})
        self.assertEqual(len(rerun["already_seen"]), 1)
        self.assertEqual(len(rerun["new"]), 0)

    def test_identical_rows_in_single_file_need_review(self):
        row = {"transaction_date": date(2025, 10, 1), "amount": 1000,
               "description": "Counter deposit"}
        plan = plan_statement_import("KCB", [row, dict(row)])
        self.assertEqual(len(plan["ambiguous_same_statement"]), 2)
        self.assertEqual(len(plan["new"]), 0)

    def test_distinct_bank_ids_not_collapsed(self):
        base = {"transaction_date": date(2025, 10, 1), "amount": 1000,
                "description": "Counter deposit"}
        rows = [{**base, "unique_bank_id": "ID-1"},
                {**base, "unique_bank_id": "ID-2"}]
        self.assertEqual(len(plan_statement_import("KCB", rows)["new"]), 2)

    def test_baseline_does_not_modify_future_or_vacant(self):
        rows = [
            {"tenancy_id": "before", "start_date": date(2025, 8, 1), "status": "current"},
            {"tenancy_id": "future", "start_date": date(2025, 10, 1), "status": "current"},
            {"tenancy_id": "vacant", "start_date": date(2025, 7, 1), "status": "vacancy"},
        ]
        result = opening_baseline(rows)
        self.assertEqual([x["tenancy_id"] for x in result], ["before"])
        self.assertEqual(result[0]["baseline_date"], BASELINE.isoformat())
        self.assertEqual(result[0]["evidence_state"], "assumed_zero")

    def test_deposit_first_proposal_is_not_posted_rent(self):
        proposed = proposed_receipt_split(100000, 75000, "unit-10", True)
        self.assertEqual(proposed["deposit"], "75000.00")
        self.assertEqual(proposed["remainder"], "25000.00")
        self.assertEqual(proposed["status"], "proposed_only_verify_rent_period")
        manual = proposed_receipt_split(100000, 75000, None, False)
        self.assertIsNone(manual["deposit"])
        self.assertIsNone(manual["remainder"])


if __name__ == "__main__":
    unittest.main()
