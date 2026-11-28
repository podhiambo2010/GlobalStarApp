"""Section 03D: historical audits with human-readable bank particulars, read only."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from historical_review_human_evidence_v1 import build_human_review_sheet


class HistoricalHumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reviews = {
            "old-row": {"decision": "assign", "tenancy_id": "1:prior"},
            "excluded-old-row": {"decision": "exclude", "reason": "Non-rent"},
        }
        (self.root / "tenancy_bank_reviews_v1.json").write_text(
            json.dumps(self.reviews), encoding="utf-8"
        )
        history = [
            {"bank_row_id": "old-row", "bank_reference": "FT-SHARED",
             "action": "assign", "reason": "tenant mentioned",
             "timestamp_utc": "2026-11-26T11:00:00Z"},
            {"bank_row_id": "excluded-old-row", "bank_reference": "FT-ABSENT",
             "action": "exclude", "reason": "Non-rent",
             "timestamp_utc": "2026-11-26T12:00:00Z"},
        ]
        (self.root / "tenancy_bank_review_history_v1.json").write_text(
            json.dumps(history), encoding="utf-8"
        )
        self.discrepancy = {
            "mode": "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES",
            "review_register_sha256": hashlib.sha256(
                (self.root / "tenancy_bank_reviews_v1.json").read_bytes()
            ).hexdigest(),
            "unmatched_review_details": [
                {"historical_bank_row_id": "old-row", "review_decision": "assign",
                 "review_tenancy_id": "1:prior"},
                {"historical_bank_row_id": "excluded-old-row", "review_decision": "exclude",
                 "review_tenancy_id": ""},
            ],
        }
        self.bank = pd.DataFrame([
            {"Bank_Row_ID": "current-1", "Transaction Date": "2025-11-10",
             "Value Date": "2025-11-11", "Money In Num": 20000,
             "Money Out Num": 0, "Ref_Clean": "FT-SHARED",
             "Transaction Details": "Payment from tenant with abbreviated particulars"},
            {"Bank_Row_ID": "current-2", "Transaction Date": "2025-11-12",
             "Value Date": "2025-11-13", "Money In Num": 5000,
             "Money Out Num": 0, "Ref_Clean": "FT-SHARED",
             "Transaction Details": "Another payment sharing bank reference"},
        ])

    def test_human_details_for_multiple_same_reference_rows(self):
        result = build_human_review_sheet(self.discrepancy, self.bank, self.root)
        self.assertEqual(result["historical_cases"], 2)
        self.assertEqual(result["cases"][0]["current_statement_reference_candidates"], 2)
        self.assertEqual(result["cases"][0]["bank_references_from_audit"], "FT-SHARED")
        self.assertIn("Payment from tenant", result["reference_candidates"][0]["full_particulars"])
        self.assertFalse(result["cases"][0]["original_transaction_date_proven"])
        self.assertEqual(result["rent_postings"], 0)

    def test_no_current_reference_match_is_clear(self):
        result = build_human_review_sheet(self.discrepancy, self.bank, self.root)
        self.assertEqual(result["cases"][1]["status"], "no_same_reference_in_current_statement")

    def test_evidence_and_source_unchanged(self):
        before = self.bank.copy(deep=True)
        originals = [(self.root / n).read_bytes() for n in
                     ("tenancy_bank_reviews_v1.json", "tenancy_bank_review_history_v1.json")]
        build_human_review_sheet(self.discrepancy, self.bank, self.root)
        pd.testing.assert_frame_equal(self.bank, before)
        self.assertEqual(originals, [(self.root / n).read_bytes() for n in
                                    ("tenancy_bank_reviews_v1.json", "tenancy_bank_review_history_v1.json")])

    def test_modified_decisions_block(self):
        self.reviews["another"] = {"decision": "pending"}
        (self.root / "tenancy_bank_reviews_v1.json").write_text(
            json.dumps(self.reviews), encoding="utf-8")
        with self.assertRaises(ValueError):
            build_human_review_sheet(self.discrepancy, self.bank, self.root)


if __name__ == "__main__":
    unittest.main()
