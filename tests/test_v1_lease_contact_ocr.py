"""Regression tests for conservative PDF lease field extraction."""
import unittest
from lease_field_parser import parse_lease_fields


class LeaseContactExtractionTests(unittest.TestCase):
    def test_tenant_contacts_with_line_evidence(self):
        text = """LANDLORD
Email: landlord@example.com
Telephone: +254 722 111 222
KRA PIN: P051548911H
TENANT
Email: accounts@tenant.co.ke
Telephone: +254 712 345 678
KRA PIN: P123456789X
Gross Quarterly Base Rent: KSh. 50,166.67
Value Added Tax (VAT at 16%): KSh. 8,026.67
Total Gross Quarterly Obligation: KSh. 58,193.34
"""
        fields = parse_lease_fields(text)
        self.assertEqual(fields["Email"], "accounts@tenant.co.ke")
        self.assertEqual(fields["Telephone No."], "+254712345678")
        self.assertEqual(fields["KRA PIN"], "P123456789X")
        self.assertIn("tenant.co.ke", fields["Field Evidence"]["Email"])
        self.assertEqual(fields["Quarterly Base Rent (KSh)"], 50166.67)
        self.assertIsNone(fields["Monthly Rent (KSh)"])

    def test_landlord_only_does_not_populate_tenant(self):
        text = """LANDLORD
Email: owner@example.com
Telephone: 0712 222 333
KRA PIN: P051548911H
"""
        result = parse_lease_fields(text)
        for field in ("Email", "Telephone No.", "KRA PIN"):
            self.assertIsNone(result[field])

    def test_unlabelled_identifiers_are_not_assumed(self):
        text = """Mail accounts@tenant.co.ke
Contacts 0712345678
P123456789X
"""
        result = parse_lease_fields(text)
        self.assertIsNone(result["Email"])
        self.assertIsNone(result["KRA PIN"])
        self.assertIsNone(result["Telephone No."])

    def test_conflicting_tenant_contacts_not_guessed(self):
        text = """TENANT
Email: first@example.com
Email: second@example.com
"""
        result = parse_lease_fields(text)
        self.assertIsNone(result["Email"])
        self.assertTrue(any("Conflicting tenant Email" in x for x in result["Parser Warnings"]))

    def test_no_filename_inference(self):
        result = parse_lease_fields("There is no tenant contact information in this lease.")
        self.assertIsNone(result["Email"])


if __name__ == "__main__":
    unittest.main()
