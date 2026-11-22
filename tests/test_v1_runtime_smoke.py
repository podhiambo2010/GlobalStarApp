"""Synthetic Excel smoke test for published V1; no Supabase connections."""
import os
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from app_backend import TenantPortalBackend


class ExcelOnlyRuntimeSmoke(unittest.TestCase):
    def test_parses_bank_movements_and_tenant_without_database(self):
        with tempfile.TemporaryDirectory() as temp:
            tenant_path = Path(temp) / "Tenants_Details.xlsx"
            bank_path = Path(temp) / "KCB_Bank_Statement.xlsx"
            tenant = pd.DataFrame([{
                "Shop / Unit #": 1,
                "Tenant Name": "Example Tenant",
                "Monthly Rate": 25000,
                "Deposit (KSh)": 0,
                "Lease Date": "2025-09-01",
                "Telephone No.": "0700000000",
                "Email Address": "example.invalid",
                "Lease Renewed (Yes/No)": "NO",
            }])
            tenant.to_excel(tenant_path, sheet_name="Sheet1", index=False)
            movements = pd.DataFrame([
                ["01.10.2025", "01.10.2025", "Rent for Example Tenant", 0, 25000, 25000, "RENT-1"],
                ["02.10.2025", "02.10.2025", "Bank transfer", -30000, 0, -5000, "SAME-REF"],
                ["02.10.2025", "02.10.2025", "Transfer charge", -76.25, 0, -5076.25, "SAME-REF"],
            ], columns=[
                "Transaction Date", "Value Date", "Transaction Details",
                "Money Out", "Money In", "Ledger Balance", "Bank Reference Number"
            ])
            with pd.ExcelWriter(bank_path, engine="openpyxl") as writer:
                pd.DataFrame([{
                    "A": "Period: 01/10/2025 - 31/10/2025",
                    "B": "",
                }]).to_excel(writer, sheet_name="Bank Statement", index=False, startrow=0)
                movements.to_excel(writer, sheet_name="Bank Statement", index=False, startrow=14)
            backend = TenantPortalBackend(str(tenant_path), str(bank_path),
                override_json_path=str(Path(temp)/"assignments.json"),
                ignored_json_path=str(Path(temp)/"ignored.json"))
            self.assertEqual(len(backend.df_tenants), 1)
            self.assertEqual(len(backend.df_bank), 3)
            self.assertEqual(int((backend.df_bank["Money In Num"] > 0).sum()), 1)
            self.assertEqual(int((backend.df_bank["Money Out Num"] < 0).sum()), 2)
            self.assertEqual(int((backend.df_bank["Ref_Clean"]=="SAME-REF").sum()), 2)
            self.assertFalse(hasattr(backend, "supabase"), "Excel-only V1 must not initialize Supabase")


if __name__ == "__main__":
    unittest.main()
