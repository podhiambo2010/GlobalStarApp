"""Section 03A: classification by original bank row identity, never by reference."""
import json
from pathlib import Path
import tempfile
import unittest

from migration_classification_v1_section03a import classify_evidence


class Section03AClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = {
            "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "schema": "gs_streamlit_v1",
            "tenancies": [{"tenancy_id": "tenant-1"}],
            "bank_movements": [
                {"legacy_bank_row_id": "r1", "fingerprint": "a", "direction": "credit", "reference": "SAME"},
                {"legacy_bank_row_id": "r2", "fingerprint": "b", "direction": "debit", "reference": "SAME"},
                {"legacy_bank_row_id": "r3", "fingerprint": "c", "direction": "credit", "reference": "SAME"},
                {"legacy_bank_row_id": "r4", "fingerprint": "d", "direction": "credit", "reference": "SAME"},
            ]
        }
        self.preview = {
            "mode": "SECTION_03_PREVIEW_ONLY_NO_WRITES",
            "schema": "gs_streamlit_v1",
            "local_tenancies": 1,
            "local_bank_rows": 4,
            "missing_evidence_from_stage_1d": ["reassignments.json"],
        }
        self._write("tenancy_bank_reviews_v1.json", {
            "r1": {"decision": "exclude", "reason": "returned"},
            "r3": {"decision": "assign", "tenancy_id": "tenant-1"},
            "r4": {"decision": "pending"},
        })
        self._write("cheque_clearance_reviews_v1h.json", {"schema_version": 1, "history": [
            {"original_credit_row_id": "r1", "returned_debit_row_id": "r2",
             "successful_credit_row_id": "r3", "tenancy_id": "tenant-1"}
        ]})
        self._write("cheque_allocations_v1i.json", {"schema_version": 1, "history": [
            {"original_credit_row_id": "r1", "returned_debit_row_id": "r2",
             "successful_credit_row_id": "r3", "tenancy_id": "tenant-1",
             "rent_posted": False}
        ]})

    def _write(self, name, obj):
        (self.root / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_cheques_classified_without_posting(self):
        result = classify_evidence(self.plan, self.preview, self.root)
        self.assertEqual(result["cheque_related_bank_rows"], 3)
        self.assertEqual(result["classification_counts"]["returned_cheque_reversal_debit"], 1)
        self.assertEqual(result["classification_counts"]["later_cleared_cheque_credit"], 1)
        self.assertEqual(result["classification_counts"]["pending_review"], 1)
        self.assertEqual(result["approved_rent_postings"], 0)
        self.assertTrue(result["all_rows_held"])

    def test_shared_reference_never_creates_fake_match(self):
        self._write("tenancy_bank_reviews_v1.json", {"r4": {"decision": "assign", "tenancy_id": "tenant-1"}})
        result = classify_evidence(self.plan, self.preview, self.root)
        self.assertEqual(result["matched_review_decisions"], 1)
        self.assertEqual(result["classification_counts"]["assigned_reviewed_not_posted"], 1)

    def test_orphan_review_flagged(self):
        self._write("tenancy_bank_reviews_v1.json", {"unknown": {"decision": "assign", "tenancy_id": "tenant-1"}})
        result = classify_evidence(self.plan, self.preview, self.root)
        self.assertEqual(result["orphan_review_decisions"], 1)
        self.assertEqual(result["approved_imports"], 0)

    def test_conflicting_allocation_blocks(self):
        self._write("cheque_allocations_v1i.json", {"schema_version": 1, "history": [
            {"original_credit_row_id": "r1", "returned_debit_row_id": "r2",
             "successful_credit_row_id": "r3", "tenancy_id": "different",
             "rent_posted": False}
        ]})
        with self.assertRaises(ValueError):
            classify_evidence(self.plan, self.preview, self.root)

    def test_missing_audit_blocks(self):
        (self.root / "cheque_allocations_v1i.json").unlink()
        with self.assertRaises(ValueError):
            classify_evidence(self.plan, self.preview, self.root)

    def test_missing_or_duplicate_bank_row_id_blocks(self):
        self.plan["bank_movements"][1]["legacy_bank_row_id"] = "r1"
        with self.assertRaises(ValueError):
            classify_evidence(self.plan, self.preview, self.root)

    def test_stale_snapshot_blocks(self):
        self.preview["local_bank_rows"] = 999
        with self.assertRaises(ValueError):
            classify_evidence(self.plan, self.preview, self.root)

    def test_all_three_evidence_files_remain_unchanged(self):
        names = ("tenancy_bank_reviews_v1.json", "cheque_clearance_reviews_v1h.json", "cheque_allocations_v1i.json")
        before = {name: (self.root / name).read_bytes() for name in names}
        classify_evidence(self.plan, self.preview, self.root)
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in names})


if __name__ == "__main__":
    unittest.main()
