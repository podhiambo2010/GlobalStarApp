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
        self.assertEqual(r.loc[2, "Actual_Collected"], 0)
        self.assertEqual(r.loc[3, "Actual_Collected"], 0)
        self.assertEqual(r.loc[2, "Provisional_Credits"], 20000)
        self.assertEqual(r.loc[3, "Provisional_Credits"], 20000)

    def test_approved_allocation_targets_exact_tenancy(self):
        from bank_review_v1 import bank_row_ids, record_decision
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-12-31")
        tx = pd.DataFrame([
            {"Transaction Date": "21.07.2026", "Value Date": "21.07.2026",
             "Transaction Details": "CROWN COURIER", "Money In Num": 20000,
             "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "SHARED"},
            {"Transaction Date": "20.09.2026", "Value Date": "20.09.2026",
             "Transaction Details": "MOWLEM HOLDINGS", "Money In Num": 20000,
             "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "SHARED"},
        ])
        ids = bank_row_ids(tx)
        self.assertNotEqual(ids[0], ids[1])
        decisions = record_decision({}, ids[0], "assign", reg.loc[2, "Tenancy_ID"], "receipt checked")
        decisions = record_decision(decisions, ids[1], "assign", reg.loc[3, "Tenancy_ID"], "receipt checked")
        result, p = classify_credits(tx, reg, lambda *x: 13,
                                      "2026-07-01", "2026-12-31", reviews=decisions)
        self.assertEqual(result.loc[2, "Actual_Collected"], 20000)
        self.assertEqual(result.loc[3, "Actual_Collected"], 20000)
        self.assertTrue((p["Allocation_Status"] == "Assigned (reviewed)").all())

    def test_legacy_ref_exclusion_not_applied_to_both_rows(self):
        from bank_review_v1 import bank_row_ids, record_decision
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-12-31")
        tx = pd.DataFrame([
            {"Transaction Date": "21.07.2026", "Value Date": "21.07.2026",
             "Transaction Details": "CROWN COURIER", "Money In Num": 20000,
             "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "SAME"},
            {"Transaction Date": "20.09.2026", "Value Date": "20.09.2026",
             "Transaction Details": "MOWLEM HOLDINGS", "Money In Num": 20000,
             "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "SAME"},
        ])
        ids = bank_row_ids(tx)
        decisions = record_decision({}, ids[0], "exclude", reason="bank correction confirmed")
        result, p = classify_credits(
            tx, reg, lambda *x: 13, "2026-07-01", "2026-12-31",
            reviews=decisions, old_ignored={"SAME": True})
        self.assertEqual(p["Allocation_Status"].tolist(),
                         ["Excluded (reviewed)", "Legacy decision: reverify"])
        self.assertEqual(result["Actual_Collected"].sum(), 0)

    def test_row_ids_handle_repeated_reference_and_identical_rows(self):
        from bank_review_v1 import bank_row_ids
        data = pd.DataFrame([{"Transaction Date": "02.11.2026", "Ref_Clean": "FTX",
                              "Transaction Details": "Deposit", "Money In Num": 1000,
                              "Money Out Num": 0}] * 2)
        ids = bank_row_ids(data)
        self.assertEqual(len(set(ids)), 2)

    def test_tenancy_identity_survives_workbook_sort(self):
        original = tenancy_register(self.rows(), "2026-11-01", "2026-11-30")
        shuffled = tenancy_register(self.rows().iloc[::-1].reset_index(drop=True),
                                    "2026-11-01", "2026-11-30")
        self.assertEqual(set(original["Tenancy_ID"]), set(shuffled["Tenancy_ID"]))

    def test_approved_row_overrides_legacy_reference_without_affecting_sibling(self):
        from bank_review_v1 import bank_row_ids, record_decision
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-12-31")
        tx = pd.DataFrame([
            {"Transaction Date": "21.07.2026", "Transaction Details": "CROWN COURIER",
             "Money In Num": 20000, "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "FTX"},
            {"Transaction Date": "20.09.2026", "Transaction Details": "MOWLEM HOLDINGS",
             "Money In Num": 20000, "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "FTX"}
        ])
        rid = bank_row_ids(tx)[0]
        entries = record_decision({}, rid, "assign", reg.loc[2, "Tenancy_ID"], "receipt checked")
        updated, bank = classify_credits(tx, reg, lambda *x: 13,
            "2026-07-01", "2026-12-31", reviews=entries, old_overrides={"FTX": 13})
        self.assertEqual(bank.iloc[0]["Allocation_Status"], "Assigned (reviewed)")
        self.assertEqual(bank.iloc[1]["Allocation_Status"], "Legacy decision: reverify")
        self.assertEqual(updated.loc[2, "Actual_Collected"], 20000)
        self.assertEqual(updated.loc[3, "Actual_Collected"], 0)

    def test_former_missing_departure_is_flagged(self):
        rows = self.rows()
        rows.loc[0, "Lease End Date"] = None
        reg = tenancy_register(rows, "2026-11-01", "2026-11-30")
        self.assertTrue(reg.loc[0, "Review_Required"])
        self.assertEqual(reg.loc[0, "Expected_Rent"], 0)


if __name__ == "__main__":
    unittest.main()
