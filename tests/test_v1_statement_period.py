"""Bank statement baseline and front-end selector regression checks."""
import ast
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from statement_period_v1 import load_baseline, save_baseline, coverage_message

class StatementPeriodTests(unittest.TestCase):
    def test_pinned_date_defaults_to_original_kcb_start(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            self.assertEqual(load_baseline(path), date(2025, 9, 21))
            save_baseline(path, date(2025, 9, 21))
            self.assertEqual(load_baseline(path), date(2025, 9, 21))

    def test_missing_earlier_coverage_is_explicit(self):
        status, msg = coverage_message(
            date(2025, 9, 21), datetime(2025, 11, 19), datetime(2026, 11, 19))
        self.assertEqual(status, "gap")
        self.assertIn("not loaded", msg)

    def test_september_statement_covers_baseline(self):
        status, _ = coverage_message(
            date(2025, 9, 21), datetime(2025, 9, 21), datetime(2026, 9, 21))
        self.assertEqual(status, "covered")

    def test_source_modules_parse(self):
        for filename in ["app_frontend.py", "app_backend.py", "bank_review_v1.py",
                         "statement_period_v1.py", "receipt_split_v1.py",
                         "tenancy_turnover_v1.py"]:
            with self.subTest(filename=filename):
                ast.parse(Path(filename).read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()