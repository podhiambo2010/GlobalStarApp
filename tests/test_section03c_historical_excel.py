"""Section 03C archived KCB Excel import and historical tenancy context tests."""
from io import BytesIO
import unittest

import pandas as pd

from historical_kcb_excel_v1_section03c import load_historical_kcb_xlsx
from migration_identity_recovery_v1_section03c import historical_tenancy_context


def workbook(rows):
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame([
            ["KCB BANK STATEMENT", None, None, None, None, None],
            ["Transaction Date", "Value Date", "Bank Reference Number",
             "Transaction Details", "Money In", "Money Out"],
            *rows,
        ]).to_excel(writer, sheet_name="Bank Statement", index=False, header=False)
    return stream.getvalue()


class ArchivedKCBExcelTests(unittest.TestCase):
    def test_preamble_and_headers_are_normalized_read_only(self):
        source = workbook([["2025-11-10", "2025-11-10", "FT-A", "Cheque deposit", 60000, 0],
                           ["2025-11-11", "2025-11-11", "FT-B", "Return", 0, 60000]])
        parsed, sheet = load_historical_kcb_xlsx(source)
        self.assertEqual(sheet, "Bank Statement")
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed["Money In Num"].tolist(), [60000, 0])
        self.assertTrue(all(":" in value for value in parsed["Bank_Row_ID"]))
        self.assertEqual(source, source[:])

    def test_refuses_missing_bank_fields(self):
        s = BytesIO()
        with pd.ExcelWriter(s, engine="openpyxl") as writer:
            pd.DataFrame({"Tenant Name": ["Alice"], "Rent": [20000]}).to_excel(
                writer, index=False)
        with self.assertRaises(ValueError):
            load_historical_kcb_xlsx(s.getvalue())

    def test_rejects_malformed_amount(self):
        source = workbook([["2025-11-10", "2025-11-10", "FT-A", "Deposit", "not-money", 0]])
        with self.assertRaises(ValueError):
            load_historical_kcb_xlsx(source)

    def test_same_unit_cannot_confirm_prior_tenant(self):
        plan = {"mode": "DRY_RUN_ONLY_NO_DB_WRITES", "schema": "gs_streamlit_v1",
                "tenancies": [{"tenancy_id": "1:new", "unit_code": "1",
                               "tenant_name": "Current tenant", "tenancy_status": "current"}]}
        full = {"mode": "SECTION_03B_FULL_SOURCE_DIAGNOSTIC_NO_WRITES",
                "stale_tenancy_evidence": [{"bank_row_id": "row7", "historical_tenancy_id": "1:old"}]}
        context = historical_tenancy_context(plan, full)
        self.assertEqual(len(context), 1)
        self.assertFalse(context[0]["historical_tenancy_confirmed"])
        self.assertFalse(context[0]["current_tenant_reassigned"])
        self.assertEqual(context[0]["current_tenancy_candidates_same_unit"][0]["tenancy_id"], "1:new")


if __name__ == "__main__":
    unittest.main()
