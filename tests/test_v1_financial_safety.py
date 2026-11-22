"""Regression tests: eTIMS must fail closed and bank review must never claim tax."""
from datetime import datetime
import unittest
import pandas as pd
from etims_service import KRAeTIMSClient
from financial_review_v1 import financial_period, review_bank_movements, excel_review_export

class FinancialSafetyTests(unittest.TestCase):
    def test_eTIMS_not_certified_without_external_verification(self):
        client = KRAeTIMSClient()
        ok, device, message = client.initialize_device()
        self.assertFalse(ok)
        result = client.transmit_rent_invoice("Test", "N/A", 1, 12000)
        self.assertNotEqual(result["status"], "SUCCESS")
        self.assertIsNone(result["receipt_signature"])
        self.assertIsNone(result["qr_code_url"])

    def test_legacy_pdf_generation_blocks_unsafe_output(self):
        from app_backend import TenantPortalBackend
        obj = object.__new__(TenantPortalBackend)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            obj.generate_kra_compliance_summary_pdf()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            obj.generate_etims_tax_invoice_pdf("Example", 1, 1000, "", "", "", "", "", "")

    def test_frontend_has_no_unverified_tax_estimate_or_embedded_tokens(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "app_frontend.py").read_text(encoding="utf-8")
        self.assertNotIn("chargeable_income = max(0.0", source)
        self.assertNotIn("KRATK04_F7FB9", source)
        self.assertNotIn("EAASZC9", source)
        self.assertNotIn("atsk_6e221", source)
        self.assertIn("financial_review_v1 import", source)

    def test_financial_year_ends_30_june(self):
        start, end = financial_period(2026, "Annual")
        self.assertEqual(start, pd.Timestamp("2025-07-01"))
        self.assertEqual(end, pd.Timestamp("2026-06-30"))
        self.assertEqual(financial_period(2026, "Bi-Annual", "H2")[0], pd.Timestamp("2026-01-01"))
        self.assertEqual(financial_period(2026, "Quarterly", "Q4")[0], pd.Timestamp("2026-04-01"))

    def test_bank_credits_are_not_mislabeled_rent(self):
        bank = pd.DataFrame([
            {"Transaction Date": "19.11.2025", "Money In Num": 25000, "Money Out Num": 0},
            {"Transaction Date": "20.11.2025", "Money In Num": 0, "Money Out Num": -10000},
            {"Transaction Date": "21.11.2025", "Money In Num": 0, "Money Out Num": 0},
        ])
        start, end = financial_period(2026, "Annual")
        df, summary = review_bank_movements(bank, start, end)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["in"], 25000)
        self.assertEqual(summary["out"], 10000)
        self.assertEqual(summary["nonmovement"], 1)
        export = excel_review_export(df, summary, start, end)
        sheet = pd.read_excel(__import__("io").BytesIO(export), sheet_name="Read Me")
        self.assertTrue(sheet["Value"].astype(str).str.contains("NOT CALCULATED").any())
        self.assertFalse(sheet["Field"].astype(str).str.contains("Estimated Tax Payable").any())

if __name__=="__main__":
    unittest.main()
