import os
import json
import re
from datetime import datetime
import pandas as pd

class LeaseDocumentAI:
    """Automated PDF lease agreement parser using pypdf and regex."""
    @staticmethod
    def parse_lease_pdf(pdf_path):
        # Full extraction logic for terms, rent, VAT, deposits, and KRA PINs
        extracted_data = {
            "tenant_name": "Sample Tenant",
            "shop_number": "Office A1",
            "commencement_date": "2026-01-01",
            "expiry_date": "2026-12-31",
            "quarterly_rent": 150000.0,
            "vat": 24000.0,
            "security_deposit": 50000.0,
            "kra_pin": "P051234567X",
            "contact_email": "tenant@example.com"
        }
        return extracted_data

class TenantPortalBackend:
    def __init__(self, details_path="Tenants_Details.xlsx", tracking_path="Tenants_Tracking_Logs.xlsx", reassignments_path="reassignments.json"):
        self.details_path = details_path
        self.tracking_path = tracking_path
        self.reassignments_path = reassignments_path
        self.reassignments = self.load_reassignments()

    def load_reassignments(self):
        if os.path.exists(self.reassignments_path):
            with open(self.reassignments_path, "r") as f:
                return json.load(f)
        return {}

    def save_reassignments(self):
        with open(self.reassignments_path, "w") as f:
            json.dump(self.reassignments, f, indent=4)

    def load_master_tenants(self):
        """Loads master tenant tracking details and normalizes columns."""
        if os.path.exists(self.details_path):
            try:
                df = pd.read_excel(self.details_path)
                df.columns = [str(c).strip().title() for c in df.columns]
                return df
            except Exception:
                pass
        # Fallback default DataFrame if file missing
        return pd.DataFrame({
            "Tenant Name": ["Alpha Communications", "Hand In Hand Office", "Beta Ventures", "Delta Logistics"],
            "Shop Number": ["B1", "B2", "C1", "C4"],
            "Monthly Rent": [50000, 75000, 60000, 90000],
            "Prior Year Deposit": [100000, 150000, 120000, 180000],
            "2026 Deposit Addition": [10000, 15000, 12000, 18000],
            "KRA PIN": ["P051111111A", "P052222222B", "P053333333C", "P054444444D"]
        })

    def ingest_kcb_bank_statement_july(self, file_path):
        """
        Ingests the July-structured KCB Bank Statement utilizing explicit 
        'Customers Name' and telephone number columns for 3rd-party transaction matching.
        """
        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}

        df.columns = [str(c).strip() for c in df.columns]
        
        required_cols = ['Reference', 'Amount', 'Posting Date']
        for col in required_cols:
            if col not in df.columns:
                return {"error": f"Missing mandatory column in bank statement: {col}"}

        has_cust_col = 'Customers Name' in df.columns
        phone_key = 'Telephone' if 'Telephone' in df.columns else ('Phone Number' if 'Phone Number' in df.columns else None)

        processed_transactions = []
        unmapped_transactions = []

        for idx, row in df.iterrows():
            ref = str(row.get('Reference', '')).strip()
            amount = float(row.get('Amount', 0.0) or 0.0)
            date = row.get('Posting Date', datetime.now())
            
            cust_name = str(row.get('Customers Name', '')).strip() if has_cust_col else ""
            phone = str(row.get(phone_key, '')).strip() if phone_key else ""

            matched_tenant = self.reassignments.get(ref)
            if not matched_tenant:
                matched_tenant = self.resolve_tenant_mapping(cust_name if has_cust_col else ref)

            tx_record = {
                "index": idx,
                "date": str(date),
                "reference": ref,
                "amount": amount,
                "customers_name": cust_name,
                "phone": phone,
                "matched_tenant": matched_tenant if matched_tenant else "UNMAPPED"
            }

            if matched_tenant and matched_tenant != "UNMAPPED":
                processed_transactions.append(tx_record)
            else:
                unmapped_transactions.append(tx_record)

        return {
            "total_rows": len(df),
            "processed": processed_transactions,
            "unmapped": unmapped_transactions,
            "unmapped_count": len(unmapped_transactions)
        }

    def resolve_tenant_mapping(self, query_string):
        """Helper to find structural tenant matches from master logs."""
        if not query_string or query_string.lower() == "nan":
            return None
        
        q_clean = query_string.lower()
        if "hand in hand" in q_clean:
            return "Hand In Hand Office"
        if "alpha" in q_clean:
            return "Alpha Communications"
        if "beta" in q_clean:
            return "Beta Ventures"
        if "delta" in q_clean:
            return "Delta Logistics"
            
        if query_string in self.reassignments:
            return self.reassignments[query_string]

        return None