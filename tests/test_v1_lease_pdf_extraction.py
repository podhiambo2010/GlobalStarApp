"""Tests ensure PDF text extraction never fabricates tenancy facts."""
import io
import unittest
from unittest.mock import patch

import pandas as pd
from app_backend import LeaseDocumentAI, TenantPortalBackend


class _Page:
    def __init__(self, value):
        self.value = value
    def extract_text(self):
        return self.value


class _Reader:
    def __init__(self, value):
        self.pages = [_Page(value)]


class LeaseExtractionTests(unittest.TestCase):
    def test_unreadable_scan_does_not_invent_rent_deposit_tenant_or_date(self):
        with patch("app_backend.pypdf.PdfReader", return_value=_Reader("")):
            out = LeaseDocumentAI.parse_lease_pdf(io.BytesIO(b"test"))
        for key in ("Tenant Name", "Shop #", "Monthly Rent (KSh)",
                    "Security Deposit (KSh)", "Commencement", "Email", "Telephone No."):
            self.assertIsNone(out[key], key)
        self.assertTrue(out["Verification Required"])
        self.assertTrue(out["Extraction Warnings"])

    def test_labeled_fields_are_provisional_and_read_only(self):
        body = ("Tenant: Example Limited\nShop No: 14\nMonthly Rent: KSh 25000\n"
                "Security Deposit: KSh 75000\nCommencement Date: 2025-01-01\n"
                "This agreement concerns commercial premises.\n")
        with patch("app_backend.pypdf.PdfReader", return_value=_Reader(body)):
            out = LeaseDocumentAI.parse_lease_pdf(io.BytesIO(b"test"))
        self.assertEqual(out["Shop #"], 14)
        self.assertEqual(out["Monthly Rent (KSh)"], 25000)
        self.assertEqual(out["Security Deposit (KSh)"], 75000)
        self.assertEqual(out["Tenant Name"], "Example Limited")
        self.assertTrue(out["Verification Required"])

    def test_unreadable_document_does_not_claim_successful_ocr(self):
        with patch("app_backend.pypdf.PdfReader", return_value=_Reader("")):
            out = LeaseDocumentAI.parse_lease_pdf(io.BytesIO(b"not a real pdf"))
        self.assertIsNone(out["Tenant Name"])
        self.assertIsNone(out["Monthly Rent (KSh)"])
        self.assertTrue(out["Verification Required"])
        self.assertTrue(out["Extraction Warnings"])
        self.assertEqual(out["Extraction Method"], "PDF text layer")

    def test_missing_rent_does_not_crash_master_verification(self):
        obj = object.__new__(TenantPortalBackend)
        obj.df_tenants = pd.DataFrame([{
            "Shop #": 14, "Tenant Name": "Example Limited",
            "Monthly Rate": 25000, "Tenancy Record Status": "Current",
        }])
        out = obj.verify_ocr_against_master({
            "Shop #": 14, "Tenant Name": "Example Limited",
            "Monthly Rent (KSh)": None,
        })
        self.assertTrue(out["Match Found"])
        self.assertTrue(any("not extracted" in x for x in out["Discrepancies"]))

    def test_no_auto_match_by_shop_alone(self):
        obj = object.__new__(TenantPortalBackend)
        obj.df_tenants = pd.DataFrame([{"Shop #": 14, "Tenant Name": "Example Limited",
                                       "Monthly Rate": 25000}])
        out = obj.verify_ocr_against_master({
            "Shop #": 14, "Tenant Name": None, "Monthly Rent (KSh)": 25000})
        self.assertFalse(out["Match Found"])


if __name__ == "__main__":
    unittest.main()
