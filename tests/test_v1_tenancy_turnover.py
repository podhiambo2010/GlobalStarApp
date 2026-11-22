"""Regression tests for Excel-only turnover; run with python -m unittest tests.test_v1_tenancy_turnover -v."""
import unittest
from datetime import datetime
import pandas as pd
from tenancy_turnover_v1 import tenancy_register, classify_credits


class TenantTurnoverTests(unittest.TestCase):
    def rows(self):
        return pd.DataFrame([
            {"Shop #": 12, "Tenant Name": "Pilona Bookshop", "Lease Date": "2024-01-05",
             "Lease End Date": "2026-08-31", "Monthly Rate": 25000,
             "Tenancy Record Status": "Former"},
            {"Shop #": 12, "Tenant Name": "Arnoda Anyango Ofafa", "Lease Date": "2026-12-01",
             "Lease End Date": None, "Monthly Rate": 25000,
             "Tenancy Record Status": "Current"},
            {"Shop #": 13, "Tenant Name": "Crown Courier", "Lease Date": "2025-07-03",
             "Lease End Date": "2026-07-22", "Monthly Rate": 20000,
             "Tenancy Record Status": "Former"},
            {"Shop #": 13, "Tenant Name": "Mowlem Holdings", "Lease Date": "2026-09-03",
             "Lease End Date": None, "Monthly Rate": 20000,
             "Tenancy Record Status": "Current"},
            {"Shop #": 100, "Tenant Name": "UNALLOCATED", "Lease Date": None,
             "Lease End Date": None, "Monthly Rate": 121600,
             "Tenancy Record Status": "Vacancy"}
        ])

    def test_former_future_and_vacancy_are_not_charged(self):
        result = tenancy_register(self.rows(), "2026-11-01", "2026-11-30")
        self.assertEqual(len(result), 5)
        self.assertEqual(result.loc[0, "Expected_Rent"], 0)
        self.assertEqual(result.loc[1, "Expected_Rent"], 0)
        self.assertEqual(result.loc[1, "Report_Status"], "Future")
        self.assertEqual(result.loc[4, "Expected_Rent"], 0)
        self.assertEqual(result.loc[3, "Expected_Rent"], 20000)

    def test_partial_month_and_tenancy_id(self):
        result = tenancy_register(self.rows(), "2026-09-01", "2026-09-30")
        self.assertAlmostEqual(result.loc[3, "Expected_Rent"], 20000 * 28 / 30, places=2)
        self.assertNotEqual(result.loc[0, "Tenancy_ID"], result.loc[1, "Tenancy_ID"])

    def test_old_tenant_payment_never_moves_to_successor(self):
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-12-31")
        tx = pd.DataFrame([
            {"Transaction Date": "21.07.2026", "Transaction Details": "CROWN COURIER",
             "Money In Num": 20000, "Valid_Credit": True, "Ref_Clean": "X1"},
            {"Transaction Date": "10.09.2026", "Transaction Details": "CROWN COURIER",
             "Money In Num": 20000, "Valid_Credit": True, "Ref_Clean": "X2"},
            {"Transaction Date": "20.09.2026", "Transaction Details": "MOWLEM HOLDINGS",
             "Money In Num": 20000, "Valid_Credit": True, "Ref_Clean": "X3"}
        ])
        r, p = classify_credits(tx, reg, lambda *args: 13, "2026-07-01", "2026-12-31")
        self.assertEqual(p["Allocation_Status"].tolist(), [
            "Identified (verify before notice)", "Review required",
            "Identified (verify before notice)"
        ])
        self.assertEqual(r.loc[2, "Actual_Collected"], 20000)
        self.assertEqual(r.loc[3, "Actual_Collected"], 20000)

    def test_former_missing_departure_is_flagged(self):
        rows = self.rows()
        rows.loc[0, "Lease End Date"] = None
        reg = tenancy_register(rows, "2026-11-01", "2026-11-30")
        self.assertTrue(reg.loc[0, "Review_Required"])
        self.assertEqual(reg.loc[0, "Expected_Rent"], 0)


if __name__ == "__main__":
    unittest.main()
