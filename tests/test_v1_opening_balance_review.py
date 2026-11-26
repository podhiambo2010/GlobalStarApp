"""No-ledger-write regression checks for Stage 1B opening-balance evidence."""
import json
import os
import tempfile
import unittest
from datetime import date

import pandas as pd

from opening_balance_review_v1 import load_openings, record_opening, evidence_view


class OpeningBalanceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temporary.name, "openings.json")

    def tearDown(self):
        self.temporary.cleanup()

    def test_record_and_audit_revisions_without_duplicate(self):
        day = date(2025, 11, 24)
        self.assertTrue(record_opening(
            self.path, "10:20250701:aaa", day, 750, "Verified ledger entry ABC", "Reviewer"))
        self.assertFalse(record_opening(
            self.path, "10:20250701:aaa", day, 750, "Verified ledger entry ABC", "Reviewer"))
        self.assertTrue(record_opening(
            self.path, "10:20250701:aaa", day, -200, "Tenant credit statement ABC", "Reviewer"))
        data = load_openings(self.path)
        self.assertEqual(len(data["history"]), 2)
        self.assertEqual(data["history"][0]["action"], "opening_recorded")
        self.assertEqual(data["history"][1]["action"], "opening_revised")
        self.assertEqual(data["balances"]["10:20250701:aaa"]["amount_cents"], -20000)
        self.assertEqual(data["history"][1]["previous"]["amount_cents"], 75000)

    def test_missing_or_invalid_data_is_not_silently_reset(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("{broken")
        with self.assertRaises(json.JSONDecodeError):
            load_openings(self.path)
        with self.assertRaises(json.JSONDecodeError):
            record_opening(self.path, "unit-10", date(2025, 11, 24), 20, "Documented source", "Owner")

    def test_evidence_is_separate_from_period_rent_and_date_mismatch_flagged(self):
        record_opening(self.path, "10", date(2025, 9, 21), 750, "Ledger sheet Sept 2025", "Owner")
        original = pd.DataFrame([
            {"Tenancy_ID": "10", "Expected_Rent": 1000, "Actual_Collected": 100},
            {"Tenancy_ID": "13", "Expected_Rent": 2000, "Actual_Collected": 0},
        ])
        view = evidence_view(original, load_openings(self.path), date(2025, 11, 24))
        self.assertEqual(view.loc[0, "Opening_Balance_KSh"], 750)
        self.assertIn("Date differs", view.loc[0, "Opening_Status"])
        self.assertEqual(view.loc[1, "Opening_Status"], "Not supplied")
        self.assertTrue(pd.isna(view.loc[1, "Opening_Balance_KSh"]))
        self.assertEqual(view.loc[0, "Expected_Rent"], 1000)
        self.assertEqual(view.loc[0, "Actual_Collected"], 100)

    def test_require_evidence_and_valid_money(self):
        for value in [float("nan"), 1.234]:
            with self.assertRaises(ValueError):
                record_opening(self.path, "10", date(2025, 11, 24), value,
                               "Adequate source evidence", "Owner")
        with self.assertRaises(ValueError):
            record_opening(self.path, "10", date(2025, 11, 24), 0, "", "Owner")


if __name__ == "__main__":
    unittest.main()
