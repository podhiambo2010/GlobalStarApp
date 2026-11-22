"""Read-only allocation review must not create rent or mutate source data."""
import unittest
import pandas as pd
from tenant_allocation_review_v1 import review_excluded_credits, export_allocation_review

class AllocationAuditTests(unittest.TestCase):
    def test_all_four_credits_remain_pending(self):
        input_rows = [
            ("03.12.2025", "GETCASH CAPITAL LIMITED DECEMBERRENT", "A", 13000, True, 8),
            ("18.12.2025", "TRANSFER 8035949 MPESA PETE", "B", 4000, True, 26),
            ("08.01.2026", "GETCASH CAPITAL LIMITED JANUARYRENT", "C", 13000, True, 44),
            ("04.02.2026", "GETCASH CAPITAL LIMITED JANUARYRENT", "D", 13000, True, 86),
        ]
        bank = pd.DataFrame(input_rows, columns=[
            "Transaction Date", "Transaction Details", "Ref_Clean", "Money In Num",
            "Excluded_From_Legacy_Analysis", "Original_Statement_Row"])
        bank_copy = bank.copy(deep=True)
        tenants = pd.DataFrame([{"Tenant Name": "GetCash Capital Limited", "Shop #": 12}])
        audit, totals = review_excluded_credits(bank, bank.iloc[0:0], tenants)
        self.assertEqual(totals["excluded_credits"], 4)
        self.assertEqual(totals["amount"], 43000)
        self.assertTrue((audit["Decision"] == "Needs evidence — no allocation").all())
        self.assertEqual(audit["Transaction ID (source row)"].tolist(), [8,26,44,86])
        self.assertEqual(len(audit[audit["Suggested tenant / classification"].str.contains("Possible tenant:")]), 3)
        pd.testing.assert_frame_equal(bank, bank_copy)
        self.assertTrue(export_allocation_review(audit, totals).startswith(b"PK"))

    def test_repeat_bank_reference_not_equated_to_same_payment(self):
        rows = pd.DataFrame([
            ["03.12.2025", "Rent 1", "SHARED", 13000, True, 8],
            ["04.12.2025", "Rent 2", "SHARED", 13000, True, 9]
        ], columns=["Transaction Date", "Transaction Details", "Ref_Clean", "Money In Num", "Excluded_From_Legacy_Analysis", "Original_Statement_Row"])
        audit, summary = review_excluded_credits(rows, pd.DataFrame(), pd.DataFrame())
        self.assertEqual(summary["excluded_credits"], 2)
        self.assertEqual(len(audit), 2)

if __name__ == "__main__":
    unittest.main()
