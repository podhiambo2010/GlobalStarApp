"""Stage 1I controls: independent allocation audit; no automatic rent posting."""
import json
import tempfile
import unittest
from pathlib import Path

from cheque_clearance_v1h import record_clearance
from cheque_allocation_v1i import record_allocation, latest_allocations


class ClearedChequeAllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.clearance = root / "v1h.json"
        self.allocation = root / "v1i.json"
        self.later = {
            "bank_row_id": "later-credit-53", "date": "2025-11-11",
            "amount_ksh": "30000.00", "reference": "FT25315DRWFX",
        }
        self.pair = {
            "cheque_number": "4680", "transaction_date": "2025-11-10",
            "amount_ksh": "30000.00", "credit_row_id": "first-46",
            "debit_row_id": "reversed-51",
            "later_credit_candidates": [self.later],
        }
        record_clearance(
            self.clearance, self.pair, self.later,
            tenancy_id="dreamline-lease", tenant_name="Dreamline Express",
            status="bank_cleared_pending_allocation",
            reviewer="Bank Manager",
            explanation="Verified later bank credit and no later reversal",
            verified_bank_posting=True, checked_no_later_reversal=True,
        )

    def allocate(self, **changes):
        args = dict(
            successful_credit_row_id="later-credit-53",
            tenancy_id="dreamline-lease", rent_period="2025-11-01",
            amount_ksh="30000.00", reviewer="Bank Manager",
            explanation="Verified November rent against lease and bank evidence",
            verified_period=True, verified_amount=True, confirmed=True,
        )
        args.update(changes)
        return record_allocation(self.allocation, self.clearance, **args)

    def test_approved_review_is_not_rent_posting(self):
        event = self.allocate()
        self.assertEqual(event["status"], "allocation_approved_ledger_pending")
        self.assertFalse(event["rent_posted"])
        self.assertEqual(event["successful_credit_row_id"], "later-credit-53")
        self.assertEqual(event["original_credit_row_id"], "first-46")
        self.assertEqual(event["returned_debit_row_id"], "reversed-51")
        self.assertEqual(len(json.loads(self.allocation.read_text())["history"]), 1)
        self.assertEqual(len(json.loads(self.clearance.read_text())["history"]), 1)

    def test_same_credit_cannot_allocate_twice(self):
        self.allocate()
        with self.assertRaises(ValueError):
            self.allocate(rent_period="2025-12-01")
        self.assertEqual(len(json.loads(self.allocation.read_text())["history"]), 1)

    def test_cannot_allocate_to_different_tenancy(self):
        with self.assertRaises(ValueError):
            self.allocate(tenancy_id="unrelated-lease")

    def test_cannot_allocate_wrong_or_partial_amount(self):
        for amount in ("15000.00", "60000.00", "0.00", "-10.00"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.allocate(amount_ksh=amount)
        self.assertFalse(self.allocation.exists())

    def test_period_and_approval_checks(self):
        for changed in (
            {"rent_period": "2025-11-10"},
            {"verified_period": False},
            {"verified_amount": False},
            {"confirmed": False},
            {"explanation": "short"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.allocate(**changed)

    def test_amendment_preserves_audit_history(self):
        first = self.allocate()
        second = self.allocate(
            rent_period="2025-12-01", amend=True,
            correction_reason="Lease evidence confirms December rather than November",
        )
        history = json.loads(self.allocation.read_text())["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["rent_period"], "2025-11-01")
        self.assertEqual(history[1]["rent_period"], "2025-12-01")
        self.assertEqual(second["prior_recorded_at_utc"], first["recorded_at_utc"])
        self.assertEqual(latest_allocations(self.allocation)["later-credit-53"], second)

    def test_amendment_cannot_be_unchanged_or_unexplained(self):
        self.allocate()
        with self.assertRaises(ValueError):
            self.allocate(amend=True, correction_reason="We checked the record and corrected the period")
        with self.assertRaises(ValueError):
            self.allocate(rent_period="2025-12-01", amend=True, correction_reason="Too brief")

    def test_bad_register_never_overwritten(self):
        self.allocation.write_text("{broken", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            self.allocate()
        self.assertEqual(self.allocation.read_text(), "{broken")

    def test_stage_1h_reversal_blocks_new_allocation(self):
        record_clearance(
            self.clearance, self.pair, self.later,
            tenancy_id="dreamline-lease", tenant_name="Dreamline Express",
            status="not_cleared", reviewer="Bank Manager",
            explanation="Later credit was reversed in new evidence",
            verified_bank_posting=False, checked_no_later_reversal=False,
        )
        with self.assertRaises(ValueError):
            self.allocate()


    def test_quarterly_cheque_allocates_once_to_three_months(self):
        # Isolate new cheque from Dreamline to verify the quarter independently.
        second = dict(self.later, bank_row_id="later-mash-52", amount_ksh="60000.00",
                      reference="FT25315X5FFZ")
        pair = dict(self.pair, cheque_number="4525", amount_ksh="60000.00",
                    credit_row_id="mash-original-47", debit_row_id="mash-return-50",
                    later_credit_candidates=[second])
        record_clearance(
            self.clearance, pair, second,
            tenancy_id="mash-unit-3", tenant_name="Mash East Africa",
            status="bank_cleared_pending_allocation", reviewer="Bank Manager",
            explanation="Verified Mash successful later credit without reversal",
            verified_bank_posting=True, checked_no_later_reversal=True,
        )
        periods = [
            {"rent_period": "2025-11-01", "amount_ksh": "20000.00"},
            {"rent_period": "2025-12-01", "amount_ksh": "20000.00"},
            {"rent_period": "2026-01-01", "amount_ksh": "20000.00"},
        ]
        kwargs = dict(
            successful_credit_row_id="later-mash-52", tenancy_id="mash-unit-3",
            rent_period="2025-11-01", amount_ksh="60000.00",
            allocations=periods, reviewer="Bank Manager",
            explanation="Quarterly rent for Nov Dec and Jan confirmed by owner",
            verified_period=True, verified_amount=True, confirmed=True,
        )
        event = record_allocation(self.allocation, self.clearance, **kwargs)
        self.assertEqual(event["allocations"], periods)
        self.assertFalse(event["rent_posted"])
        self.assertEqual(len(latest_allocations(self.allocation)), 1)
        with self.assertRaises(ValueError):
            record_allocation(self.allocation, self.clearance, **kwargs)
        self.assertEqual(len(json.loads(self.allocation.read_text())["history"]), 1)
        self.assertEqual(len(json.loads(self.clearance.read_text())["history"]), 2)

    def test_quarterly_mismatch_rejected(self):
        second = dict(self.later, bank_row_id="later-mash-52", amount_ksh="60000.00")
        pair = dict(self.pair, cheque_number="4525", amount_ksh="60000.00",
                    credit_row_id="mash-original-47", debit_row_id="mash-return-50",
                    later_credit_candidates=[second])
        record_clearance(
            self.clearance, pair, second,
            tenancy_id="mash-unit-3", tenant_name="Mash East Africa",
            status="bank_cleared_pending_allocation", reviewer="Bank Manager",
            explanation="Verified Mash successful later credit without reversal",
            verified_bank_posting=True, checked_no_later_reversal=True,
        )
        baseline = dict(
            successful_credit_row_id="later-mash-52", tenancy_id="mash-unit-3",
            rent_period="2025-11-01", amount_ksh="60000.00",
            reviewer="Bank Manager",
            explanation="Quarterly rent confirmed by the owner and lease evidence",
            verified_period=True, verified_amount=True, confirmed=True,
        )
        invalids = [
            [{"rent_period": "2025-11-01", "amount_ksh": "60000.00"}],
            [{"rent_period": "2025-11-01", "amount_ksh": "20000.00"},
             {"rent_period": "2025-12-01", "amount_ksh": "20000.00"},
             {"rent_period": "2026-01-01", "amount_ksh": "19000.00"}],
            [{"rent_period": "2025-11-01", "amount_ksh": "20000.00"},
             {"rent_period": "2025-11-01", "amount_ksh": "20000.00"},
             {"rent_period": "2026-01-01", "amount_ksh": "20000.00"}],
        ]
        for parts in invalids:
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                record_allocation(self.allocation, self.clearance,
                                  allocations=parts, **baseline)
        self.assertFalse(self.allocation.exists())



if __name__ == "__main__":
    unittest.main()
