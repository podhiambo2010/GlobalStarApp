"""Tests that occupied units are not confused with current tenancy records."""
import unittest
import pandas as pd
from lease_overview_v1 import occupancy_audit, build_lease_overview


class OccupancyAuditTests(unittest.TestCase):
    def test_duplicate_current_records_do_not_double_count(self):
        rows = pd.DataFrame([
            {"Shop #": 19, "Tenant Name": "A", "Lease Date": "2026-01-01",
             "Tenancy Record Status": "Current", "Lease End Date": None},
            {"Shop #": 19, "Tenant Name": "B", "Lease Date": "2026-02-01",
             "Tenancy Record Status": "Current", "Lease End Date": None},
            {"Shop #": 21, "Tenant Name": "C", "Lease Date": "2026-06-01",
             "Tenancy Record Status": "Current", "Lease End Date": None},
        ])
        summary = occupancy_audit(build_lease_overview(rows, "2026-11-25"))
        self.assertEqual(summary["current_records"], 3)
        self.assertEqual(summary["unique_occupied_units"], 2)
        self.assertEqual(summary["uncontested_occupied_units"], 1)
        self.assertEqual(summary["conflicting_units"], 1)
        self.assertEqual(len(summary["issues"]), 2)

    def test_vacancy_conflict_not_counted_vacant(self):
        rows = pd.DataFrame([
            {"Shop #": 21, "Tenant Name": "Current", "Lease Date": "2026-06-01",
             "Tenancy Record Status": "Current", "Lease End Date": None},
            {"Shop #": 21, "Tenant Name": "UNALLOCATED", "Lease Date": None,
             "Tenancy Record Status": "Vacancy", "Lease End Date": None},
            {"Shop #": 22, "Tenant Name": "UNALLOCATED", "Lease Date": None,
             "Tenancy Record Status": "Vacancy", "Lease End Date": None}
        ])
        summary = occupancy_audit(build_lease_overview(rows, "2026-11-25"))
        self.assertEqual(summary["vacant_units"], 1)
        self.assertEqual(summary["conflicting_units"], 1)
        self.assertEqual(summary["uncontested_occupied_units"], 0)

    def test_future_record_not_occupied(self):
        rows = pd.DataFrame([
            {"Shop #": 12, "Tenant Name": "Future", "Lease Date": "2026-12-01",
             "Tenancy Record Status": "Current", "Lease End Date": None}
        ])
        summary = occupancy_audit(build_lease_overview(rows, "2026-11-25"))
        self.assertEqual(summary["unique_occupied_units"], 0)


if __name__ == "__main__":
    unittest.main()
