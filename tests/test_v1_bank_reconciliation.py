"""Excel-only full-ledger reconciliation tests (no database, no writes)."""
import unittest
from io import BytesIO
import pandas as pd
from bank_reconciliation_v1 import reconcile_bank_ledger, export_reconciliation

class BankReconciliationTests(unittest.TestCase):
    def test_unfiltered_bank_rows_expose_four_discontinuities(self):
        movements = [
            ("19.11.2025", "BALANCE B/FWD", "77,240.18", 0, 0, None, False),
            ("05.12.2025", "Credit A", "263,070.93", 194907, 0, "ABC", False),
            ("18.12.2025", "Payment", "202.18", 0, 3797.82, "ABC", True),
            ("08.01.2026", "Credit B", "166,788.18", 25000, 0, "ABC", False),
            ("05.02.2026", "Bank fee", "148,095.18", 0, 76.25, "ABC", False),
        ]
        # Different references are not required for distinct ledger movements.
        df = pd.DataFrame(movements, columns=[
            "Transaction Date", "Transaction Details", "Ledger Balance",
            "Money In Num", "Money Out Num", "Bank Reference Number",
            "Excluded_From_Legacy_Analysis",
        ])
        audit, exceptions, summary = reconcile_bank_ledger(df)
        self.assertEqual(summary["rows"], 5)
        self.assertEqual(summary["exceptions"], 4)
        self.assertEqual(summary["excluded_from_legacy_analysis"], 1)
        self.assertEqual(len(exceptions), 4)
        self.assertEqual(summary["difference"], -145177.93)  # arithmetic from synthetic test fixture
        self.assertTrue(export_reconciliation(audit, exceptions, summary).startswith(b"PK"))

    def test_balanced_movements_are_not_flagged_and_ref_can_repeat(self):
        df = pd.DataFrame([
            ("01.01.2026", "100.00", 0, 0, "R1", False),
            ("01.01.2026", "150.00", 50, 0, "R1", False),
            ("01.01.2026", "145.00", 0, -5, "R1", True),
        ], columns=["Transaction Date", "Ledger Balance", "Money In Num", "Money Out Num",
                    "Bank Reference Number", "Excluded_From_Legacy_Analysis"])
        _, ex, summary = reconcile_bank_ledger(df)
        self.assertTrue(ex.empty)
        self.assertEqual(summary["excluded_from_legacy_analysis"], 1)

    def test_source_rows_are_not_changed(self):
        source = pd.DataFrame([{
            "Transaction Date": "01.01.2026", "Ledger Balance": "100",
            "Money In Num": 0, "Money Out Num": 0
        }])
        original = source.copy(deep=True)
        reconcile_bank_ledger(source)
        pd.testing.assert_frame_equal(source, original)

if __name__ == "__main__":
    unittest.main()
