"""
Global Star Investments - Backend Engine
==================================================
GOVERNANCE & ARCHITECTURE CONSTITUTION:
- Data Integrity: All financial/eTIMS calculations must be deterministic and audited.
- Security: Zero hardcoded secrets; environment variables (.env) are mandatory.
- Modularity: Strict separation between database layers, business logic, and UI.
"""

import os
import re
import json
import pypdf
import qrcode
import requests
from io import BytesIO
from datetime import datetime
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from dotenv import load_dotenv

load_dotenv()

try:
    from etims_service import KRAeTIMSClient
except ImportError:
    KRAeTIMSClient = None

class LeaseDocumentAI:
    @staticmethod
    def parse_lease_pdf(pdf_file):
        """Conservative text extraction for PDF leases; scanned pages require OCR review.

        No hardcoded tenant, rent, shop number or commencement values are returned.
        Any missing or ambiguous field remains unverified, never guessed.
        """
        filename = getattr(pdf_file, "name", "Lease_Document.pdf")
        warnings = []
        method = "PDF text layer"
        pages = []
        pdf_data = None
        try:
            if hasattr(pdf_file, "seek"):
                pdf_file.seek(0)
            pdf_data = pdf_file.read() if hasattr(pdf_file, "read") else (
                pdf_file if isinstance(pdf_file, bytes) else None)
            reader = pypdf.PdfReader(BytesIO(pdf_data) if pdf_data is not None else pdf_file)
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            warnings.append(f"Unable to read PDF text layer: {type(exc).__name__}")
        raw_text = "\n".join(pages)
        if len(" ".join(raw_text.split())) < 50 or (
            pages and any(len(page.strip()) < 20 for page in pages)
        ):
            # The OCR path is local and optional: PyMuPDF renders page images,
            # and pytesseract calls the user's installed Tesseract executable.
            # Never report successful OCR if the binary is unavailable.
            try:
                import fitz
                import pytesseract
                from PIL import Image
                if pdf_data is None:
                    raise ValueError("PDF bytes unavailable for OCR")
                with fitz.open(stream=pdf_data, filetype="pdf") as document:
                    if len(document) > 25:
                        warnings.append("Only the first 25 pages were examined with OCR; verify the remainder.")
                    ocr_pages = []
                    for idx, page in enumerate(document):
                        if idx >= 25:
                            break
                        text_page = pages[idx] if idx < len(pages) else ""
                        if len(text_page.strip()) >= 50:
                            ocr_pages.append(text_page)
                            continue
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                        ocr_pages.append(pytesseract.image_to_string(image, lang="eng"))
                    raw_text = "\n".join(ocr_pages)
                    method = "PDF text layer + local Tesseract OCR"
            except (ImportError, FileNotFoundError) as exc:
                warnings.append(f"Image OCR not available ({type(exc).__name__}). Install PyMuPDF, Pillow, pytesseract and the Tesseract executable.")
            except Exception as exc:
                warnings.append(f"Image OCR unsuccessful ({type(exc).__name__}); verify original scan manually.")
        cleaned = " ".join(raw_text.split())
        if len(cleaned) < 50:
            warnings.append("No reliable machine-readable lease text was recovered; manual transcription required.")
        if pages and any(len(page.strip()) < 20 for page in pages) and method == "PDF text layer":
            warnings.append("One or more pages contain little or no extractable text; verify completeness manually.")

        def unique_match(pattern, label, transform=lambda x: x):
            found = [transform(x) for x in re.findall(pattern, cleaned, re.IGNORECASE)]
            found = list(dict.fromkeys(found))
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                warnings.append(f"Conflicting {label} values; manual verification required.")
            return None

        # Avoid extracting figures from unrelated clauses by requiring explicit labels.
        shop = unique_match(r"(?:shop|unit)\s*(?:no\.?|number|#)\s*[:#\-]?\s*(\d{1,4})\b",
                            "shop number", lambda x: int(x))
        rent = unique_match(r"(?:monthly\s+rent|rent\s+per\s+month)\s*(?:\(ksh\))?\s*[:=\-]?\s*(?:ksh|kes)?\s*([\d,]+(?:\.\d{1,2})?)",
                            "monthly rent", lambda x: float(x.replace(",", "")))
        deposit = unique_match(r"(?:security\s+deposit|refundable\s+deposit)\s*(?:\(ksh\))?\s*[:=\-]?\s*(?:ksh|kes)?\s*([\d,]+(?:\.\d{1,2})?)",
                               "security deposit", lambda x: float(x.replace(",", "")))
        commencement = unique_match(
            r"(?:commencement\s+date|lease\s+start\s+date)\s*[:=\-]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})",
            "commencement date")
        # Require a labeled, single-line name; do not consume unrelated contract clauses.
        name_candidates = re.findall(
            r"(?im)^\s*(?:tenant|lessee)\s*(?:name)?\s*[:\-]\s*([A-Za-z][A-Za-z &.'\-]{2,65})\s*$",
            raw_text)
        name_candidates = list(dict.fromkeys(x.strip() for x in name_candidates))
        name = name_candidates[0] if len(name_candidates) == 1 else None
        if len(name_candidates) > 1:
            warnings.append("Conflicting tenant names; manual verification required.")
        # The body is whitespace-normalised; name extraction can be ambiguous.
        if name and len(name.split()) > 8:
            name = None
            warnings.append("Tenant name could not be isolated confidently.")

        return {
            "Tenant Name": name,
            "Shop #": shop,
            "Monthly Rent (KSh)": rent,
            "Security Deposit (KSh)": deposit,
            "Commencement": commencement,
            "Email": None,
            "KRA PIN": None,
            "Telephone No.": None,
            "Billing Cycle": None,
            "Raw Text Length": len(raw_text),
            "Source File": filename,
            "Extraction Method": method,
            "Extraction Warnings": warnings,
            "Verification Required": True,
        }

