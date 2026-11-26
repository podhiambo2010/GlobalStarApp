"""Section 03 pre-migration safeguards."""
import json
import tempfile
import unittest
from pathlib import Path

from migration_preview_v1_section03 import build_migration_preview
from supabase_compare_v1_readonly import TABLES


class Section03PreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.plan = {
            "schema": "gs_streamlit_v1", "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "tenancies": [{"tenancy_id": "u3"}],
            "bank_movements": [
                {"legacy_bank_row_id": "r1", "fingerprint": "a", "migration_status": "new_staging_candidate"},
                {"legacy_bank_row_id": "r2", "fingerprint": "b", "migration_status": "possible_overlap_review"},
            ],
            "summary": {}, "evidence_inventory": [],
        }
        self.comparison = {
            "mode": "READ_ONLY_COMPARISON_NO_IMPORT",
            "schema": "gs_streamlit_v1",
            "local_tenancies": 1,
            "local_bank_rows": 2,
            "remote_counts": {t: 0 for t in TABLES},
        }

    def test_every_row_held_even_when_database_empty(self):
        result = build_migration_preview(self.plan, self.comparison, self.root)
        self.assertEqual(result["preview_held_rows"], 2)
        self.assertEqual(result["approved_to_import_rows"], 0)
        self.assertEqual(result["approved_rent_postings"], 0)
        self.assertFalse(result["tenancy_reviews"]["present"])

    def test_original_source_untouched(self):
        before = repr(self.plan)
        build_migration_preview(self.plan, self.comparison, self.root)
        self.assertEqual(before, repr(self.plan))

    def test_reversed_cheque_and_approved_allocation_do_not_post(self):
        (self.root / "cheque_clearance_reviews_v1h.json").write_text(json.dumps({
            "schema_version": 1, "history": [{
                "original_credit_row_id": "r1", "returned_debit_row_id": "r2",
                "successful_credit_row_id": "r3", "status": "bank_cleared_pending_allocation"
            }]
        }), encoding="utf-8")
        (self.root / "cheque_allocations_v1i.json").write_text(json.dumps({
            "schema_version": 1, "history": [{
                "successful_credit_row_id": "r3", "status": "allocation_approved_ledger_pending",
                "rent_posted": False
            }]
        }), encoding="utf-8")
        result = build_migration_preview(self.plan, self.comparison, self.root)
        self.assertEqual(result["stage_1h_current_cheque_clearances"], 1)
        self.assertEqual(result["stage_1i_current_rent_allocations_not_posted"], 1)
        self.assertEqual(result["held_reasons"]["cheque_related_source_rows"], 2)
        self.assertEqual(result["approved_rent_postings"], 0)

    def test_bad_comparison_blocked(self):
        with self.assertRaises(ValueError):
            build_migration_preview(self.plan, {**self.comparison, "local_bank_rows": 999}, self.root)
        with self.assertRaises(ValueError):
            build_migration_preview({**self.plan, "schema": "public"}, self.comparison, self.root)

    def test_repeated_ids_are_flagged(self):
        self.plan["bank_movements"][1]["legacy_bank_row_id"] = "r1"
        result = build_migration_preview(self.plan, self.comparison, self.root)
        self.assertEqual(result["held_reasons"]["duplicate_legacy_row_id"], 1)
        self.assertEqual(result["approved_to_import_rows"], 0)

    def test_corrupt_audit_file_refuses_preview(self):
        (self.root / "cheque_allocations_v1i.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_migration_preview(self.plan, self.comparison, self.root)


if __name__ == "__main__":
    unittest.main()
