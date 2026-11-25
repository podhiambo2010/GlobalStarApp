"""Regression tests for clause parsing; run: python -m unittest tests.test_v1_lease_field_parser -v"""
import unittest
from lease_field_parser import parse_lease_fields


class LeaseFieldParsingTests(unittest.TestCase):
    def test_monthly_scanned_style(self):
        source = """TENANT NAME: ALOICE NGOLO OTIENO
3. TERM OF TENANCY This tenancy shall commence on 6/6/2026
4. RENT VAT eTIMS The Tenant shall pay monthly rent of KES 10,000 PER MONTH
5. SECURITY DEPOSIT Before occupation, the Tenant shall pay a security deposit equivalent to Three (3) months' rent."""
        got = parse_lease_fields(source)
        self.assertEqual(got["Monthly Rent (KSh)"], 10000)
        self.assertEqual(got["Security Deposit (KSh)"], 30000)
        self.assertEqual(got["Commencement"], "2026-06-06")
        self.assertEqual(got["Billing Cycle"], "Monthly")
        self.assertIsNone(got["Shop #"])

    def test_quarterly_signed_style(self):
        source = """BETWEEN GLOBAL STAR INVESTMENTS LIMITED AND
HAND IN HAND EASTERN AFRICA, P.O. Box 8562
OFFICE NO. 19, located on the First Floor
Fixed Duration: This Lease shall be for a fixed term of Two (2) Years,
commencing on the 1st day of June 2026 and expiring on the 31st day of May 2028
Gross Quarterly Base Rent: KSh. 50,166.67 per quarter.
Value Added Tax (VAT at 16%): KSh. 8,026.67 per quarter.
Total Gross Quarterly Obligation: KSh. 58,193.34 per quarter.
The Total Gross Quarterly Rent Payable shall be paid quarterly in advance.
4.2 Security Deposit Alignment: Upon execution of this Agreement, the Tenant shall pay a refundable security deposit of exactly KSh. 50,166.67"""
        got = parse_lease_fields(source)
        self.assertEqual(got["Shop #"], 19)
        self.assertEqual(got["Commencement"], "2026-06-01")
        self.assertEqual(got["Lease End Date"], "2028-05-31")
        self.assertEqual(got["Quarterly Base Rent (KSh)"], 50166.67)
        self.assertEqual(got["Quarterly VAT (KSh)"], 8026.67)
        self.assertEqual(got["Quarterly Gross Rent (KSh)"], 58193.34)
        self.assertEqual(got["Security Deposit (KSh)"], 50166.67)
        self.assertEqual(got["Billing Cycle"], "Quarterly")
        self.assertIsNone(got["Monthly Rent (KSh)"])

    def test_no_invented_values(self):
        got = parse_lease_fields("A scanned document with no readable financial terms")
        self.assertIsNone(got["Monthly Rent (KSh)"])
        self.assertIsNone(got["Security Deposit (KSh)"])
        self.assertIsNone(got["Commencement"])
        self.assertIsNone(got["Tenant Name"])


if __name__ == "__main__":
    unittest.main()
