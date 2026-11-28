"""Full-source Section 03B regression tests (no database access or writes)."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import unittest

import pandas as pd

from bank_review_v1 import bank_row_ids
from migration_full_source_inspection_v1_section03b import inspect_full_source


class FullSourceInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bank = pd.DataFrame([
            {"Transaction Date": "2025-11-10", "Value Date": "2025-11-10",
             "Ref_Clean": "SAME", "Transaction Details": "Zero marker",
             "Money In Num": 0, "Money Out Num": 0},
            {"Transaction Date": "2025-11-11", "Value Date": "2025-11-11",
             "Ref_Clean": "SAME", "Transaction Details": "Posted credit",
             "Money In Num": 20000, "Money Out Num": 0},
        ])
        self.bank["Bank_Row_ID"] = bank_row_ids(self.bank)
        self.zero_id, self.credit_id = self.bank["Bank_Row_ID"].tolist()
        self.plan = {
            "schema": "gs_streamlit_v1", "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "bank_movements": [{"legacy_bank_row_id": self.credit_id}],
            "tenancies": [{"tenancy_id": "2:new", "unit_code": "2"}],
        }
        self.reviews = {self.zero_id: {"decision": "exclude", "reason": "test"},
                        self.credit_id: {"decision": "assign", "tenancy_id": "2:old"}}
        (self.root / "tenancy_bank_reviews_v1.json").write_text(json.dumps(self.reviews), encoding="utf-8")
        self.discrepancy = {
            "mode": "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES",
            "unmatched_review_details": [
                {"historical_bank_row_id": self.zero_id, "review_decision": "exclude",
                 "review_tenancy_id": ""}],
            "stale_tenancy_details": [
                {"bank_row_id": self.credit_id, "review_tenancy_id": "2:old"}],
            "review_register_sha256": hashlib.sha256((self.root / "tenancy_bank_reviews_v1.json").read_bytes()).hexdigest(),
        }

    def test_zero_row_identified_by_exact_id(self):
        result = inspect_full_source(self.plan, self.discrepancy, self.bank, self.root)
        self.assertEqual(result["unmatched_match_categories"]["exact_id_zero_amount_original_statement_row"], 1)
        self.assertEqual(result["zero_amount_original_rows"], 1)
        self.assertTrue(result["row_id_algorithm_consistent_with_source"])
        self.assertEqual(result["approved_imports"], 0)

    def test_shared_reference_does_not_authorize_automatching(self):
        result = inspect_full_source(self.plan, self.discrepancy, self.bank, self.root)
        self.assertFalse(result["unmatched_review_evidence"][0]["auto_remap_allowed"])
        self.assertEqual(result["stale_tenancy_evidence"][0]["same_unit_tenancy_ids_for_manual_investigation"], ["2:new"])
        self.assertFalse(result["stale_tenancy_evidence"][0]["auto_assignment_allowed"])

    def test_source_rows_and_review_unchanged(self):
        before = self.bank.copy(deep=True)
        original = (self.root / "tenancy_bank_reviews_v1.json").read_bytes()
        inspect_full_source(self.plan, self.discrepancy, self.bank, self.root)
        pd.testing.assert_frame_equal(self.bank, before)
        self.assertEqual((self.root / "tenancy_bank_reviews_v1.json").read_bytes(), original)

    def test_missing_exact_row_is_not_declared_resolved(self):
        self.discrepancy["unmatched_review_details"][0]["historical_bank_row_id"] = "unknown-id"
        self.reviews["unknown-id"] = self.reviews.pop(self.zero_id)
        (self.root / "tenancy_bank_reviews_v1.json").write_text(json.dumps(self.reviews), encoding="utf-8")
        self.discrepancy["review_register_sha256"] = hashlib.sha256((self.root / "tenancy_bank_reviews_v1.json").read_bytes()).hexdigest()
        result = inspect_full_source(self.plan, self.discrepancy, self.bank, self.root)
        self.assertEqual(result["unmatched_match_categories"]["not_in_current_full_statement_by_exact_row_id"], 1)

    def test_changed_review_blocks(self):
        self.reviews["new"] = {"decision": "pending"}
        (self.root / "tenancy_bank_reviews_v1.json").write_text(json.dumps(self.reviews), encoding="utf-8")
        with self.assertRaises(ValueError):
            inspect_full_source(self.plan, self.discrepancy, self.bank, self.root)


if __name__ == "__main__":
    unittest.main()
