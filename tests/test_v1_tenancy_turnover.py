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

    def test_original_alias_matches_single_occupant_without_legal_name_token(self):
        rows = self.rows().iloc[[0]].copy()
        rows["Shop #"] = 9
        rows["Tenant Name"] = "Midtown Barbershop"
        rows["Tenancy Record Status"] = "Current"
        rows["Lease End Date"] = None
        reg = tenancy_register(rows, "2026-07-01", "2026-07-31")
        bank = pd.DataFrame([{"Transaction Date": "10.07.2026",
            "Transaction Details": "MPESA JOE /", "Money In Num": 10000,
            "Valid_Credit": True, "Ref_Clean": "FIRST"}])
        result, credits = classify_credits(
            bank, reg,
            lambda details, ref, customer: 9 if "JOE" in details else 0,
            "2026-07-01", "2026-07-31")
        self.assertEqual(credits.iloc[0]["Allocation_Status"], "Identified (verify before notice)")
        self.assertEqual(result.iloc[0]["Provisional_Credits"], 10000)

    def test_unique_legacy_override_preserved_as_provisional(self):
        from bank_review_v1 import bank_row_ids
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-07-31")
        bank = pd.DataFrame([{"Transaction Date": "12.07.2026",
            "Transaction Details": "Uninformative payer", "Money In Num": 10000,
            "Valid_Credit": True, "Ref_Clean": "OLD-REF"}])
        result, credits = classify_credits(
            bank, reg, lambda *args: 0, "2026-07-01", "2026-07-31",
            old_overrides={"OLD-REF": 12})
        self.assertEqual(credits.iloc[0]["Allocation_Status"],
                         "Identified (legacy override, verify tenancy)")
        self.assertEqual(result.loc[0, "Provisional_Credits"], 10000)
        self.assertEqual(result.loc[0, "Actual_Collected"], 0)

    def test_unique_legacy_exclusion_keeps_out_credit(self):
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-07-31")
        bank = pd.DataFrame([{"Transaction Date": "12.07.2026",
            "Transaction Details": "Excluded director movement", "Money In Num": 10000,
            "Valid_Credit": True, "Ref_Clean": "EXCLUDED"}])
        result, credits = classify_credits(bank, reg, lambda *args: 12,
            "2026-07-01", "2026-07-31", old_ignored={"EXCLUDED": True})
        self.assertEqual(credits.iloc[0]["Allocation_Status"], "Excluded (legacy)")
        self.assertEqual(result["Provisional_Credits"].sum(), 0)

    def test_restored_legacy_exclusion_reruns_original_description_matcher(self):
        from bank_review_v1 import bank_row_ids, record_decision
        reg = tenancy_register(self.rows().iloc[[0]], "2026-07-01", "2026-07-31")
        bank = pd.DataFrame([{"Transaction Date": "12.07.2026",
            "Transaction Details": "PILONA rental payment",
            "Money In Num": 10000, "Money Out Num": 0,
            "Valid_Credit": True, "Ref_Clean": "RESTOREME"}])
        rid = bank_row_ids(bank)[0]
        decision = record_decision({}, rid, "restore", reason="Originally excluded in error")
        result, payments = classify_credits(bank, reg,
            lambda details, ref, customer: 12 if "PILONA" in details else 0,
            "2026-07-01", "2026-07-31", reviews=decision,
            old_ignored={"RESTOREME": True})
        self.assertEqual(payments.iloc[0]["Allocation_Status"],
                         "Identified (verify before notice)")
        self.assertEqual(result.iloc[0]["Provisional_Credits"], 10000)
        self.assertEqual(result.iloc[0]["Actual_Collected"], 0)

    def test_restoring_one_shared_reference_keeps_other_row_unresolved(self):
        from bank_review_v1 import bank_row_ids, record_decision
        reg = tenancy_register(self.rows(), "2026-07-01", "2026-12-31")
        bank = pd.DataFrame([
            {"Transaction Date": "21.07.2026", "Transaction Details": "CROWN COURIER",
             "Money In Num": 10000, "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "SHARED"},
            {"Transaction Date": "20.09.2026", "Transaction Details": "MOWLEM HOLDINGS",
             "Money In Num": 20000, "Money Out Num": 0, "Valid_Credit": True, "Ref_Clean": "SHARED"},
        ])
        decision = record_decision({}, bank_row_ids(bank)[0], "restore", reason="Wrongly excluded")
        result, payments = classify_credits(bank, reg, lambda *args: 13,
            "2026-07-01", "2026-12-31", reviews=decision,
            old_ignored={"SHARED": True})
        self.assertEqual(payments["Allocation_Status"].tolist(),
            ["Identified (verify before notice)", "Legacy decision: reverify"])
        self.assertEqual(result["Actual_Collected"].sum(), 0)

    def test_restore_requires_reason_and_history_retains_both_actions(self):
        from bank_review_v1 import (record_decision, append_review_event, load_event_history)
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with self.assertRaises(ValueError):
            record_decision({}, "row1", "restore")
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "history.json")
            append_review_event(path, bank_row_id="row1", reference="BANK1",
                action="exclude", reason="initial review", previous="unreviewed", actor="tester")
            append_review_event(path, bank_row_id="row1", reference="BANK1",
                action="restore", reason="incorrect exclusion", previous="exclude", actor="tester")
            records = load_event_history(path)
            self.assertEqual([entry["action"] for entry in records], ["exclude", "restore"])
            self.assertEqual(records[1]["reason"], "incorrect exclusion")
    def test_former_missing_departure_is_flagged(self):
        rows = self.rows()
        rows.loc[0, "Lease End Date"] = None
        reg = tenancy_register(rows, "2026-11-01", "2026-11-30")
        self.assertTrue(reg.loc[0, "Review_Required"])
        self.assertEqual(reg.loc[0, "Expected_Rent"], 0)


if __name__ == "__main__":
    unittest.main()
