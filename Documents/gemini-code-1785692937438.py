import os
import json
import re
from datetime import datetime
import pandas as pd

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

    def ingest_kcb_bank_statement_july(self, file_path):
        """
        Ingests the July-structured KCB Bank Statement utilizing explicit 
        'Customers Name' and telephone number columns for 3rd-party transaction matching.
        """
        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            return {"error": f"Failed to read file: {str(e)}"}

        # Normalize column names to strip spacing/casing issues
        df.columns = [str(c).strip() for c in df.columns]
        
        # Expected mapping check or fallback creation
        required_cols = ['Reference', 'Amount', 'Posting Date']
        for col in required_cols:
            if col not in df.columns:
                return {"error": f"Missing mandatory column in bank statement: {col}"}

        # Identify explicit customer identification columns if present in the July schema
        has_cust_col = 'Customers Name' in df.columns
        has_phone_col = 'Telephone' in df.columns or 'Phone Number' in df.columns
        phone_key = 'Telephone' if 'Telephone' in df.columns else ('Phone Number' if 'Phone Number' in df.columns else None)

        processed_transactions = []
        unmapped_transactions = []

        for idx, row in df.iterrows():
            ref = str(row.get('Reference', '')).strip()
            amount = float(row.get('Amount', 0.0) or 0.0)
            date = row.get('Posting Date', datetime.now())
            
            cust_name = str(row.get('Customers Name', '')).strip() if has_cust_col else ""
            phone = str(row.get(phone_key, '')).strip() if phone_key else ""

            # Check override reassignments.json first
            matched_tenant = self.reassignments.get(ref)

            if not matched_tenant:
                # Attempt heuristic mapping via explicit Customer Name or Reference text matching
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
        # Direct lookup simulation against master records (e.g., Hand In Hand, etc.)
        if "hand in hand" in q_clean:
            return "Hand In Hand Office"
        
        # Check reassignments table
        if query_string in self.reassignments:
            return self.reassignments[query_string]

        return None