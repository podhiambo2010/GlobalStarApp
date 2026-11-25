"""Review only: contractual identification discrepancies must never change the ledger."""
import unittest
import pandas as pd
from app_backend import TenantPortalBackend


class LeaseIdentityReviewTests(unittest.TestCase):
    def setUp(self):
        self.backend = TenantPortalBackend.__new__(TenantPortalBackend)
        self.backend.df_tenants = pd.DataFrame([
            {"Shop #": 19, "Tenant Name": "Aloice Ngolo Otieno", "Monthly Rate": 10000,
             "Tenancy Record Status": "Current"},
            {"Shop #": 21, "Tenant Name": "Hand in Hand Eastern Africa", "Monthly Rate": 16722.22,
             "Tenancy Record Status": "Current"},
        ])

    def test_aloice_without_lease_unit_does_not_infer_match(self):
        result = self.backend.verify_ocr_against_master({
            "Tenant Name": "Aloice Ngolo Otieno", "Shop #": None,
            "Monthly Rent (KSh)": 10000})
        self.assertFalse(result["Match Found"])
        self.assertIn("Unit 19", " ".join(result["Discrepancies"]))
        self.assertEqual(self.backend.df_tenants.loc[0, "Shop #"], 19)

    def test_hand_in_hand_amendment_pending_not_verified(self):
        result = self.backend.verify_ocr_against_master({
            "Tenant Name": "Hand In Hand Eastern Africa", "Shop #": 19,
            "Billing Cycle": "Quarterly", "Quarterly Base Rent (KSh)": 50166.67})
        self.assertFalse(result["Match Found"])
        self.assertEqual(result["Manual Status"], "Amendment awaiting countersignature")
        self.assertEqual(self.backend.df_tenants.loc[1, "Shop #"], 21)

    def test_ambiguous_name_not_approved(self):
        self.backend.df_tenants.loc[2] = [19, "Aloice Another", 3000, "Former"]
        result = self.backend.verify_ocr_against_master({
            "Tenant Name": "Aloice Ngolo Otieno", "Shop #": None})
        self.assertFalse(result["Match Found"])


if __name__ == "__main__":
    unittest.main()
