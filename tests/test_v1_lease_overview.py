"""Lease overview should respect occupancy independently from historical lease expiry."""
import unittest
import pandas as pd
from lease_overview_v1 import build_lease_overview


class LeaseOverviewTests(unittest.TestCase):
    def sample(self):
        return pd.DataFrame([
            {"Shop #": 1, "Tenant Name": "Active occupant with expired original term",
             "Lease Date": "2021-07-01", "Lease Status (Months)": 24,
             "Tenancy Record Status": "Current", "Lease End Date": None,
             "Lease Renewed (Yes/No)": "No"},
            {"Shop #": 2, "Tenant Name": "Former occupant",
             "Lease Date": "2024-01-01", "Lease Status (Months)": 48,
             "Tenancy Record Status": "Former", "Lease End Date": "2025-06-30",
             "Lease Renewed (Yes/No)": "No"},
            {"Shop #": 3, "Tenant Name": "Renewal flagged",
             "Lease Date": "2023-01-01", "Lease Status (Months)": 24,
             "Tenancy Record Status": "Current", "Lease End Date": None,
             "Lease Renewed (Yes/No)": "Yes"},
            {"Shop #": 4, "Tenant Name": "UNALLOCATED",
             "Lease Date": None, "Lease Status (Months)": None,
             "Tenancy Record Status": "Vacancy", "Lease End Date": None,
             "Lease Renewed (Yes/No)": None},
            {"Shop #": 5, "Tenant Name": "Former without departure date",
             "Lease Date": "2024-01-01", "Lease Status (Months)": 24,
             "Tenancy Record Status": "Former", "Lease End Date": None,
             "Lease Renewed (Yes/No)": "No"},
        ])

    def test_expired_original_term_does_not_terminate_current_tenancy(self):
        data = build_lease_overview(self.sample(), "2026-11-25")
        self.assertEqual(data.loc[0, "Occupancy_Status"], "Current")
        self.assertEqual(data.loc[0, "Original_Term_End_Estimate"], pd.Timestamp("2023-07-01"))
        self.assertIn("verify renewal", data.loc[0, "Contract_Review_Status"])

    def test_former_tenant_remains_former_even_if_original_term_future(self):
        data = build_lease_overview(self.sample(), "2025-01-01")
        self.assertEqual(data.loc[1, "Occupancy_Status"], "Former")

    def test_renewal_does_not_invent_new_contract_dates(self):
        data = build_lease_overview(self.sample(), "2026-11-25")
        self.assertEqual(data.loc[2, "Occupancy_Status"], "Current")
        self.assertIn("Renewal recorded", data.loc[2, "Contract_Review_Status"])

    def test_vacancy_is_not_active(self):
        data = build_lease_overview(self.sample(), "2026-11-25")
        self.assertEqual(data.loc[3, "Occupancy_Status"], "Vacant")

    def test_missing_former_departure_flags_review(self):
        data = build_lease_overview(self.sample(), "2026-11-25")
        self.assertIn("missing", data.loc[4, "Occupancy_Status"])

    def test_expired_alerts_only_include_current_occupants(self):
        from lease_overview_v1 import expired_current_leases
        data = build_lease_overview(self.sample(), "2026-11-25")
        alerts = expired_current_leases(data, "2026-11-25")
        self.assertEqual(set(alerts["Shop #"].tolist()), {1, 3})
        self.assertTrue((alerts["Days_Past_Original_Term"] > 0).all())

    def test_missing_duration_not_reported_as_expired(self):
        from lease_overview_v1 import expired_current_leases
        data = build_lease_overview(
            self.sample().drop(columns=["Lease Status (Months)"]), "2026-11-25")
        self.assertTrue(expired_current_leases(data, "2026-11-25").empty)

    def test_no_tenancy_history_is_not_assumed_active(self):
        data = build_lease_overview(self.sample().drop(
            columns=["Tenancy Record Status", "Lease End Date"]), "2026-11-25")
        self.assertTrue(data["Occupancy_Status"].str.contains("Unverified").all())

    def test_unknown_duration_is_not_defaulted_to_12_months(self):
        data = build_lease_overview(self.sample().drop(
            columns=["Lease Status (Months)"]), "2026-11-25")
        self.assertTrue(data["Original_Term_End_Estimate"].isna().all())

if __name__ == "__main__":
    unittest.main()
