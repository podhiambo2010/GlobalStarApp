"""Stage 1H regression tests — no bank or rent mutation."""
import json
import tempfile
import unittest
from pathlib import Path

from cheque_clearance_v1h import record_clearance, latest_reviews


def sample():
    later = {
        "source_row": 53, "bank_row_id": "rebanked-credit-53",
        "date": "2025-11-11", "amount_ksh": "30000.00",
        "reference": "FT25315DRWFX",
    }
    pair = {
        "cheque_number": "4680", "transaction_date": "2025-11-10",
        "amount_ksh": "30000.00", "credit_row_id": "original-46",
        "debit_row_id": "return-51",
        "later_credit_candidates": [later],
    }
    return pair, later


class ChequeClearanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "clearance.json"
        self.pair, self.later = sample()

    def save(self, **kw):
        args = dict(
            tenancy_id="unit-5-dreamline", tenant_name="Dreamline Express",
            status="bank_cleared_pending_allocation",
            reviewer="Bank Manager", explanation="Verified posted 11 Nov on statement.",
            verified_bank_posting=True, checked_no_later_reversal=True,
        )
        args.update(kw)
        return record_clearance(self.path, self.pair, self.later, **args)

    def test_clearance_only_registers_evidence(self):
        event = self.save()
        self.assertFalse(event["rent_posted"])
        self.assertFalse(event["allocation_approved"])
        self.assertEqual(latest_reviews(self.path)["original-46"]["status"],
                         "bank_cleared_pending_allocation")
        self.assertEqual(len(json.loads(self.path.read_text())["history"]), 1)

    def test_evidence_checks_required(self):
        with self.assertRaises(ValueError):
            self.save(verified_bank_posting=False)
        with self.assertRaises(ValueError):
            self.save(checked_no_later_reversal=False)
        self.assertFalse(self.path.exists())

    def test_wrong_credit_blocked(self):
        wrong = dict(self.later, bank_row_id="another-bank-row")
        with self.assertRaises(ValueError):
            record_clearance(
                self.path, self.pair, wrong, tenancy_id="x",
                tenant_name="Dreamline", status="needs_investigation",
                reviewer="Manager", explanation="Review pending further evidence",
                verified_bank_posting=False, checked_no_later_reversal=False
            )

    def test_multiple_candidates_cannot_confirm(self):
        pair = dict(self.pair)
        pair["later_credit_candidates"] = [self.later, dict(self.later)]
        with self.assertRaises(ValueError):
            record_clearance(
                self.path, pair, self.later, tenancy_id="x",
                tenant_name="Dreamline", status="needs_investigation",
                reviewer="Manager", explanation="Review pending further evidence",
                verified_bank_posting=False, checked_no_later_reversal=False
            )

    def test_new_review_preserves_previous(self):
        first = self.save(status="needs_investigation",
                          verified_bank_posting=False, checked_no_later_reversal=False)
        second = self.save(explanation="Verified posted credit and checked reversals.")
        history = json.loads(self.path.read_text())["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["status"], "needs_investigation")
        self.assertEqual(history[1]["status"], "bank_cleared_pending_allocation")

    def test_conflicting_tenancy_rejected(self):
        self.save()
        with self.assertRaises(ValueError):
            self.save(tenancy_id="different-tenant")

    def test_corrupt_register_never_overwritten(self):
        self.path.write_text("{corrupted")
        with self.assertRaises(json.JSONDecodeError):
            self.save()
        self.assertEqual(self.path.read_text(), "{corrupted")


if __name__ == "__main__":
    unittest.main()
