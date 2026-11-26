"""Section 02 has no write path and never mixes Commercial schema records."""
import unittest
from unittest.mock import patch

from supabase_compare_v1_readonly import TABLES, compare_summary, read_remote_state


class ReadOnlyComparisonTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "schema": "gs_streamlit_v1",
            "mode": "DRY_RUN_ONLY_NO_DB_WRITES",
            "tenancies": [{"tenancy_id": "unit-3"}],
            "bank_movements": [
                {"fingerprint": "abc", "legacy_bank_row_id": "row1"},
                {"fingerprint": "def", "legacy_bank_row_id": "row2"},
            ],
        }

    def test_empty_database_does_not_import_anything(self):
        report = compare_summary(self.plan, {table: 0 for table in TABLES})
        self.assertEqual(report["mode"], "READ_ONLY_COMPARISON_NO_IMPORT")
        self.assertEqual(report["local_bank_rows"], 2)
        self.assertEqual(report["unmatched_local_bank_rows"], 2)
        self.assertEqual(report["remote_counts"]["bank_movements"], 0)

    def test_comparison_does_not_change_input_manifest(self):
        snapshot = repr(self.plan)
        report = compare_summary(self.plan, {table: 0 for table in TABLES}, ["abc"])
        self.assertEqual(report["bank_fingerprint_matches"], 1)
        self.assertEqual(repr(self.plan), snapshot)

    def test_overlapping_fingerprints_cannot_authorize_deduplication(self):
        self.plan["bank_movements"].append(
            {"fingerprint": "abc", "legacy_bank_row_id": "row3"}
        )
        report = compare_summary(self.plan, {table: 0 for table in TABLES}, ["abc"])
        self.assertTrue(report["requires_review"])
        self.assertEqual(report["local_duplicate_fingerprint_groups"], 1)
        self.assertEqual(report["bank_fingerprint_matches"], 2)

    def test_wrong_schema_or_non_dry_run_rejected(self):
        with self.assertRaises(ValueError):
            compare_summary({**self.plan, "schema": "public"}, {table: 0 for table in TABLES})
        with self.assertRaises(ValueError):
            compare_summary({**self.plan, "mode": "POST"}, {table: 0 for table in TABLES})

    def test_missing_secret_fails_closed_without_connecting(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                read_remote_state()


if __name__ == "__main__":
    unittest.main()
