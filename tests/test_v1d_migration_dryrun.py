import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
import pandas as pd
from migration_dryrun_v1d import (
    bank_overlap_dry_run, evidence_inventory, prepare_local_migration,
)


class MigrationDryRunTests(unittest.TestCase):
    def setUp(self):
        self.rows = pd.DataFrame([{
            "Transaction Date": "21.09.2025", "Money In Num": 20000,
            "Money Out Num": 0, "Transaction Details": "Rent by payer",
            "Ref_Clean": "ABC", "Bank_Row_ID": "old-id:1",
        }])
        self.register = pd.DataFrame([{
            "Tenancy_ID": "10:test", "Shop #": 10, "Tenant Name": "Mowlem",
            "Tenancy_Status": "current", "Report_Status": "Current",
        }])
        self.openings = {"schema": 1, "balances": {
            "10:test": {"amount_cents": 0, "as_of": "2025-09-01",
                        "evidence": "owner assumed zero rent balance"}
        }, "history": []}

    def test_nonunique_reference_repeated_same_file_is_flagged(self):
        result = bank_overlap_dry_run(pd.concat(
            [self.rows, self.rows], ignore_index=True), "KCB-1")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(x["migration_status"] == "ambiguous_identical_rows"
                            for x in result))

    def test_existing_fingerprint_without_unique_bank_id_is_review(self):
        first = bank_overlap_dry_run(self.rows, "KCB-1")
        second = bank_overlap_dry_run(
            self.rows, "KCB-1", [first[0]["fingerprint"]])
        self.assertEqual(second[0]["migration_status"], "possible_overlap_review")

    def test_outgoing_transaction_remains_negative(self):
        rows = self.rows.copy()
        rows["Money In Num"] = 0
        rows["Money Out Num"] = 6000
        result = bank_overlap_dry_run(rows, "KCB-1")
        self.assertEqual(result[0]["amount"], "-6000.00")

    def test_manifest_does_not_modify_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "opening_balances_v1.json"
            path.write_text(json.dumps(self.openings), encoding="utf-8")
            before = path.read_bytes()
            manifest = prepare_local_migration(
                self.register, self.rows, self.openings, "KCB-1", folder)
            self.assertEqual(manifest["summary"]["opening_balance_entries"], 1)
            self.assertEqual(manifest["mode"], "DRY_RUN_ONLY_NO_DB_WRITES")
            self.assertEqual(path.read_bytes(), before)

    def test_unknown_tenancy_opening_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "unknown tenancy ID"):
                prepare_local_migration(
                    self.register, self.rows,
                    {"balances": {"someone_else": {"amount_cents": 0}}},
                    "KCB-1", folder)

    def test_malformed_json_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "ignored_transactions.json").write_text("{broken")
            inventory = evidence_inventory(folder)
            invalid = [e for e in inventory if e["name"] == "ignored_transactions.json"][0]
            self.assertFalse(invalid["valid_json_structure"])


if __name__ == "__main__":
    unittest.main()
