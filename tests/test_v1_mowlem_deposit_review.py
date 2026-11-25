import tempfile
import unittest
from pathlib import Path
from deposit_reconciliation_v1 import load_records, update_record, overview_rows

class MowlemDepositReviewTests(unittest.TestCase):
    def test_owner_attested_distinct_from_bank_verified(self):
        rows = overview_rows(load_records(Path(tempfile.gettempdir()) / "absent_mowlem_fixture_very_unlikely.json"))
        self.assertEqual(rows[0]["Owner-reported received (KSh)"], 75000)
        self.assertIn("bank evidence pending", rows[0]["Evidence status"])
        self.assertEqual(rows[1]["Owner-reported unpaid (KSh)"], 60000)
    def test_changes_preserve_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "status.json"
            self.assertTrue(update_record(p, 13, 10000, "Part-paid; bank evidence pending", "Receipt pending check"))
            doc = load_records(p)
            self.assertEqual(len(doc["history"]), 1)
            self.assertEqual(overview_rows(doc)[1]["Owner-reported unpaid (KSh)"], 50000)
            self.assertFalse(update_record(p, 13, 10000, "Part-paid; bank evidence pending", "Receipt pending check"))
            self.assertEqual(len(load_records(p)["history"]), 1)
    def test_reject_out_of_range_and_unsubstantiated_status(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "status.json"
            with self.assertRaises(ValueError):
                update_record(p, 13, 90000, "Part-paid; bank evidence pending", "No")
            with self.assertRaises(ValueError):
                update_record(p, 13, 60000, "Bank-verified", "")
            self.assertFalse(p.exists())

if __name__ == "__main__":
    unittest.main()
