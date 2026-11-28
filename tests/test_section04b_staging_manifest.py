"""Section 04B staging manifest safety tests. No real DB connection."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from section04b_staging_manifest import build_manifest


class StagingManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "live"
        self.backup = Path(self.temp.name) / "backup"
        self.root.mkdir()
        self.backup.mkdir()
        self.write(self.root, "tenancy_bank_reviews_v1.json", {
            "r1": {"decision": "assign", "tenancy_id": "2:t1"},
            "r2": {"decision": "exclude", "reason": "not rental income"},
        })
        self.write(self.backup, "GlobalStar_V1_Tenancy_Bank_Review_Backup.json", {
            "r1": {"decision": "assign", "tenancy_id": "2:t1"},
            "r2": {"decision": "exclude", "reason": "not rental income"},
        })
        self.write(self.root, "tenancy_bank_review_history_v1.json", [
            {"bank_row_id": "r1", "action": "assign"},
            {"bank_row_id": "r2", "action": "exclude"},
            {"bank_row_id": "s1", "action": "split_receipt"},
        ])
        self.write(self.root, "tenancy_receipt_splits_v1.json", {
            "s1": {"tenancy_id": "2:t1", "components": [
                {"component": "deposit", "amount_ksh": "5000.00"},
            ]},
        })
        self.write(self.root, "cheque_clearance_reviews_v1h.json", {
            "schema_version": 1, "history": [
                {"original_credit_row_id": "c1",
                 "successful_credit_row_id": "clear1",
                 "tenancy_id": "incorrect", "cheque_number": "4680",
                 "status": "bank_cleared_pending_allocation"},
                {"original_credit_row_id": "c1",
                 "successful_credit_row_id": "clear1",
                 "tenancy_id": "2:t1", "cheque_number": "4680",
                 "status": "bank_cleared_pending_allocation",
                 "corrects_prior_tenancy": True},
            ]})
        self.write(self.root, "cheque_allocations_v1i.json", {
            "schema_version": 1, "history": [
                {"successful_credit_row_id": "clear1",
                 "tenancy_id": "2:t1", "cheque_number": "4680",
                 "amount_ksh": "30000.00",
                 "allocations": [{"rent_period": "2025-11-01", "amount_ksh": "30000.00"}],
                 "rent_posted": False}
            ]})
        self.write(self.root, "ignored_transactions.json", {"OLDREF": True})
        self.write(self.root, "reassignments.json", {"OLDREF2": 2})

    @staticmethod
    def write(folder, name, data):
        (folder / name).write_text(json.dumps(data), encoding="utf-8")

    def test_dry_run_counts_and_preserves_superseded_cheque_event(self):
        result = build_manifest(self.root, self.backup)
        self.assertEqual(result["comparison"]["audit_events"], 3)
        self.assertEqual(result["comparison"]["receipt_splits"], 1)
        self.assertEqual(result["comparison"]["unresolved_audit_ids"], [])
        self.assertEqual(result["staging_event_counts"]["cheque_clearance"], 2)
        self.assertEqual(result["staging_event_counts"]["cheque_allocation"], 1)
        self.assertEqual(len(result["approved_allocations_still_unposted"]), 1)
        self.assertEqual(result["approved_allocations_still_unposted"][0]["approved_allocation_ksh"], "30000.00")
        self.assertFalse(result["import_approved"])
        self.assertEqual(result["supabase_writes"], 0)

    def test_source_files_remain_unchanged(self):
        paths = list(self.root.iterdir()) + list(self.backup.iterdir())
        before = {str(p): p.read_bytes() for p in paths}
        build_manifest(self.root, self.backup)
        self.assertEqual(before, {str(p): p.read_bytes() for p in paths})

    def test_missing_split_audit_blocks(self):
        self.write(self.root, "tenancy_receipt_splits_v1.json", {})
        with self.assertRaises(ValueError):
            build_manifest(self.root, self.backup)

    def test_conflicting_cheque_tenancy_blocks(self):
        data = json.loads((self.root / "cheque_allocations_v1i.json").read_text())
        data["history"][0]["tenancy_id"] = "another-tenant"
        self.write(self.root, "cheque_allocations_v1i.json", data)
        with self.assertRaises(ValueError):
            build_manifest(self.root, self.backup)

    def test_legacy_reference_data_stays_hint(self):
        result = build_manifest(self.root, self.backup)
        hints = [e for e in result["staging_events"] if e["source_kind"].startswith("legacy_reference")]
        self.assertEqual(len(hints), 2)
        self.assertTrue(all(e["reference_only_cannot_autopost"] for e in hints))


if __name__ == "__main__":
    unittest.main()
