"""Section 04A read-only evidence inventory contract tests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from section04a_evidence_audit import summarize


class EvidenceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "live"
        self.backup = Path(self.temp.name) / "backup"
        self.root.mkdir()
        self.backup.mkdir()
        self.write(self.root, "tenancy_bank_reviews_v1.json", {
            "r1": {"decision": "assign", "tenancy_id": "u1"},
            "r2": {"decision": "exclude", "reason": "not income"},
        })
        self.write(self.backup, "GlobalStar_V1_Tenancy_Bank_Review_Backup.json", {
            "r1": {"decision": "assign", "tenancy_id": "u1"},
            "r2": {"decision": "assign", "tenancy_id": "u2"},
            "r3": {"decision": "pending"},
        })
        self.write(self.root, "tenancy_bank_review_history_v1.json", [
            {"bank_row_id": "r1", "action": "assign"},
            {"bank_row_id": "r2", "action": "exclude"},
            {"bank_row_id": "legacy", "action": "exclude"},
        ])
        self.write(self.root, "cheque_clearance_reviews_v1h.json", {
            "schema_version": 1,
            "history": [
                {"original_credit_row_id": "c1", "successful_credit_row_id": "s1",
                 "cheque_number": "4525"},
                {"original_credit_row_id": "c1", "successful_credit_row_id": "s1",
                 "cheque_number": "4525"},
            ],
        })
        self.write(self.root, "cheque_allocations_v1i.json", {
            "schema_version": 1,
            "history": [{"successful_credit_row_id": "s1", "rent_posted": False}],
        })

    def write(self, folder, name, obj):
        (folder / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_archived_conflicts_and_orphan_audit_are_reported(self):
        r = summarize(self.root, self.backup)
        self.assertEqual(r["live_decisions"], 2)
        self.assertEqual(r["archived_decisions"], 3)
        self.assertEqual(r["content_conflicts_for_shared_ids"], ["r2"])
        self.assertEqual(r["only_in_archive"], ["r3"])
        self.assertEqual(r["audit_ids_not_in_live_register"], ["legacy"])
        self.assertEqual(r["cheque_clearance_history_events"], 2)
        self.assertEqual(r["latest_cheques"], 1)
        self.assertEqual(r["latest_unposted_allocation_count"], 1)
        self.assertFalse(r["migration_authorized"])
        self.assertEqual(r["status"], "REQUIRES_MANUAL_RECONCILIATION")

    def test_source_files_not_modified(self):
        names = list(self.root.iterdir()) + list(self.backup.iterdir())
        before = {str(p): p.read_bytes() for p in names}
        summarize(self.root, self.backup)
        self.assertEqual(before, {str(p): p.read_bytes() for p in names})

    def test_missing_live_reviews_blocks_without_fallback(self):
        (self.root / "tenancy_bank_reviews_v1.json").unlink()
        with self.assertRaises(ValueError):
            summarize(self.root, self.backup)

    def test_corrupt_audit_blocks(self):
        (self.root / "tenancy_bank_review_history_v1.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            summarize(self.root, self.backup)


if __name__ == "__main__":
    unittest.main()
