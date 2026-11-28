"""Section 03B: historical review investigation never mutates financial evidence."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from migration_discrepancies_v1_section03b import investigate_discrepancies


class Section03BTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = {
            "schema": "gs_streamlit_v1",
            "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "tenancies": [{"tenancy_id": "t1"}],
            "bank_movements": [
                {"legacy_bank_row_id": "r1", "reference": "SHARED"},
                {"legacy_bank_row_id": "r2", "reference": "SHARED"},
            ],
        }
        self.reviews = {
            "r1": {"decision": "assign", "tenancy_id": "t1"},
            "r2": {"decision": "assign", "tenancy_id": "missing-tenant"},
            "orphan": {"decision": "exclude", "reason": "prior review"},
        }
        self._write("tenancy_bank_reviews_v1.json", self.reviews)
        self._write("cheque_clearance_reviews_v1h.json", {"schema_version": 1, "history": []})
        self._write("cheque_allocations_v1i.json", {"schema_version": 1, "history": []})
        self.classification = {
            "mode": "SECTION_03A_EVIDENCE_CLASSIFICATION_ONLY_NO_WRITES",
            "schema": "gs_streamlit_v1",
            "total_original_bank_rows": 2,
            "classified_rows": 2,
            "matched_review_decisions": 2,
            "orphan_review_decisions": 1,
            "historical_file_warnings": ["reassignments.json"],
            "review_register_sha256": self._sha("tenancy_bank_reviews_v1.json"),
            "cheque_clearance_sha256": self._sha("cheque_clearance_reviews_v1h.json"),
            "cheque_allocation_sha256": self._sha("cheque_allocations_v1i.json"),
        }

    def _write(self, name, obj):
        (self.root / name).write_text(json.dumps(obj), encoding="utf-8")

    def _sha(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def test_orphan_and_stale_tenancy_identified_separately(self):
        report = investigate_discrepancies(self.plan, self.classification, self.root)
        self.assertEqual(report["unmatched_historical_reviews"], 1)
        self.assertEqual(report["stale_tenancy_assignments_in_current_bank_rows"], 1)
        self.assertEqual(report["unmatched_decisions_by_type"], {"exclude": 1})
        self.assertEqual(report["approved_imports"], 0)
        self.assertFalse(report["evidence_written"])

    def test_shared_bank_reference_does_not_auto_match(self):
        report = investigate_discrepancies(self.plan, self.classification, self.root)
        self.assertEqual(report["matched_review_count"], 2)
        self.assertEqual(report["unmatched_review_details"][0]["historical_bank_row_id"], "orphan")

    def test_financial_sources_byte_identical_after_report(self):
        files = ["tenancy_bank_reviews_v1.json", "cheque_clearance_reviews_v1h.json", "cheque_allocations_v1i.json"]
        before = {f: (self.root / f).read_bytes() for f in files}
        investigate_discrepancies(self.plan, self.classification, self.root)
        self.assertEqual(before, {f: (self.root / f).read_bytes() for f in files})

    def test_modified_review_file_blocks_stale_report(self):
        self._write("tenancy_bank_reviews_v1.json", {})
        with self.assertRaises(ValueError):
            investigate_discrepancies(self.plan, self.classification, self.root)

    def test_changed_cheque_evidence_blocks(self):
        self._write("cheque_allocations_v1i.json", {"schema_version": 1, "history": [{"foo": 1}]})
        with self.assertRaises(ValueError):
            investigate_discrepancies(self.plan, self.classification, self.root)

    def test_wrong_schema_blocks(self):
        with self.assertRaises(ValueError):
            investigate_discrepancies({**self.plan, "schema": "public"}, self.classification, self.root)

    def test_duplicate_original_row_id_blocks(self):
        self.plan["bank_movements"][1]["legacy_bank_row_id"] = "r1"
        with self.assertRaises(ValueError):
            investigate_discrepancies(self.plan, self.classification, self.root)


if __name__ == "__main__":
    unittest.main()
