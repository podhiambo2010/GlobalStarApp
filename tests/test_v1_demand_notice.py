"""Smoke tests for the Excel-only Demand Notice Builder PDF."""
import io
from datetime import date, timedelta
import unittest

from pypdf import PdfReader
from demand_notice_v1 import render_draft_demand_notice


class DraftDemandNoticeSmoke(unittest.TestCase):
    def test_draft_pdf_is_created_locally(self):
        payload = render_draft_demand_notice(
            tenant_name="Example Tenant", unit="12",
            outstanding=12500.0, as_of=date(2026, 11, 22),
            response_by=date(2026, 12, 6),
            account_period="November 2026"
        )
        self.assertTrue(payload.startswith(b"%PDF"))
        content = "\n".join(page.extract_text() or ""
                            for page in PdfReader(io.BytesIO(payload)).pages)
        self.assertIn("DRAFT", content)
        self.assertIn("Example Tenant", content)
        self.assertIn("12,500.00", content)
        self.assertIn("November 2026", content)

    def test_declines_invalid_amount_and_deadline(self):
        common = dict(
            tenant_name="Test Tenant", unit="2",
            outstanding=1000, as_of=date(2026, 11, 22),
            response_by=date(2026, 11, 23),
            account_period="November 2026"
        )
        with self.assertRaises(ValueError):
            render_draft_demand_notice(**{**common, "outstanding": -5})
        with self.assertRaises(ValueError):
            render_draft_demand_notice(**{**common, "response_by": date(2026, 11, 21)})

if __name__=="__main__":
    unittest.main()