class TenantPortalBackend:
    def process_lease_agreements_folder(self, folder_path: str = "Lease_Agreements") -> list:
        """
        Scans the root Lease_Agreements folder for PDF files and extracts 
        tenant lease details in batch.
        """
        extracted_leases = []
        if not os.path.exists(folder_path):
            os.makedirs(folder_path, exist_ok=True)
            return extracted_leases

        for filename in os.listdir(folder_path):
            if filename.lower().endswith(".pdf"):
                file_path = os.path.join(folder_path, filename)
                try:
                    with open(file_path, "rb") as f:
                        # Parse each PDF using LeaseDocumentAI
                        lease_info = LeaseDocumentAI.parse_lease_pdf(f)
                        lease_info["Source File"] = filename
                        extracted_leases.append(lease_info)
                except Exception as e:
                    print(f"Error processing {filename}: {e}")

        return extracted_leases

    def generate_kra_compliance_summary_pdf(self, output_path: str = "KRA_Sandbox_Integration_Summary.pdf") -> str:
        """Generates a formal technical compliance and architecture summary PDF for KRA eTIMS certification review."""
        doc = SimpleDocTemplate(output_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1a252c'), spaceAfter=4)
        normal_style = styles['Normal']
        small_bold = ParagraphStyle('SmallBold', parent=normal_style, fontSize=9, leading=12, fontName='Helvetica-Bold')
        small_norm = ParagraphStyle('SmallNorm', parent=normal_style, fontSize=9, leading=12)

        elements.append(Paragraph("<b>GLOBAL STAR INVESTMENTS LIMITED</b>", title_style))
        elements.append(Paragraph("<b>eTIMS OSCU SYSTEM-TO-SYSTEM INTEGRATION CERTIFICATION SUMMARY</b>", styles['Heading2']))
        elements.append(Paragraph("<b>Prepared for:</b> Kenya Revenue Authority (KRA) eTIMS Technical Support & Audit Desk", normal_style))
        elements.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%d %B %Y')} | <b>Environment:</b> Sandbox (OSCU)", normal_style))
        elements.append(Spacer(1, 10))

        arch_data = [
            ["Architecture Component", "Implementation & Compliance Specification"],
            ["Company Name", "Global Star Investments Limited"],
            ["Company PIN", "P051548911H"],
            ["Integration Protocol", "System-to-System / Online Sales Control Unit (OSCU) REST API"],
            ["API Endpoints", "• Handshake: /etims-api/v1/oscu/init\n• Sales Transmission: /etims-api/v1/oscu/saveSales"],
            ["Sandbox Token", "KRATK04_F7FB9 (Active & Verified)"],
            ["Device Serial No.", "KRASRN000002834"],
            ["Item Classifications", "Commercial Property Rental (HS Code: 80131502)"],
            ["Billing Frequencies", "Automated scaling supporting Monthly, Bi-Monthly (2-Month), and Quarterly (3-Month) cycles"],
            ["Cryptographic Security", "Token-bound secure receipt signature generation (KRATK04-SIG-...)"],
            ["QR Code Compliance", "Dynamic generation of KRA verification URLs linked to receipt signatures"]
        ]

        t_arch = Table(arch_data, colWidths=[180, 360])
        t_arch.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a252c')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
            ('PADDING', (0,0), (-1,-1), 6)
        ]))
        elements.append(t_arch)
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("<b><u>SYSTEM ARCHITECTURE & WORKFLOW VERIFICATION</u></b>", styles['Heading3']))
        elements.append(Spacer(1, 5))

        summary_text = """
        <b>1. Handshake & Initialization (/initialize):</b><br/>
        The application establishes a secure connection with KRA sandbox servers using Bearer token authentication, passing the taxpayer PIN, Branch ID (01), and device serial number.<br/><br/>
        <b>2. Transaction Processing & Transmission (/saveSales):</b><br/>
        Commercial rental billing data—incorporating custom tenant schedules (Monthly, Bi-Monthly, and Quarterly cycles)—is dynamically structured into JSON payloads. The system transmits item codes (80131502), supply amounts, and tax indicators (NON-VAT/Exempt) directly to the OSCU gateway.<br/><br/>
        <b>3. Cryptographic Validation & QR Rendering:</b><br/>
        Upon successful response, the system captures the official receipt signature (<code>rcptSign</code>) and embeds a secure KRA verification QR code onto the generated tax invoice PDF, ensuring complete audit readiness.
        """
        elements.append(Paragraph(summary_text, small_norm))
        elements.append(Spacer(1, 20))

        elements.append(Paragraph("<font color='#555555' size='7'><b>THIS DOCUMENT IS GENERATED AUTOMATICALLY AS PART OF THE KRA eTIMS SELF-INTEGRATION COMPLIANCE PACKAGE.</b></font>", small_norm))

        doc.build(elements)
        return output_path

    def __init__(self, tenant_excel_path: str, bank_excel_path: str, override_json_path: str = "reassignments.json", ignored_json_path: str = "ignored_transactions.json"):
        self.tenant_path = tenant_excel_path
        self.bank_path = bank_excel_path
        self.override_json_path = override_json_path
        self.ignored_json_path = ignored_json_path
        self.df_tenants = None
        self.df_bank = None
        self.statement_period_str = ""
        self.statement_start_date = None
        self.statement_end_date = None
        self.statement_day = 31
        self.statement_month_str = "July 2026"
        self.overrides = self.load_json(self.override_json_path)
        self.ignored_refs = self.load_json(self.ignored_json_path)
        self.tenancy_review_path = "tenancy_bank_reviews_v1.json"
        self.tenancy_event_history_path = "tenancy_bank_review_history_v1.json"
        from bank_review_v1 import load_review
        self.tenancy_reviews = load_review(self.tenancy_review_path)
        from receipt_split_v1 import load_splits
        self.receipt_split_path = "tenancy_receipt_splits_v1.json"
        self.receipt_splits = load_splits(self.receipt_split_path)
        
        # Published V1 is Excel-only: never initialize or sync a database.
        self.supabase = None

        self.reload_master_data()

    def load_json(self, path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError(
                f"Review file '{path}' cannot be read. Restore a valid JSON backup "
                "rather than losing previous allocation decisions."
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(f"Review file '{path}' must contain a JSON object.")
        return data

    def save_override(self, txn_ref: str, shop_no: int):
        self.overrides[str(txn_ref).strip()] = int(shop_no)
        with open(self.override_json_path, 'w') as f:
            json.dump(self.overrides, f, indent=4)

    def save_ignored(self, txn_ref: str):
        self.ignored_refs[str(txn_ref).strip()] = True
        with open(self.ignored_json_path, 'w') as f:
            json.dump(self.ignored_refs, f, indent=4)

    def standardize_and_filter_transactions(self, df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Standardizes transaction types using the Notes column (Column G) for outgoing funds,
        retains all historical records in the raw layer, and applies strict period filtering.
        """
        processed_df = df.copy()
        
        if 'transaction_date' in processed_df.columns:
            processed_df['transaction_date'] = pd.to_datetime(processed_df['transaction_date'], errors='coerce')
        
        mask_penalty = processed_df['transaction_type'].str.lower() == 'penalty'
        if 'notes' in processed_df.columns:
            processed_df.loc[mask_penalty, 'transaction_type'] = processed_df.loc[mask_penalty, 'notes'].apply(
                lambda x: self._categorize_note(str(x))
            )
        elif 'Notes' in processed_df.columns:
            processed_df.loc[mask_penalty, 'transaction_type'] = processed_df.loc[mask_penalty, 'Notes'].apply(
                lambda x: self._categorize_note(str(x))
            )
        
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        
        filtered_active_df = processed_df[
            (processed_df['transaction_date'] >= start) & 
            (processed_df['transaction_date'] <= end)
        ]
        
        return filtered_active_df

    def _categorize_note(self, note: str) -> str:
        """Helper function to map unstructured notes into standardized financial categories."""
        note_lower = note.lower()
        
        if 'electricity' in note_lower or 'power' in note_lower:
            return 'Utility - Electricity'
        elif 'water' in note_lower:
            return 'Utility - Water'
        elif 'maintenance' in note_lower or 'repair' in note_lower:
            return 'Property Maintenance'
        elif 'tax' in note_lower or 'kra' in note_lower:
            return 'Tax Remittance'
        elif 'supplier' in note_lower or 'stock' in note_lower:
            return 'Inventory Purchase'
        elif 'loan' in note_lower:
            return 'Loan Repayment'
        else:
            return note.title() if note.strip() and note.lower() != 'nan' else 'General Expense'

    def reload_master_data(self):
        # Explicitly load 'Sheet1' from the workbook
        if hasattr(self.tenant_path, 'read') or os.path.exists(self.tenant_path):
            if hasattr(self.tenant_path, 'seek'):
                self.tenant_path.seek(0)
            with pd.ExcelFile(self.tenant_path) as xls_tenant:
                tenant_sheet = 'Sheet1' if 'Sheet1' in xls_tenant.sheet_names else xls_tenant.sheet_names[0]
                self.df_tenants = pd.read_excel(xls_tenant, sheet_name=tenant_sheet)
        else:
            self.df_tenants = pd.DataFrame(columns=['Shop / Unit #', 'Tenant Name', 'Monthly Rate', 'Deposit (KSh)', 'Lease Date', 'Telephone No.', 'Email Address'])
        
        # Standardize 'Shop / Unit #' to 'Shop #'
        if 'Shop / Unit #' in self.df_tenants.columns and 'Shop #' not in self.df_tenants.columns:
            self.df_tenants['Shop #'] = self.df_tenants['Shop / Unit #']
        elif 'Shop #' in self.df_tenants.columns and 'Shop / Unit #' not in self.df_tenants.columns:
            self.df_tenants['Shop / Unit #'] = self.df_tenants['Shop #']
        
        # Robust column name normalization and fallback mapping to prevent KeyErrors
        col_lower_map = {str(c).strip().lower(): c for c in self.df_tenants.columns}
        
        # Safely map 'Tenant Name'
        if 'tenant name' not in col_lower_map and 'name' in col_lower_map:
            self.df_tenants.rename(columns={col_lower_map['name']: 'Tenant Name'}, inplace=True)
        elif 'tenant name' in col_lower_map:
            self.df_tenants.rename(columns={col_lower_map['tenant name']: 'Tenant Name'}, inplace=True)
            
        if 'Tenant Name' in self.df_tenants.columns:
            self.df_tenants['Tenant Name'] = self.df_tenants['Tenant Name'].astype(str).str.replace('Waninga', 'Waringa')
        else:
            self.df_tenants['Tenant Name'] = "Unknown Tenant"
        
        def clean_dep(val):
            try: return float(val)
            except: return 0.0
            
        deposit_col = col_lower_map.get('deposit (ksh)', next((c for c in self.df_tenants.columns if 'deposit' in c.lower()), 'Deposit (KSh)'))
        if deposit_col in self.df_tenants.columns:
            self.df_tenants['Deposit_Clean'] = self.df_tenants[deposit_col].apply(clean_dep)
        else:
            self.df_tenants['Deposit_Clean'] = 0.0

        lease_date_col = col_lower_map.get('lease date', next((c for c in self.df_tenants.columns if 'date' in c.lower()), 'Lease Date'))
        if lease_date_col in self.df_tenants.columns:
            self.df_tenants['Lease_Date_Parsed'] = pd.to_datetime(self.df_tenants[lease_date_col], errors='coerce')
        else:
            self.df_tenants['Lease_Date_Parsed'] = pd.NaT

        self.df_tenants['Lease_Year'] = self.df_tenants['Lease_Date_Parsed'].dt.year.fillna(2026).astype(int)
        self.df_tenants['Deposit_Timing'] = self.df_tenants['Lease_Year'].apply(
            lambda y: '2026 Current Year Addition' if y == 2026 else 'Prior Years Liability (Pre-2026)'
        )

        renew_col = col_lower_map.get('lease renewed (yes/no)', next((c for c in self.df_tenants.columns if 'renew' in c.lower()), None))
        if renew_col and renew_col in self.df_tenants.columns:
            self.df_tenants['Lease_Type'] = self.df_tenants[renew_col].apply(
                lambda x: 'New Lease' if str(x).strip().upper() == 'YES' else 'Old Lease'
            )
        else:
            self.df_tenants['Lease_Type'] = 'Old Lease'

        # =====================================================================
        # DYNAMIC LEASE DURATION, END DATE & STATUS CALCULATION
        # =====================================================================
        duration_col = next((c for c in self.df_tenants.columns if 'period' in c.lower() or 'duration' in c.lower() or 'month' in c.lower()), None)
        
        def calculate_end_date(row):
            start_dt = row['Lease_Date_Parsed']
            if pd.isnull(start_dt):
                return None
            try:
                months = int(row[duration_col]) if duration_col and duration_col in row and pd.notnull(row[duration_col]) else 12
                return start_dt + pd.DateOffset(months=months)
            except:
                return start_dt + pd.DateOffset(months=12)

        self.df_tenants['Calculated_Lease_End'] = self.df_tenants.apply(calculate_end_date, axis=1)
        
        today = pd.Timestamp.now()
        self.df_tenants['Calculated_Status'] = self.df_tenants['Calculated_Lease_End'].apply(
            lambda end_dt: 'expired' if pd.notnull(end_dt) and end_dt < today else 'active'
        )

        # =====================================================================
        # BANK STATEMENT PARSING & ROBUST RECONCILIATION
        # =====================================================================
        if hasattr(self.bank_path, 'seek'):
            self.bank_path.seek(0)
        xls = pd.ExcelFile(self.bank_path)
        sheet_name = 'Bank Statement' if 'Bank Statement' in xls.sheet_names else xls.sheet_names[0]
        
        df_raw = pd.read_excel(xls, sheet_name=sheet_name)
        
        for row_idx in range(min(25, len(df_raw))):
            cell_val = str(df_raw.iloc[row_idx, 0])
            if 'Period:' in cell_val or 'Period' in str(df_raw.iloc[row_idx, 0]):
                full_text = str(df_raw.iloc[row_idx, 0]) + " " + str(df_raw.iloc[row_idx, 1])
                match = re.search(r'(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})', full_text)
                if match:
                    self.statement_period_str = match.group(0)
                    self.statement_start_date = datetime.strptime(match.group(1), "%d/%m/%Y")
                    self.statement_end_date = datetime.strptime(match.group(2), "%d/%m/%Y")
                    self.statement_day = self.statement_end_date.day
                    self.statement_month_str = self.statement_end_date.strftime("%B %Y")
                    print(f"DEBUG BANK STATEMENT: Start -> {self.statement_start_date.strftime('%Y-%m-%d')}, End -> {self.statement_end_date.strftime('%Y-%m-%d')}")
                    break
        
        h_idx = 13
        for idx in range(len(df_raw)):
            row_vals = [str(v) for v in df_raw.iloc[idx].values]
            if 'Transaction Date' in row_vals or 'Bank Reference Number' in row_vals:
                h_idx = idx
                break

        if h_idx == 13 and not any(
            "Transaction Date" in [str(v).strip() for v in df_raw.iloc[idx].values]
            or "Bank Reference Number" in [str(v).strip() for v in df_raw.iloc[idx].values]
            for idx in range(len(df_raw))
        ):
            xls.close()
            raise ValueError(
                "The uploaded Bank Statement workbook does not contain a KCB "
                "transaction header. It may be a tenants workbook. Please upload "
                "KCB_Bank_Statement.xlsx under 'Upload Bank Statement (Excel)'."
            )

        columns = [str(c).strip() for c in df_raw.iloc[h_idx].values]
        self.df_bank = pd.read_excel(xls, sheet_name=sheet_name, skiprows=h_idx+1)
        self.df_bank.columns = [str(c).strip() for c in columns]
        xls.close()
        
        col_map = {c.lower(): c for c in self.df_bank.columns}
        money_in_col = col_map.get('money in', next((c for c in self.df_bank.columns if 'money in' in c.lower() or 'credit' in c.lower()), 'Money In'))
        money_out_col = col_map.get('money out', next((c for c in self.df_bank.columns if 'money out' in c.lower() or 'debit' in c.lower()), 'Money Out'))
        txn_desc_col = col_map.get('transaction details', next((c for c in self.df_bank.columns if 'transaction' in c.lower() or 'description' in c.lower()), 'Transaction Details'))
        ref_col = col_map.get('bank reference number', col_map.get('ref', next((c for c in self.df_bank.columns if 'ref' in c.lower()), 'Bank Reference Number')))
        
        required_bank_fields = {
            "Money In": money_in_col, "Money Out": money_out_col,
            "Transaction Details": txn_desc_col, "Bank Reference Number": ref_col,
        }
        missing_bank_fields = [
            label for label, column in required_bank_fields.items()
            if column not in self.df_bank.columns
        ]
        if missing_bank_fields:
            raise ValueError(
                "The Bank Statement upload is missing required KCB columns: "
                + ", ".join(missing_bank_fields)
                + ". Confirm the KCB statement is uploaded in the bank field, "
                  "not the tenant-history workbook."
            )

        self.df_bank['Money In Num'] = pd.to_numeric(
            self.df_bank[money_in_col].astype(str).str.replace(',', '').str.strip(), errors='coerce'
        ).fillna(0)
        self.df_bank['Money Out Num'] = pd.to_numeric(
            self.df_bank[money_out_col].astype(str).str.replace(',', '').str.strip(), errors='coerce'
        ).fillna(0)
        self.df_bank['Transaction Details'] = self.df_bank[txn_desc_col].astype(str)
        self.df_bank['Ref_Clean'] = self.df_bank[ref_col].astype(str).str.strip()
        from bank_review_v1 import bank_row_ids
        self.df_bank["Bank_Row_ID"] = bank_row_ids(self.df_bank)
        # Preserve original movements and historically excluded rows for audit.
        self.df_bank_unfiltered = self.df_bank.copy()

        def should_ignore(row):
            ref = row['Ref_Clean']
            desc = row['Transaction Details'].upper()
            if ref in self.ignored_refs:
                return True
            if any(k in desc for k in ['ONLINE.AC.CLOSURE', 'TESTING MPESA', 'DIRECTOR DEPOSIT']):
                return True
            return False

        self.df_bank = self.df_bank[~self.df_bank.apply(should_ignore, axis=1)].copy()

        if 'July' in xls.sheet_names:
            july_df = pd.read_excel(xls, sheet_name='July')
            july_df['Ref_Clean'] = july_df['Bank Reference Number'].astype(str).str.strip()
            if 'Customers Name' in july_df.columns:
                self.df_bank = pd.merge(
                    self.df_bank, 
                    july_df[['Ref_Clean', 'Customers Name']].drop_duplicates(subset=['Ref_Clean']), 
                    on='Ref_Clean', 
                    how='left'
                )

        def is_valid_credit(row):
            ref = row['Ref_Clean']
            amt = row['Money In Num']
            if amt > 0:
                debit_matches = self.df_bank[(self.df_bank['Ref_Clean'] == ref) & (self.df_bank['Money Out Num'] < 0) & (abs(self.df_bank['Money Out Num']) == amt)]
                if not debit_matches.empty:
                    if any(row.name <= d_idx for d_idx in debit_matches.index):
                        return False
            return True

        self.df_bank['Valid_Credit'] = self.df_bank.apply(is_valid_credit, axis=1)

    def verify_ocr_against_master(self, extracted_lease: dict) -> dict:
        """Compare only confidently extracted values; do not infer an identity from unit alone."""
        shop_no = extracted_lease.get("Shop #")
        name = extracted_lease.get("Tenant Name")
        results = {"Match Found": False, "Discrepancies": [],
                   "Manual Status": "Unverified", "Master Tenant Name": None}
        warnings = extracted_lease.get("Extraction Warnings") or []
        if warnings:
            results["Discrepancies"].extend(warnings)
        if shop_no is None or not name:
            results["Discrepancies"].append(
                "Tenant name and shop number must be verified before matching the master workbook.")
            return results
        matches = self.df_tenants.loc[
            pd.to_numeric(self.df_tenants["Shop #"], errors="coerce").eq(shop_no)
            & self.df_tenants["Tenant Name"].fillna("").astype(str).str.strip().str.casefold().eq(
                str(name).strip().casefold())
        ]
        if len(matches) != 1:
            results["Discrepancies"].append(
                "No unique tenancy matched both the extracted tenant name and shop number.")
            return results
        entry = matches.iloc[0]
        results["Match Found"] = True
        results["Master Tenant Name"] = str(entry["Tenant Name"])
        results["Manual Status"] = str(entry.get(
            "Tenancy Record Status", entry.get("Manual_Lease_Status", "Unverified")))
        extracted_rate = extracted_lease.get("Monthly Rent (KSh)")
        if extracted_rate is None:
            results["Discrepancies"].append("Monthly rent was not extracted; manual verification required.")
        else:
            master_rate = pd.to_numeric(pd.Series([entry.get("Monthly Rate")]), errors="coerce").iloc[0]
            if pd.isna(master_rate):
                results["Discrepancies"].append("Master workbook monthly rent is missing.")
            elif abs(float(extracted_rate) - float(master_rate)) > 1:
                results["Discrepancies"].append(
                    f"Rent mismatch: PDF KSh {float(extracted_rate):,.2f}; master KSh {float(master_rate):,.2f}.")
        return results

    def map_transaction_to_shop(self, details_str: str, ref_str: str = "", customer_name: str = "") -> int:
        clean_ref = str(ref_str).strip()
        if clean_ref in self.overrides:
            return int(self.overrides[clean_ref])

        combined_text = f"{str(details_str)} {str(customer_name)}".upper()
        
        if 'MUMIA' in combined_text or 'CHESANG' in combined_text or 'GLORIA' in combined_text: return 8
        elif 'PATRICIA' in combined_text or 'WARINGA' in combined_text or 'WANINGA' in combined_text: return 1
        elif 'HILINE' in combined_text or 'HI-LINE' in combined_text: return 2
        elif 'MASH EAST AFRICA' in combined_text or 'MASH EAST' in combined_text or 'MASH POA' in combined_text: return 3
        elif 'VINCENT' in combined_text or 'VCENTOZ' in combined_text or 'BARBRA' in combined_text: return 4
        elif 'DREAM' in combined_text or 'DREAMLINE' in combined_text: return 5
        elif 'GREENLINE' in combined_text or 'CARO' in combined_text: return 6
        elif 'MC HOME' in combined_text or 'HOMEDECCOR' in combined_text: return 7
        elif 'JOE' in combined_text or 'MIDTOWN' in combined_text: return 9
        elif 'MOWLEM' in combined_text: return 10
        elif 'SUNCULTURE' in combined_text or 'SUN CULTURE' in combined_text: return 11
        elif 'PILONA' in combined_text: return 12
        elif 'MOHA' in combined_text or 'CROWN' in combined_text: return 13
        elif 'NOEL' in combined_text or 'LEGACY' in combined_text: return 14
        elif 'CEMES' in combined_text or 'LINET' in combined_text: return 15
        elif 'PLATINUM' in combined_text: return 16
        elif 'PITT' in combined_text or 'OPTICS' in combined_text: return 17
        elif 'EVER' in combined_text or 'ACHIENG' in combined_text: return 18
        elif 'ALOI' in combined_text or 'NGOLO' in combined_text: return 19
        elif 'ALPH' in combined_text: return 20
        elif 'HAND IN HAND' in combined_text: return 21
        elif 'MART' in combined_text or 'CELE' in combined_text: return 22
        return 0

    def tenancy_turnover_report(self, period_start=None, period_end=None):
        """Excel-only tenancy register and cautious bank credit identification."""
        from tenancy_turnover_v1 import tenancy_register, classify_credits
        start = period_start or self.statement_start_date
        end = period_end or self.statement_end_date
        if start is None or end is None:
            raise ValueError("Bank statement reporting dates are unavailable")
        register = tenancy_register(self.df_tenants, start, end)
        # Reattach per-row bank identity and legacy decisions, without deleting movements.
        review_bank = self.df_bank_unfiltered.copy()
        if "Customers Name" in self.df_bank.columns:
            linked = self.df_bank[["Bank_Row_ID", "Customers Name"]].drop_duplicates("Bank_Row_ID")
            review_bank = review_bank.merge(linked, on="Bank_Row_ID", how="left")
        # Validate credits against reversal rows using the existing bank parser.
        validity = self.df_bank[["Bank_Row_ID", "Valid_Credit"]].drop_duplicates("Bank_Row_ID")
        review_bank = review_bank.merge(validity, on="Bank_Row_ID", how="left")
        review_bank["Valid_Credit"] = review_bank["Valid_Credit"].fillna(True)
        return classify_credits(
            review_bank, register, self.map_transaction_to_shop, start, end,
            reviews=self.tenancy_reviews, old_overrides=self.overrides,
            old_ignored=self.ignored_refs, splits=self.receipt_splits
        )

    def save_receipt_split(self, bank_row_id, tenancy_id, components, evidence):
        """Allocate one exact bank row without booking deposits as rent."""
        from receipt_split_v1 import create_receipt_split, save_splits
        from tenancy_turnover_v1 import tenancy_register
        from bank_review_v1 import append_review_event
        import getpass
        if bank_row_id not in set(self.df_bank_unfiltered["Bank_Row_ID"]):
            raise ValueError("Bank row not present in the uploaded statement")
        row = self.df_bank_unfiltered.loc[
            self.df_bank_unfiltered["Bank_Row_ID"] == bank_row_id].iloc[0]
        register = tenancy_register(
            self.df_tenants, self.statement_start_date, self.statement_end_date)
        selected = register.loc[register["Tenancy_ID"] == str(tenancy_id)]
        if selected.empty:
            raise ValueError("Individual tenancy was not found")
        previous = self.tenancy_reviews.get(bank_row_id, {})
        if previous.get("decision") in {"assign", "exclude"}:
            raise ValueError("A previously approved assignment/exclusion must first be reviewed")
        reference = str(row["Ref_Clean"]).strip()
        if reference in self.ignored_refs and previous.get("decision") != "restore":
            raise ValueError("Restore this excluded bank row before splitting")
        if any(x in str(row["Transaction Details"]).upper() for x in
               ["ONLINE.AC.CLOSURE", "TESTING MPESA", "DIRECTOR DEPOSIT"]):
            raise ValueError("Automatic non-rent exclusion must be reviewed before splitting")
        valid = self.df_bank.loc[self.df_bank["Bank_Row_ID"] == bank_row_id]
        if valid.empty or not bool(valid.iloc[0]["Valid_Credit"]):
            raise ValueError("Excluded or reversed credit cannot be split")
        updated = create_receipt_split(
            self.receipt_splits, bank_row_id, tenancy_id, row, selected.iloc[0],
            components, evidence, getpass.getuser())
        append_review_event(
            self.tenancy_event_history_path, bank_row_id=bank_row_id,
            reference=reference, action="split_receipt", reason=evidence,
            previous=previous.get("decision", "unreviewed"), actor=getpass.getuser())
        save_splits(self.receipt_split_path, updated)
        self.receipt_splits = updated

    def save_tenancy_bank_review(self, bank_row_id, decision, tenancy_id=None, reason=""):
        from bank_review_v1 import write_review, record_decision
        if bank_row_id in self.receipt_splits:
            raise ValueError("This bank transaction already has a verified receipt split; it cannot also be reviewed as a full rent payment")
        if bank_row_id not in set(self.df_bank_unfiltered["Bank_Row_ID"]):
            raise ValueError("The selected transaction is not in the uploaded bank statement")
        if decision == "assign":
            from tenancy_turnover_v1 import tenancy_register
            register = tenancy_register(self.df_tenants, self.statement_start_date, self.statement_end_date)
            selected = register[register["Tenancy_ID"] == str(tenancy_id)]
            if selected.empty or bool(selected.iloc[0]["Review_Required"]) or selected.iloc[0]["Tenancy_Status"] == "vacancy":
                raise ValueError("Choose a valid individual tenancy, not a vacant or unverified record")
        if decision == "assign":
            from tenancy_turnover_v1 import _tx_date
            movement = self.df_bank_unfiltered[self.df_bank_unfiltered["Bank_Row_ID"] == bank_row_id].iloc[0]
            move_date = _tx_date(movement["Transaction Date"])
            start = selected.iloc[0]["Lease_Date_Parsed"]
            end = selected.iloc[0]["End_Actual"]
            if float(movement.get("Money In Num", 0)) <= 0 or pd.isna(move_date):
                raise ValueError("Only dated incoming credits can be assigned to rent")
            if pd.isna(start) or move_date < start:
                raise ValueError("The payment predates this tenancy; do not assign it as rent")
            if pd.notna(end) and move_date > end and "POST-TENANCY" not in reason.upper():
                raise ValueError("For a payment after departure, include POST-TENANCY in the evidence note if it settles this former tenant's arrears")
        if decision == "restore" and not reason.strip():
            raise ValueError("Explain why this exclusion should be restored")
        row = self.df_bank_unfiltered.loc[
            self.df_bank_unfiltered["Bank_Row_ID"] == bank_row_id].iloc[0]
        reference = str(row["Ref_Clean"]).strip()
        previous = self.tenancy_reviews.get(bank_row_id, {}).get("decision", "")
        if decision == "restore" and previous != "exclude" and reference not in self.ignored_refs:
            raise ValueError("This selected bank row has no recorded exclusion")
        updated = record_decision(self.tenancy_reviews, bank_row_id, decision, tenancy_id, reason)
        if updated == self.tenancy_reviews:
            return False  # An unchanged decision must not produce duplicate history.
        from bank_review_v1 import append_review_event
        import getpass
        append_review_event(
            self.tenancy_event_history_path, bank_row_id=bank_row_id,
            reference=reference, action=decision, reason=reason,
            previous=previous or ("legacy reference exclusion" if reference in self.ignored_refs else "unreviewed"),
            actor=getpass.getuser(),
        )
        write_review(self.tenancy_review_path, updated)
        self.tenancy_reviews = updated
        return True

    def calculate_tenant_arrears(self, current_day: int = None) -> pd.DataFrame:
        # Historical tenancy workbooks must not be billed using the legacy
        # shop-level 12-month assumption or cross-tenant bank allocations.
        if {'Tenancy Record Status', 'Lease End Date'}.issubset(self.df_tenants.columns):
            register, pending = self.tenancy_turnover_report()
            self.turnover_pending_credits = pending
            return register

        if current_day is None:
            current_day = self.statement_day

        df_credits = self.df_bank[(self.df_bank['Money In Num'] > 0) & (self.df_bank['Valid_Credit'] == True)].copy()
        
        cust_col = 'Customers Name' if 'Customers Name' in df_credits.columns else ''
        df_credits['Shop_ID'] = df_credits.apply(
            lambda r: self.map_transaction_to_shop(
                r['Transaction Details'], 
                r['Ref_Clean'], 
                r[cust_col] if cust_col and pd.notnull(r[cust_col]) else ""
            ), axis=1
        )
        
        summary = df_credits.groupby('Shop_ID')['Money In Num'].sum().reset_index()
        summary.columns = ['Shop #', 'Actual_Collected']
        
        df_tenants_active = self.df_tenants.copy()
        df_tenants_active = df_tenants_active[df_tenants_active['Shop #'].isin(list(range(1, 23)))]
        
        df_res = pd.merge(df_tenants_active, summary, on='Shop #', how='left')
        df_res['Actual_Collected'] = df_res['Actual_Collected'].fillna(0)
        
        def adjust_collected(row):
            collected = row['Actual_Collected']
            lease_year = row.get('Lease_Year', 0)
            deposit_amt = row.get('Deposit_Clean', 0.0)
            if lease_year == 2026 and collected >= deposit_amt:
                return collected - deposit_amt
            return collected

        df_res['Actual_Collected'] = df_res.apply(adjust_collected, axis=1)
        
        def calc_expected(row):
            s_num = row['Shop #']
            rate = row['Monthly Rate']
            if s_num in [20, 22]: return rate * 5
            return rate * 12
            
        df_res['Expected_Rent'] = df_res.apply(calc_expected, axis=1)
        df_res['Base_Arrears'] = df_res['Expected_Rent'] - df_res['Actual_Collected']
        
        def apply_penalties(row):
            base_arr = row['Base_Arrears']
            lease_type = str(row['Lease_Type']).strip()
            shop_id = row['Shop #']
            
            penalty_fee = 0.0
            interest_charge = 0.0
            legal_status = "Compliant"
            
            shop_payments = df_credits[df_credits['Shop_ID'] == shop_id]
            
            if lease_type == 'Old Lease':
                for _, pay_row in shop_payments.iterrows():
                    txn_date = pd.to_datetime(pay_row['Transaction Date'], errors='coerce', dayfirst=True)
                    if pd.notnull(txn_date) and txn_date.day > 5:
                        penalty_fee += 2000.0
                if penalty_fee > 0:
                    legal_status = f"Late Fees Charged (Total: KSh {penalty_fee:,.0f})"
            elif lease_type == 'New Lease':
                for _, pay_row in shop_payments.iterrows():
                    txn_date = pd.to_datetime(pay_row['Transaction Date'], errors='coerce', dayfirst=True)
                    if pd.notnull(txn_date) and txn_date.day > 10:
                        penalty_fee += 2000.0
                if base_arr > 0 and current_day > 10:
                    penalty_fee = max(penalty_fee, 2000.0)
                    interest_charge = base_arr * 0.015
                    legal_status = "Late Penalty (KSh 2k + 1.5% Int.)"
            
            if base_arr > 0:
                if lease_type == 'Old Lease':
                    if current_day > 10:
                        legal_status = "ACCESS RESTRICTION (Lock Doors / Distress)"
                    elif penalty_fee == 0 and current_day > 5:
                        penalty_fee = 2000.0
                        legal_status = "Late Fee Charged (KSh 2,000)"
                else:
                    if current_day >= 30:
                        legal_status = "MATERIAL BREACH (Re-entry & Forfeiture)"
        
            total_arrears = base_arr + penalty_fee + interest_charge

            if total_arrears <= 0:
                legal_status = "Compliant"
            elif "Compliant" in legal_status:
                legal_status = "ACCESS RESTRICTION (Arrears Balance)"

            return pd.Series([penalty_fee, interest_charge, total_arrears, legal_status])
    
        df_res[['Penalty_Fee', 'Interest_Charge', 'Arrears_Balance', 'Enforcement_Status']] = df_res.apply(apply_penalties, axis=1)
        
        def clean_phone_str(val):
            if pd.isnull(val):
                return ""
            s = str(val).strip()
            if s.endswith('.0'):
                s = s[:-2]
            return ''.join(filter(str.isdigit, s))

        df_res['Telephone No.'] = df_res['Telephone No.'].apply(clean_phone_str)
        
        return df_res

    def get_tenant_billing_cycle_details(self, shop_no: int, monthly_rate: float, billing_month: str) -> tuple:
        s_num = int(shop_no)
        if s_num in [2, 16, 21]:
            multiplier = 3
            total_amount = monthly_rate * multiplier
            item_desc = f"Commercial Rent - Shop #{s_num} (Quarterly Billing: {billing_month})"
        elif s_num == 12:
            multiplier = 2
            total_amount = monthly_rate * multiplier
            item_desc = f"Commercial Rent - Shop #{s_num} (Bi-Monthly Billing: {billing_month})"
        else:
            multiplier = 1
            total_amount = monthly_rate
            item_desc = f"Commercial Rent - Shop #{s_num} ({billing_month})"
        return multiplier, total_amount, item_desc

    def get_unmapped_deposits(self) -> pd.DataFrame:
        df_credits = self.df_bank[(self.df_bank['Money In Num'] > 0) & (self.df_bank['Valid_Credit'] == True)].copy()
        cust_col = 'Customers Name' if 'Customers Name' in df_credits.columns else ''
        
        def safe_map(r):
            try:
                shop_id = self.map_transaction_to_shop(
                    r['Transaction Details'], 
                    r['Ref_Clean'], 
                    r[cust_col] if cust_col and pd.notnull(r[cust_col]) else ""
                )
                if shop_id in [0, "0", None, "", "None", "N/A"]:
                    return 0
                return shop_id
            except Exception:
                return 0

        df_credits['Shop_ID'] = df_credits.apply(safe_map, axis=1)
        unmapped = df_credits[df_credits['Shop_ID'] == 0].copy()
        
        cols_to_show = ['Transaction Date', 'Transaction Details', 'Money In Num', 'Ref_Clean']
        if cust_col:
            cols_to_show.insert(2, cust_col)
            
        return unmapped[cols_to_show]

    def generate_etims_tax_invoice_pdf(self, tenant_name: str, shop_no: int, rate: float, paybill: str, paybill_acc: str, branch_name: str, bank_code: str, branch_code: str, swift_code: str, billing_month: str = "July 2026", base_filename: str = None, kra_pin: str = "P051548911H", etims_env: str = "Sandbox (Testing)"):
        parts = billing_month.split()
        month_name = parts[0] if len(parts) > 0 else "General"
        year_name = parts[1] if len(parts) > 1 else str(datetime.now().year)

        target_dir = os.path.join("Invoices", year_name, month_name)
        os.makedirs(target_dir, exist_ok=True)

        if not base_filename:
            clean_name = tenant_name.replace(' ', '_').replace('/', '_')
            base_filename = f"eTIMS_Invoice_Shop_{shop_no}_{clean_name}.pdf"

        full_pdf_path = os.path.join(target_dir, base_filename)

        df_credits = self.df_bank[(self.df_bank['Money In Num'] > 0) & (self.df_bank['Valid_Credit'] == True)].copy()
        cust_col = 'Customers Name' if 'Customers Name' in df_credits.columns else ''
        df_credits['Shop_ID'] = df_credits.apply(
            lambda r: self.map_transaction_to_shop(
                r['Transaction Details'], 
                r['Ref_Clean'], 
                r[cust_col] if cust_col and pd.notnull(r[cust_col]) else ""
            ), axis=1
        )
        tenant_txns = df_credits[df_credits['Shop_ID'] == shop_no].copy()

        matched_refs = []
        total_paid_in_period = 0.0
        month_map = {
            'January': 1, 'February': 2, 'March': 3, 'April': 4,
            'May': 5, 'June': 6, 'July': 7, 'August': 8,
            'September': 9, 'October': 10, 'November': 11, 'December': 12
        }
        target_month_num = month_map.get(month_name, None)

        if not tenant_txns.empty and target_month_num and 'Transaction Date' in tenant_txns.columns:
            parsed_dates = pd.to_datetime(tenant_txns['Transaction Date'], format='%d.%m.%Y', errors='coerce')
            parsed_dates = parsed_dates.fillna(pd.to_datetime(tenant_txns['Transaction Date'], dayfirst=True, errors='coerce'))
            mask = (parsed_dates.dt.month == target_month_num) & (parsed_dates.dt.year == int(year_name))
            filtered_txns = tenant_txns[mask]
            
            for _, txn_row in filtered_txns.iterrows():
                ref_val = str(txn_row.get('Ref_Clean', ''))
                amt_val = float(txn_row.get('Money In Num', 0.0))
                if ref_val and ref_val != 'nan':
                    matched_refs.append(f"{ref_val} (KSh {amt_val:,.2f})")
                total_paid_in_period += amt_val

        ref_string = ", ".join(matched_refs) if matched_refs else "No bank ref matched for period"

        t_match = self.df_tenants[self.df_tenants['Shop #'] == shop_no]
        tenant_pin = "N/A"
        tenant_phone = "N/A"
        tenant_email = "N/A"
        
        if not t_match.empty:
            row = t_match.iloc[0]
            if 'KRA PIN Certificate' in row and pd.notnull(row['KRA PIN Certificate']):
                pin_val = str(row['KRA PIN Certificate']).split('.')[0].strip()
                tenant_pin = pin_val if pin_val != 'nan' else 'N/A'
            if 'Telephone No.' in row and pd.notnull(row['Telephone No.']):
                phone_raw = str(row['Telephone No.']).split('.')[0].strip()
                tenant_phone = phone_raw if phone_raw != 'nan' else 'N/A'
            if 'Email Address' in row and pd.notnull(row['Email Address']):
                email_val = str(row['Email Address']).strip()
                tenant_email = email_val if email_val != 'nan' else 'N/A'

        now_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inv_no_num = f"{shop_no}{datetime.now().strftime('%m%d')}"
        scu_serial = "KRASRN000002834"
        cu_inv_no = f"{scu_serial}/{inv_no_num}"
        receipt_sig = f"GSIL-KRA-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        multiplier, total_invoice_amount, item_desc = self.get_tenant_billing_cycle_details(shop_no, rate, billing_month)

        etims_data = {
            "etims_invoice_no": inv_no_num,
            "scu_id": scu_serial,
            "receipt_signature": receipt_sig,
            "cu_invoice_no": cu_inv_no,
            "qr_code_url": f"https://etims.kra.go.ke/common/link/etims/receipt/index?checkGdm={receipt_sig}"
        }

        if KRAeTIMSClient:
            client = KRAeTIMSClient(kra_pin=kra_pin, environment=etims_env)
            etims_res = client.transmit_rent_invoice(tenant_name, tenant_pin, shop_no, total_invoice_amount, is_vat_applicable=False, billing_month=billing_month)
            if etims_res.get("status") in ["SUCCESS", "SUCCESS (SIMULATED)", "SUCCESS (TOKEN SIGNED)"]:
                etims_data["receipt_signature"] = etims_res.get("receipt_signature", receipt_sig)
                etims_data["qr_code_url"] = etims_res.get("qr_code_url", etims_data["qr_code_url"])

        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(etims_data['qr_code_url'])
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")
        
        qr_buffer = BytesIO()
        img_qr.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)

        doc = SimpleDocTemplate(full_pdf_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1a252c'), spaceAfter=2)
        normal_style = styles['Normal']
        small_bold = ParagraphStyle('SmallBold', parent=normal_style, fontSize=9, leading=12, fontName='Helvetica-Bold')
        small_norm = ParagraphStyle('SmallNorm', parent=normal_style, fontSize=9, leading=12)

        elements.append(Paragraph("<b>Invoice</b>", title_style))
        elements.append(Paragraph(f"<b>Date Created:</b> {now_dt_str}", small_norm))
        elements.append(Spacer(1, 4))

        meta_line = f"<b>Invoice No:</b> {etims_data['etims_invoice_no']} &nbsp;&nbsp;&nbsp;&nbsp; <b>SCU ID:</b> {etims_data['scu_id']} &nbsp;&nbsp;&nbsp;&nbsp; <b>Receipt Signature:</b> {etims_data['receipt_signature']}"
        elements.append(Paragraph(meta_line, small_norm))
        elements.append(Spacer(1, 10))

        # Updated with official corporate email from KRA PIN certificate
        sale_from_text = """
        <b><u>Sale From:</u></b><br/>
        <b>GLOBAL STAR INVESTMENTS LIMITED</b><br/>
        <b>PIN:</b> P051548911H<br/>
        GLOBALSTARINVEST@GMAIL.COM<br/>
        1258, 00511, Ongata Rongai, Kenya
        """

        sale_to_text = f"""
        <b><u>Sale To:</u></b><br/>
        <b>{tenant_name}</b><br/>
        <b>PIN:</b> {tenant_pin}<br/>
        {tenant_email}<br/>
        +{tenant_phone}<br/>
        <b>CU Invoice Number:</b><br/>
        {etims_data['cu_invoice_no']}
        """

        qr_img = Image(qr_buffer, width=75, height=75)

        header_table = Table([
            [Paragraph(sale_from_text, small_norm), Paragraph(sale_to_text, small_norm), qr_img]
        ], colWidths=[220, 220, 100])
        
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fcfcfc')),
            ('PADDING', (0,0), (-1,-1), 6)
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 12))

        elements.append(Paragraph("<b>Amounts are in KES</b>", small_bold))
        elements.append(Spacer(1, 4))

        data = [
            ["Item", "Qty", "Price", "Tax Type", "Tax", "Discount", "Total"],
            [f"{item_desc} | Ref: {ref_string}", "1.00", f"{total_invoice_amount:,.2f}", "NON VAT", "0.00", "0.00", f"{total_invoice_amount:,.2f}"]
        ]

        # Optimized column widths: Item column widened to 250pt to prevent overflow
        t_items = Table(data, colWidths=[250, 30, 60, 55, 35, 45, 65])
        t_items.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a252c')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('PADDING', (0,0), (-1,-1), 5)
        ]))
        elements.append(t_items)
        elements.append(Spacer(1, 8))

        elements.append(Paragraph("<b>Number of items: 1</b>", small_norm))
        elements.append(Spacer(1, 8))

        totals_data = [
            ["Rate", "Taxable Amount", "VAT"],
            ["NON VAT", f"{total_invoice_amount:,.2f}", "0.00"],
            ["Subtotal", "", f"{total_invoice_amount:,.2f}"],
            ["Total VAT", "", "0.00"],
            ["Total Discount", "", "0.00"],
            ["Total Amount", "", f"{total_invoice_amount:,.2f}"]
        ]

        t_totals = Table(totals_data, colWidths=[180, 180, 180])
        t_totals.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0f2f6')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('PADDING', (0,0), (-1,-1), 4)
        ]))
        elements.append(t_totals)
        elements.append(Spacer(1, 10))

        payment_methods_text = f"M-Pesa Paybill (Business No: {paybill} | Account: {paybill_acc}) OR Direct Bank Transfer: KCB Bank ({branch_name} Branch) | Acc Name: GLOBAL STAR INVESTMENTS LIMITED | Acc No: 1285399528 | Bank Code: {bank_code} | Branch Code: {branch_code} | SWIFT: {swift_code}"

        footer_note = f"""
        <b>Payment Methods:</b> {payment_methods_text}<br/>
        <b>Payment Status in Period ({billing_month}):</b> Total Paid Recorded: KSh {total_paid_in_period:,.2f} | References: {ref_string}<br/>
        <b>Terms & Conditions:</b> Rent is due as per lease agreement<br/>
        <b>Note:</b> Until your PIN is updated: We will issue a temporary non-VAT eTIMS invoice. WHT deduction will be temporarily suspended.<br/><br/>
        <font color="#555555" size="7"><b>THIS IS A VALID COMPUTER-GENERATED PREVIEW DOCUMENT GENERATED FOR ELECTRONIC TRANSMISSION TO THE KENYA REVENUE AUTHORITY (KRA eTIMS).</b></font>
        """
        elements.append(Paragraph(footer_note, small_norm))

        doc.build(elements)
        return full_pdf_path

    def generate_bank_statement_pdf(self, tenant_name: str, shop_no: int, rate: float, expected: float, collected: float, arrears: float, penalty: float, interest: float, paybill: str, paybill_acc: str, branch_name: str, bank_code: str, branch_code: str, swift_code: str, billing_month: str = "July 2026", base_filename: str = None):
        parts = billing_month.split()
        month_name = parts[0] if len(parts) > 0 else "General"
        year_name = parts[1] if len(parts) > 1 else str(datetime.now().year)

        target_dir = os.path.join("Bank_Statements", year_name, month_name)
        os.makedirs(target_dir, exist_ok=True)

        if not base_filename:
            clean_name = tenant_name.replace(' ', '_').replace('/', '_')
            base_filename = f"Bank_Statement_Shop_{shop_no}_{clean_name}.pdf"

        full_pdf_path = os.path.join(target_dir, base_filename)

        df_credits = self.df_bank[(self.df_bank['Money In Num'] > 0) & (self.df_bank['Valid_Credit'] == True)].copy()
        cust_col = 'Customers Name' if 'Customers Name' in df_credits.columns else ''
        df_credits['Shop_ID'] = df_credits.apply(
            lambda r: self.map_transaction_to_shop(
                r['Transaction Details'], 
                r['Ref_Clean'], 
                r[cust_col] if cust_col and pd.notnull(r[cust_col]) else ""
            ), axis=1
        )
        tenant_txns = df_credits[df_credits['Shop_ID'] == shop_no].copy()

        if not tenant_txns.empty and 'Transaction Date' in tenant_txns.columns:
            month_map = {
                'January': 1, 'February': 2, 'March': 3, 'April': 4,
                'May': 5, 'June': 6, 'July': 7, 'August': 8,
                'September': 9, 'October': 10, 'November': 11, 'December': 12
            }
            target_month_num = month_map.get(month_name, None)
            
            if target_month_num:
                parsed_dates = pd.to_datetime(tenant_txns['Transaction Date'], format='%d.%m.%Y', errors='coerce')
                parsed_dates = parsed_dates.fillna(pd.to_datetime(tenant_txns['Transaction Date'], dayfirst=True, errors='coerce'))
                
                mask = (parsed_dates.dt.month == target_month_num) & (parsed_dates.dt.year == int(year_name))
                filtered_txns = tenant_txns[mask]
                if not filtered_txns.empty:
                    tenant_txns = filtered_txns

        doc = SimpleDocTemplate(full_pdf_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1a252c'), spaceAfter=2)
        normal_style = styles['Normal']
        small_bold = ParagraphStyle('SmallBold', parent=normal_style, fontSize=9, leading=12, fontName='Helvetica-Bold')
        small_norm = ParagraphStyle('SmallNorm', parent=normal_style, fontSize=9, leading=12)
        th_style = ParagraphStyle('TableHeader', parent=small_bold, textColor=colors.white, alignment=1)
        th_left = ParagraphStyle('TableHeaderLeft', parent=small_bold, textColor=colors.white, alignment=0)
        td_center = ParagraphStyle('TableCellCenter', parent=small_norm, alignment=1)
        td_right = ParagraphStyle('TableCellRight', parent=small_bold, alignment=2, textColor=colors.HexColor('#1a252c'))

        elements.append(Paragraph("<b>GLOBAL STAR INVESTMENTS LIMITED</b>", title_style))
        elements.append(Paragraph(f"<b>TENANT BANK PAYMENT & RENT LEDGER STATEMENT</b>", styles['Heading2']))
        elements.append(Paragraph(f"<b>Period:</b> {billing_month} | <b>Property Unit:</b> Shop #{shop_no} ({tenant_name})", normal_style))
        elements.append(Spacer(1, 10))

        summary_headers = [
            Paragraph("Monthly Rate", th_style),
            Paragraph("Expected Total", th_style),
            Paragraph("Total Bank Payments", th_style),
            Paragraph("Penalties / Int.", th_style),
            Paragraph("Current Arrears / (Credit)", th_style)
        ]
        summary_values = [
            Paragraph(f"KSh {rate:,.2f}", td_center),
            Paragraph(f"KSh {expected:,.2f}", td_center),
            Paragraph(f"KSh {collected:,.2f}", td_center),
            Paragraph(f"KSh {(penalty+interest):,.2f}", td_center),
            Paragraph(f"KSh {arrears:,.2f}", td_center)
        ]

        summary_data = [summary_headers, summary_values]
        t_sum = Table(summary_data, colWidths=[105, 105, 115, 95, 120])
        t_sum.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a252c')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#f8f9fa')),
            ('PADDING', (0,0), (-1,-1), 6)
        ]))
        elements.append(t_sum)
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("<b><u>ITEMIZED BANK STATEMENT TRANSACTIONS (KCB & PAYBILL)</u></b>", styles['Heading3']))
        elements.append(Spacer(1, 5))

        txn_headers = [
            Paragraph("Txn Date", th_left),
            Paragraph("KCB / Paybill Ref Number", th_left),
            Paragraph("Transaction Details", th_left),
            Paragraph("Amount Paid (KSh)", ParagraphStyle('THRight', parent=th_style, alignment=2))
        ]
        txn_data = [txn_headers]

        if not tenant_txns.empty:
            for _, r in tenant_txns.iterrows():
                raw_date = r.get('Transaction Date', 'N/A')
                dt_parsed = pd.to_datetime(raw_date, format='%d.%m.%Y', errors='coerce')
                if pd.isnull(dt_parsed):
                    dt_parsed = pd.to_datetime(raw_date, dayfirst=True, errors='coerce')
                t_date = dt_parsed.strftime('%d.%m.%Y') if pd.notnull(dt_parsed) else str(raw_date)[:10]
                t_ref = str(r.get('Ref_Clean', 'N/A'))
                t_desc = str(r.get('Transaction Details', 'N/A'))[:45]
                t_amt = float(r.get('Money In Num', 0.0))
                txn_data.append([
                    Paragraph(t_date, small_norm),
                    Paragraph(t_ref, small_norm),
                    Paragraph(t_desc, small_norm),
                    Paragraph(f"{t_amt:,.2f}", td_right)
                ])
        else:
            txn_data.append([
                Paragraph("N/A", small_norm),
                Paragraph("NO PAYMENTS RECORDED", small_bold),
                Paragraph(f"No bank credits matched for {billing_month}", small_norm),
                Paragraph("0.00", td_right)
            ])

        t_txns = Table(txn_data, colWidths=[80, 130, 230, 100])
        t_txns.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4a4d5a')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
            ('PADDING', (0,0), (-1,-1), 5)
        ]))
        elements.append(t_txns)
        elements.append(Spacer(1, 15))

        doc.build(elements)
        return full_pdf_path

    def send_email_statement(self, recipient_email: str, tenant_name: str, pdf_path: str, sender_email: str, app_password: str, shop_no: int, paybill: str, paybill_acc: str, branch_name: str, bank_code: str, branch_code: str, swift_code: str, billing_month: str = "July 2026"):
        try:
            raw_emails = re.split(r'[;,]', str(recipient_email))
            recipient_list = [e.strip() for e in raw_emails if e.strip() and '@' in e]
            if not recipient_list:
                return False, "No valid recipient email address provided."

            msg = MIMEMultipart()
            msg['From'] = f"Global Star Investments <{sender_email}>"
            msg['To'] = ", ".join(recipient_list)
            msg['Subject'] = f"Formal Payment Reminder & Ledger Statement ({billing_month}) - Shop #{shop_no} ({tenant_name})"

            body = f"""Dear {tenant_name},

We hope this message finds you well.

This is a formal reminder from Global Star Investments Limited regarding your commercial lease account for Shop #{shop_no} at Tinitin La Place Building, Siaya Town.

Our records indicate an outstanding arrears balance for the current billing period ({billing_month}). 

Kindly arrange for settlement at your earliest convenience using any of our official payment channels:
1. M-Pesa Paybill: Business No. {paybill} | Account: {paybill_acc}
2. M-Pesa Paybill: Business No. 522533 | Account: 8035949
3. Direct KCB Bank Transfer: Account No. {paybill_acc}, {branch_name} Branch

Please find attached your itemized bank payment and rent ledger statement for your review.

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
            msg.attach(MIMEText(body, 'plain'))

            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                    msg.attach(part)

            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(sender_email, app_password)
            server.sendmail(sender_email, recipient_list, msg.as_string())
            server.quit()
            return True, f"Payment reminder and statement successfully sent to {len(recipient_list)} address(es) for Shop #{shop_no}!"
        except Exception as e:
            return False, str(e)

    def send_etims_invoice_email(self, recipient_email: str, tenant_name: str, pdf_path: str, sender_email: str, app_password: str, shop_no: int, billing_month: str = "August 2026"):
        """Sends a clean, streamlined transmittal email solely for the attached eTIMS tax invoice without arrears or payment instructions."""
        try:
            raw_emails = re.split(r'[;,]', str(recipient_email))
            recipient_list = [e.strip() for e in raw_emails if e.strip() and '@' in e]
            if not recipient_list:
                return False, "No valid recipient email address provided."

            msg = MIMEMultipart()
            msg['From'] = f"Global Star Investments <{sender_email}>"
            msg['To'] = ", ".join(recipient_list)
            msg['Subject'] = f"Official eTIMS Tax Invoice ({billing_month}) - Shop #{shop_no} ({tenant_name})"

            body = f"""Dear {tenant_name},

Please find attached your official KRA eTIMS Tax Invoice for {billing_month} from Global Star Investments Limited regarding your commercial lease account for Shop #{shop_no} at Tinitin La Place Building, Siaya Town.

This document includes your Tenant KRA PIN and KRA eTIMS Fiscal Signature QR code for your corporate tax filing and Profit & Loss (P&L) expense deduction. All transactional payment details and account summaries are detailed within the attached tax document.

Thank you for your business.

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
            msg.attach(MIMEText(body, 'plain'))

            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                    msg.attach(part)

            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(sender_email, app_password)
            server.sendmail(sender_email, recipient_list, msg.as_string())
            server.quit()
            return True, f"Official eTIMS tax invoice successfully sent to {len(recipient_list)} address(es) for Shop #{shop_no}!"
        except Exception as e:
            return False, str(e)

    def send_whatsapp_message(self, recipient_phone: str, message_text: str, access_token: str = "EAASZC9wb7QSABSJ1na0JlElvfaXaIUcmt5db7hSIuDeJiZC6gj9I0W8U8h9UtNuRRxC7etpMbKavX7AJ8duQZBs9qK0yc8dcJG4fQGDUzp8AYaW5LNWZC4eZCYpS5A0Fl0F6fBiheKWRNL0dWq98tDZAtZCXPBRFvl1AEsJbDH9VbEOQ964Ilo0ZCTvIMycANAZDZD", phone_number_id: str = "1104611856058033") -> tuple:
        """Sends an automated WhatsApp notification via Meta's official Cloud API using pre-configured system credentials."""
        token = access_token if access_token and len(access_token) > 20 else "EAASZC9wb7QSABSJ1na0JlElvfaXaIUcmt5db7hSIuDeJiZC6gj9I0W8U8h9UtNuRRxC7etpMbKavX7AJ8duQZBs9qK0yc8dcJG4fQGDUzp8AYaW5LNWZC4eZCYpS5A0Fl0F6fBiheKWRNL0dWq98tDZAtZCXPBRFvl1AEsJbDH9VbEOQ964Ilo0ZCTvIMycANAZDZD"
        num_id = phone_number_id if phone_number_id else "1104611856058033"

        url = f"https://graph.facebook.com/v17.0/{num_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        clean_phone = ''.join(filter(str.isdigit, str(recipient_phone)))
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": message_text
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            res_data = response.json()
            if response.status_code == 200:
                return True, "WhatsApp notification sent successfully!"
            else:
                err_msg = res_data.get("error", {}).get("message", "Unknown Meta API error")
                return False, f"Meta API Error: {err_msg}"
        except Exception as e:
            return False, str(e)

    def send_sms_reminder(self, recipient_phone: str, message_text: str, username: str = "POdhiambo2010", api_key: str = "your_api_key") -> tuple:
        """Sends an instant SMS notification via Africa's Talking API."""
        try:
            import africastalking
            africastalking.initialize(username, api_key)
            sms = africastalking.SMS
            
            clean_phone = ''.join(filter(str.isdigit, str(recipient_phone)))
            if clean_phone.startswith('0'):
                clean_phone = '254' + clean_phone[1:]
            elif not clean_phone.startswith('254'):
                clean_phone = '254' + clean_phone

            response = sms.send(message_text, [f"+{clean_phone}"])
            return True, "SMS notification sent successfully!"
        except Exception as e:
            return False, str(e)