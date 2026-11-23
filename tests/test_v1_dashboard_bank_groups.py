"""Regression tests for read-only V1 dashboard bank status presentation."""
import unittest

import pandas as pd
from dashboard_bank_groups_v1 import GROUPS, group_bank_credits


class BankDashboardGroupingTests(unittest.TestCase):
    def rows(self):
        statuses = [
            "Review required", "Pending (reviewed)",
            "Legacy decision: reverify", "Stale tenancy assignment: reverify",
            "Identified (verify before notice)",
            "Identified (legacy override, verify tenancy)",
            "Assigned (reviewed)", "Split (reviewed)",
            "Excluded (reviewed)", "Excluded (legacy)",
        ]
        return pd.DataFrame([
            {"Bank_Row_ID": f"unique-row-{i}", "Allocation_Status": status,
             "Ref_Clean": "SHARED-REFERENCE", "Money In Num": 10000}
            for i, status in enumerate(statuses)
        ])

    def test_every_classification_is_accounted_for_once(self):
        original = self.rows()
        before = original.copy(deep=True)
        groups = group_bank_credits(original)
        combined_ids = [
            rid for records in groups.values()
            for rid in records["Bank_Row_ID"].tolist()
        ]
        self.assertEqual(len(combined_ids), len(original))
        self.assertEqual(len(set(combined_ids)), len(original))
        self.assertEqual(len(groups["Needs manual review"]), 4)
        self.assertEqual(len(groups["Automatically identified — not approved"]), 2)
        self.assertEqual(len(groups["Approved tenancy allocations"]), 1)
        self.assertEqual(len(groups["Split deposits / advance rent"]), 1)
        self.assertEqual(len(groups["Excluded transactions"]), 2)
        pd.testing.assert_frame_equal(original, before)

    def test_shared_reference_is_not_deduplicated(self):
        groups = group_bank_credits(self.rows())
        self.assertEqual(sum(len(group) for group in groups.values()), 10)

    def test_unknown_status_is_not_hidden(self):
        rows = self.rows()
        rows.loc[0, "Allocation_Status"] = "Future / unsupported"
        with self.assertRaises(ValueError):
            group_bank_credits(rows)

    def test_repeated_bank_id_is_not_silently_merged(self):
        rows = self.rows()
        rows.loc[1, "Bank_Row_ID"] = rows.loc[0, "Bank_Row_ID"]
        with self.assertRaises(ValueError):
            group_bank_credits(rows)

    def test_empty_view_preserves_all_five_sections(self):
        empty = pd.DataFrame(columns=["Bank_Row_ID", "Allocation_Status"])
        groups = group_bank_credits(empty)
        self.assertEqual(list(groups), list(GROUPS))
        self.assertTrue(all(item.empty for item in groups.values()))


if __name__ == "__main__":
    unittest.main()
