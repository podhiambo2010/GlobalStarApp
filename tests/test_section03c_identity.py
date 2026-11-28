"""Section 03C evidence recovery tests: preserved historical reviews, zero writes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import unittest

import pandas as pd

from bank_review_v1 import bank_row_ids
from migration_identity_recovery_v1_section03c import inspect_historical_identity


class HistoricalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.frame = pd.DataFrame([
            {"Transaction Date": "2025-11-10", "Value Date": "2025-11-10",
             "Ref_Clean": "ABC", "Transaction Details": "Prior payment",
             "Money In Num": 20000, "Money Out Num": 0}
        ])
        self.rowid = bank_row_ids(self.frame)[0]
        self.reviews = {self.rowid: {"decision": "assign", "tenancy_id": "unit1-old"}}
        self._write("tenancy_bank_reviews_v1.json", self.reviews)
        self._write("tenancy_bank_review_history_v1.json", [
            {"bank_row_id": self.rowid, "action": "assign", "bank_reference": "ABC"}
        ])
        self.discrepancy = {
            "mode": "SECTION_03B_DIAGNOSTIC_ONLY_NO_WRITES",
            "review_register_sha256": self._sha("tenancy_bank_reviews_v1.json"),
            "unmatched_historical_reviews": 1,
            "unmatched_review_details": [{"historical_bank_row_id": self.rowid,
               "review_decision": "assign", "review_tenancy_id": "unit1-old"}],
        }
        self.full_source = {
            "mode": "SECTION_03B_FULL_SOURCE_DIAGNOSTIC_NO_WRITES",
            "unmatched_review_evidence": [{"historical_bank_row_id": self.rowid,
               "review_decision": "assign", "review_tenancy_id": "unit1-old"}],
            "stale_tenancy_evidence": [],
        }

    def _write(self, name, obj):
        (self.root / name).write_text(json.dumps(obj), encoding="utf-8")

    def _sha(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def test_audit_only_reports_event_without_claiming_match(self):
        report = inspect_historical_identity(self.discrepancy, self.full_source, self.root)
        self.assertEqual(report["historical_audit_events_total"], 1)
        self.assertEqual(report["evidence_categories"], {
            "audit_history_found_bank_row_not_in_supplied_statements": 1})
        self.assertIsNone(report["review_records"][0]["exact_row_id_in_historical_statement"])
        self.assertFalse(report["review_records"][0]["automatically_reassigned"])

    def test_exact_row_id_in_archived_source(self):
        report = inspect_historical_identity(self.discrepancy, self.full_source,
                                             self.root, self.frame)
        self.assertEqual(report["evidence_categories"], {
            "exact_bank_row_id_found_in_historical_statement": 1})
        self.assertEqual(report["approved_rent_postings"], 0)
        self.assertFalse(report["supabase_writes"])

    def test_only_reference_overlap_does_not_match(self):
        other = self.frame.copy(deep=True)
        other["Transaction Details"] = "Different bank row SAME REFERENCE"
        report = inspect_historical_identity(self.discrepancy, self.full_source,
                                             self.root, other)
        self.assertEqual(report["evidence_categories"], {
            "audit_history_found_bank_row_not_in_supplied_statements": 1})
        self.assertFalse(report["review_records"][0]["exact_row_id_in_historical_statement"])

    def test_review_and_history_not_modified(self):
        before = {n: (self.root / n).read_bytes() for n in
                  ("tenancy_bank_reviews_v1.json", "tenancy_bank_review_history_v1.json")}
        inspect_historical_identity(self.discrepancy, self.full_source, self.root, self.frame)
        self.assertEqual(before, {n: (self.root / n).read_bytes() for n in before})

    def test_changed_review_blocks(self):
        self._write("tenancy_bank_reviews_v1.json", {})
        with self.assertRaises(ValueError):
            inspect_historical_identity(self.discrepancy, self.full_source, self.root)

    def test_inconsistent_discrepancy_blocks(self):
        self.discrepancy["unmatched_historical_reviews"] = 2
        with self.assertRaises(ValueError):
            inspect_historical_identity(self.discrepancy, self.full_source, self.root)

    def test_missing_history_does_not_erase_reviews(self):
        (self.root / "tenancy_bank_review_history_v1.json").unlink()
        report = inspect_historical_identity(self.discrepancy, self.full_source, self.root)
        self.assertFalse(report["historical_review_audit_file_present"])
        self.assertEqual(report["original_unmatched_reviews"], 1)


if __name__ == "__main__":
    unittest.main()
