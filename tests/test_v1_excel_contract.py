"""Regression guard: published V1 must remain Excel-only."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PublishedExcelOnlyContract(unittest.TestCase):
    def test_python_files_parse(self):
        for path in ("app_frontend.py","app_backend.py"):
            with self.subTest(path=path):
                ast.parse((ROOT/path).read_text(encoding="utf-8"), filename=path)

    def test_no_supabase_client_or_database_writes(self):
        frontend=(ROOT/"app_frontend.py").read_text(encoding="utf-8")
        backend=(ROOT/"app_backend.py").read_text(encoding="utf-8")
        requirements=(ROOT/"requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("supabase",frontend.lower())
        self.assertNotIn("from supabase import",backend)
        self.assertNotIn("create_client(",backend)
        self.assertNotIn("SUPABASE_",backend)
        self.assertNotIn(".table(",backend)
        self.assertNotIn("supabase",requirements.lower())

    def test_original_features_remain(self):
        frontend=(ROOT/"app_frontend.py").read_text(encoding="utf-8")
        for feature in (
            "Dashboard & Arrears","Deposit & Lease Ledger",
            "Unmapped Payment Auditor","Lease PDF AI Extractor & Alerts",
            "Arrears Payment Reminders","eTIMS Tax Invoices & Bank Statements",
            "Demand Notice Builder","Bank Statement Audit","Annual P&L & iTax Statement",
        ):
            with self.subTest(feature=feature):
                self.assertIn(feature,frontend)
        self.assertIn("Lease overview from the uploaded tenant workbook",frontend)
        self.assertIn("_workbook_category",frontend)

    def test_no_v2_only_pages(self):
        for path in (
            "import_review_ui.py","bank_cumulative_ui.py",
            "pages/03_Review_and_Approve_Differences.py",
            "pages/04_Cumulative_Bank_Updates.py",
        ):
            self.assertFalse((ROOT/path).exists(), path)

if __name__=="__main__":
    unittest.main()
