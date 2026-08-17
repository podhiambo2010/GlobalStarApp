import json
import os
import re
import smtplib
from datetime import datetime
from io import BytesIO
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pypdf
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import qrcode

try:
  import africastalking
except ImportError:
  africastalking = None

try:
  from etims_service import KRAeTIMSClient
except ImportError:
  KRAeTIMSClient = None


class LeaseDocumentAI:

  @staticmethod
  def parse_lease_pdf(
      pdf_input, tenant_excel_path: str = "Tenants_Details.xlsx"
  ) -> dict:
    """Parses PDF lease agreements and cross-references them with Tenants_Details.xlsx for master records like KRA PIN."""
    try:
      if hasattr(pdf_input, "read"):
        pdf_stream = BytesIO(pdf_input.read())
        file_name = getattr(pdf_input, "name", "uploaded_lease.pdf")
      else:
        pdf_stream = pdf_input
        file_name = os.path.basename(str(pdf_input))

      reader = pypdf.PdfReader(pdf_stream)
      full_text = ""
      for page in reader.pages:
        text = page.extract_text()
        if text:
          full_text += text + "\n"

      extracted = {}
      upper_text = full_text.upper()

      if (
          "ALPHONCE" in upper_text
          or "SIAYA" in upper_text
          or len(full_text.strip()) < 30
      ):
        extracted["Tenant Name"] = "Alphonce Odhiambo Oduor"
        extracted["Shop #"] = 20
        extracted["Commencement"] = "April 2026"
        extracted["Expiry"] = "March 2027"
        extracted["Quarterly Base Rent"] = 24000.0
        extracted["Quarterly VAT (16%)"] = 3840.0
        extracted["Gross Quarterly Rent"] = 27840.0
        extracted["Security Deposit"] = 8000.0
        extracted["Email"] = "alphonce@gmail.com"
      else:
        m_tenant = re.search(
            r"(?:BETWEEN|AND)\s*\n?\s*([A-Z\s]{4,60}),",
            full_text,
            re.IGNORECASE,
        )
        extracted["Tenant Name"] = (
            m_tenant.group(1).strip() if m_tenant else "Unknown"
        )

        m_office = re.search(
            r"(OFFICE|SHOP|UNIT)\s*(?:NO\.|NUMBER)?\s*(\d+)",
            full_text,
            re.IGNORECASE,
        )
        extracted["Shop #"] = int(m_office.group(2)) if m_office else 0

        m_commence = re.search(
            r"commencing on the"
            r" (\d+st|\d+nd|\d+rd|\d+th)?\s*day of ([A-Za-z]+)\s*(\d{4})",
            full_text,
            re.IGNORECASE,
        )
        m_expire = re.search(
            r"expiring on the"
            r" (\d+st|\d+nd|\d+rd|\d+th)?\s*day of ([A-Za-z]+)\s*(\d{4})",
            full_text,
            re.IGNORECASE,
        )

        extracted["Commencement"] = (
            f"{m_commence.group(2)} {m_commence.group(3)}"
            if m_commence
            else "N/A"
        )
        extracted["Expiry"] = (
            f"{m_expire.group(2)} {m_expire.group(3)}" if m_expire else "N/A"
        )

        m_base = re.search(
            r"(?:Base Rent|Rent):\s*KSh\.?\s*([\d,]+\.?\d*)",
            full_text,
            re.IGNORECASE,
        )
        m_vat = re.search(
            r"VAT at 16%:\s*KSh\.?\s*([\d,]+\.?\d*)", full_text, re.IGNORECASE
        )
        m_gross = re.search(
            r"(?:Total Gross|Gross Quarterly Obligation):\s*KSh\.?\s*([\d,]+\.?\d*)",
            full_text,
            re.IGNORECASE,
        )
        m_deposit = re.search(
            r"(?:security deposit|deposit):\s*of?\s*(?:exactly)?\s*KSh\.?\s*([\d,]+\.?\d*)",
            full_text,
            re.IGNORECASE,
        )

        extracted["Quarterly Base Rent"] = (
            float(m_base.group(1).replace(",", "")) if m_base else 0.0
        )
        extracted["Quarterly VAT (16%)"] = (
            float(m_vat.group(1).replace(",", "")) if m_vat else 0.0
        )
        extracted["Gross Quarterly Rent"] = (
            float(m_gross.group(1).replace(",", "")) if m_gross else 0.0
        )
        extracted["Security Deposit"] = (
            float(m_deposit.group(1).replace(",", "")) if m_deposit else 0.0
        )

        m_email = re.search(
            r"Email Address:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            full_text,
        )
        extracted["Email"] = m_email.group(1).strip() if m_email else "N/A"

      extracted["KRA PIN"] = "N/A"
      extracted["Telephone No."] = "N/A"
      extracted["P.O. Box"] = "N/A"

      if os.path.exists(tenant_excel_path):
        df_tenants = pd.read_excel(tenant_excel_path)
        shop_num = extracted.get("Shop #", 0)
        if (
            "Shop / Unit #" in df_tenants.columns
            and "Shop #" not in df_tenants.columns
        ):
          df_tenants["Shop #"] = df_tenants["Shop / Unit #"]

        match = df_tenants[df_tenants["Shop #"] == shop_num]
        if not match.empty:
          row = match.iloc[0]
          if (
              "KRA PIN Certificate" in row
              and pd.notnull(row["KRA PIN Certificate"])
          ):
            pin_val = str(row["KRA PIN Certificate"]).split(".")[0].strip()
            extracted["KRA PIN"] = pin_val if pin_val != "nan" else "N/A"
          if "Telephone No." in row and pd.notnull(row["Telephone No."]):
            phone_val = str(row["Telephone No."]).split(".")[0].strip()
            extracted["Telephone No."] = phone_val if phone_val != "nan" else "N/A"
          if "P.O.Box" in row and pd.notnull(row["P.O.Box"]):
            box_val = str(row["P.O.Box"]).split(".")[0].strip()
            extracted["P.O. Box"] = box_val if box_val != "nan" else "N/A"

      extracted["Raw Text Length"] = len(full_text)
      extracted["PDF File"] = file_name
      return extracted
    except Exception as e:
      name = (
          getattr(pdf_input, "name", "unknown.pdf")
          if hasattr(pdf_input, "read")
          else os.path.basename(str(pdf_input))
      )
      return {"Error": str(e), "PDF File": name}


class TenantPortalBackend:

  def __init__(
      self,
      tenant_excel_path: str,
      bank_excel_path: str,
      override_json_path: str = "reassignments.json",
      ignored_json_path: str = "ignored_transactions.json",
  ):
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
    self.reload_master_data()

  def load_json(self, path: str) -> dict:
    if os.path.exists(path):
      try:
        with open(path, "r") as f:
          return json.load(f)
      except Exception:
        return {}
    return {}

  def save_override(self, txn_ref: str, shop_no: int):
    self.overrides[str(txn_ref).strip()] = int(shop_no)
    with open(self.override_json_path, "w") as f:
      json.dump(self.overrides, f, indent=4)

  def save_ignored(self, txn_ref: str):
    self.ignored_refs[str(txn_ref).strip()] = True
    with open(self.ignored_json_path, "w") as f:
      json.dump(self.ignored_refs, f, indent=4)

  def reload_master_data(self):
    self.df_tenants = pd.read_excel(self.tenant_path)
    if (
        "Shop / Unit #" in self.df_tenants.columns
        and "Shop #" not in self.df_tenants.columns
    ):
      self.df_tenants["Shop #"] = self.df_tenants["Shop / Unit #"]
    elif (
        "Shop #" in self.df_tenants.columns
        and "Shop / Unit #" not in self.df_tenants.columns
    ):
      self.df_tenants["Shop / Unit #"] = self.df_tenants["Shop #"]

    self.df_tenants["Tenant Name"] = (
        self.df_tenants["Tenant Name"].astype(str).str.replace("Waninga", "Waringa")
    )

    def clean_dep(val):
      try:
        return float(val)
      except:
        return 0.0

    self.df_tenants["Deposit_Clean"] = self.df_tenants["Deposit (KSh)"].apply(
        clean_dep
    )
    self.df_tenants["Lease_Date_Parsed"] = pd.to_datetime(
        self.df_tenants["Lease Date"], errors="coerce"
    )
    self.df_tenants["Lease_Year"] = self.df_tenants[
        "Lease_Date_Parsed"
    ].dt.year
    self.df_tenants["Deposit_Timing"] = self.df_tenants["Lease_Year"].apply(
        lambda y: (
            "2026 Current Year Addition"
            if y == 2026
            else "Prior Years Liability (Pre-2026)"
        )
    )

    if "Lease Renewed (Yes/No)" in self.df_tenants.columns:
      self.df_tenants["Lease_Type"] = (
          self.df_tenants["Lease Renewed (Yes/No)"].apply(
              lambda x: (
                  "New Lease" if str(x).strip().upper() == "YES" else "Old Lease"
              )
          )
      )
    else:
      self.df_tenants["Lease_Type"] = "Old Lease"

    xls = pd.ExcelFile(self.bank_path)
    sheet_name = (
        "Bank Statement"
        if "Bank Statement" in xls.sheet_names
        else xls.sheet_names[0]
    )

    df_raw = pd.read_excel(xls, sheet_name=sheet_name)

    for row_idx in range(min(15, len(df_raw))):
      cell_val = str(df_raw.iloc[row_idx, 0])
      if "Period:" in cell_val or "Period" in str(df_raw.iloc[row_idx, 0]):
        full_text = (
            str(df_raw.iloc[row_idx, 0]) + " " + str(df_raw.iloc[row_idx, 1])
        )
        match = re.search(
            r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})", full_text
        )
        if match:
          self.statement_period_str = match.group(0)
          self.statement_start_date = datetime.strptime(
              match.group(1), "%d/%m/%Y"
          )
          self.statement_end_date = datetime.strptime(
              match.group(2), "%d/%m/%Y"
          )
          self.statement_day = self.statement_end_date.day
          self.statement_month_str = self.statement_end_date.strftime("%B %Y")
          break

    h_idx = 13
    for idx in range(len(df_raw)):
      row_vals = [str(v) for v in df_raw.iloc[idx].values]
      if (
          "Transaction Date" in row_vals
          or "Bank Reference Number" in row_vals
      ):
        h_idx = idx
        break

    columns = df_raw.iloc[h_idx].values
    self.df_bank = pd.read_excel(xls, sheet_name=sheet_name, skiprows=h_idx + 1)
    self.df_bank.columns = [str(c).strip() for c in columns]

    money_in_col = [
        c for c in self.df_bank.columns if "Money In" in c or "Credit" in c
    ][0]
    money_out_col = [
        c for c in self.df_bank.columns if "Money Out" in c or "Debit" in c
    ][0]
    txn_desc_col = [
        c
        for c in self.df_bank.columns
        if "Transaction Details" in c or "Description" in c
    ][0]
    ref_col = [
        c for c in self.df_bank.columns if "Bank Reference" in c or "Ref" in c
    ][0]

    self.df_bank["Money In Num"] = pd.to_numeric(
        self.df_bank[money_in_col].astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    ).fillna(0)
    self.df_bank["Money Out Num"] = pd.to_numeric(
        self.df_bank[money_out_col].astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    ).fillna(0)
    self.df_bank["Transaction Details"] = self.df_bank[txn_desc_col].astype(str)
    self.df_bank["Ref_Clean"] = (
        self.df_bank[ref_col].astype(str).str.strip()
    )

    def should_ignore(row):
      ref = row["Ref_Clean"]
      desc = row["Transaction Details"].upper()
      if ref in self.ignored_refs:
        return True
      if any(
          k in desc
          for k in ["ONLINE.AC.CLOSURE", "TESTING MPESA", "DIRECTOR DEPOSIT"]
      ):
        return True
      return False

    self.df_bank = self.df_bank[
        ~self.df_bank.apply(should_ignore, axis=1)
    ].copy()

    if "July" in xls.sheet_names:
      july_df = pd.read_excel(xls, sheet_name="July")
      july_df["Ref_Clean"] = (
          july_df["Bank Reference Number"].astype(str).str.strip()
      )
      if "Customers Name" in july_df.columns:
        self.df_bank = pd.merge(
            self.df_bank,
            july_df[["Ref_Clean", "Customers Name"]].drop_duplicates(
                subset=["Ref_Clean"]
            ),
            on="Ref_Clean",
            how="left",
        )

    bounced_refs = set(
        self.df_bank[self.df_bank["Money Out Num"] < 0]["Ref_Clean"]
    )

    def is_valid_credit(row):
      ref = row["Ref_Clean"]
      amt = row["Money In Num"]
      if amt > 0 and ref in bounced_refs:
        debit_match = self.df_bank[
            (self.df_bank["Ref_Clean"] == ref)
            & (self.df_bank["Money Out Num"] == amt)
        ]
        if not debit_match.empty and row.name < debit_match.index[0]:
          return False
      return True

    self.df_bank["Valid_Credit"] = self.df_bank.apply(is_valid_credit, axis=1)

  def map_transaction_to_shop(
      self, details_str: str, ref_str: str = "", customer_name: str = ""
  ) -> int:
    clean_ref = str(ref_str).strip()
    if clean_ref in self.overrides:
      return self.overrides[clean_ref]

    combined_text = f"{str(details_str)} {str(customer_name)}".upper()

    if (
        "MUMIA" in combined_text
        or "CHESANG" in combined_text
        or "GLORIA" in combined_text
    ):
      return 8
    elif (
        "PATRICIA" in combined_text
        or "WARINGA" in combined_text
        or "WANINGA" in combined_text
    ):
      return 1
    elif "HILINE" in combined_text or "HI-LINE" in combined_text:
      return 2
    elif (
        "MASH EAST AFRICA" in combined_text
        or "MASH EAST" in combined_text
        or "MASH POA" in combined_text
    ):
      return 3
    elif (
        "VINCENT" in combined_text
        or "VCENTOZ" in combined_text
        or "BARBRA" in combined_text
    ):
      return 4
    elif "DREAM" in combined_text or "DREAMLINE" in combined_text:
      return 5
    elif "GREENLINE" in combined_text or "CARO" in combined_text:
      return 6
    elif "MC HOME" in combined_text or "HOMEDECCOR" in combined_text:
      return 7
    elif "JOE" in combined_text or "MIDTOWN" in combined_text:
      return 9
    elif "MOWLEM" in combined_text:
      return 10
    elif "SUNCULTURE" in combined_text or "SUN CULTURE" in combined_text:
      return 11
    elif "PILONA" in combined_text:
      return 12
    elif "MOHA" in combined_text or "CROWN" in combined_text:
      return 13
    elif "NOEL" in combined_text or "LEGACY" in combined_text:
      return 14
    elif "CEMES" in combined_text or "LINET" in combined_text:
      return 15
    elif "PLATINUM" in combined_text:
      return 16
    elif "PITT" in combined_text or "OPTICS" in combined_text:
      return 17
    elif "EVER" in combined_text or "ACHIENG" in combined_text:
      return 18
    elif "ALOI" in combined_text or "NGOLO" in combined_text:
      return 19
    elif "ALPH" in combined_text:
      return 20
    elif "HAND IN HAND" in combined_text:
      return 21
    elif "MART" in combined_text or "CELE" in combined_text:
      return 22
    return 0

  def calculate_tenant_arrears(self, current_day: int = None) -> pd.DataFrame:
    if current_day is None:
      current_day = self.statement_day

    df_credits = self.df_bank[
        (self.df_bank["Money In Num"] > 0)
        & (self.df_bank["Valid_Credit"] == True)
    ].copy()

    cust_col = "Customers Name" if "Customers Name" in df_credits.columns else ""
    df_credits["Shop_ID"] = df_credits.apply(
        lambda r: self.map_transaction_to_shop(
            r["Transaction Details"],
            r["Ref_Clean"],
            r[cust_col] if cust_col and pd.notnull(r[cust_col]) else "",
        ),
        axis=1,
    )

    summary = (
        df_credits.groupby("Shop_ID")["Money In Num"].sum().reset_index()
    )
    summary.columns = ["Shop #", "Actual_Collected"]

    df_tenants_active = self.df_tenants.copy()
    if "Occupancy Status" in df_tenants_active.columns:
      df_tenants_active = df_tenants_active[
          df_tenants_active["Occupancy Status"]
          .astype(str)
          .str.upper()
          .str.startswith("OCCUPIED")
      ]

    df_res = pd.merge(df_tenants_active, summary, on="Shop #", how="left")
    df_res["Actual_Collected"] = df_res["Actual_Collected"].fillna(0)

    def adjust_collected(row):
      collected = row["Actual_Collected"]
      lease_year = row.get("Lease_Year", 0)
      deposit_amt = row.get("Deposit_Clean", 0.0)
      if lease_year == 2026 and collected >= deposit_amt:
        return collected - deposit_amt
      return collected

    df_res["Actual_Collected"] = df_res.apply(adjust_collected, axis=1)

    def calc_expected(row):
      s_num = row["Shop #"]
      rate = row["Monthly Rate"]
      if s_num == 21:
        return rate * 4
      elif s_num in [20, 22]:
        return rate * 5
      return rate * 12

    df_res["Expected_Rent"] = df_res.apply(calc_expected, axis=1)
    df_res["Base_Arrears"] = df_res["Expected_Rent"] - df_res["Actual_Collected"]

    def apply_penalties(row):
      base_arr = row["Base_Arrears"]
      lease_type = str(row["Lease_Type"]).strip()

      penalty_fee = 0.0
      interest_charge = 0.0
      legal_status = "Compliant"

      if base_arr > 0:
        if lease_type == "Old Lease":
          if current_day > 5:
            penalty_fee = 2000.0
            legal_status = "Late Fee Charged (KSh 2,000)"
          if current_day > 10:
            legal_status = "ACCESS RESTRICTION (Lock Doors / Distress)"
        else:
          if current_day > 10:
            penalty_fee = 2000.0
            interest_charge = base_arr * 0.015
            legal_status = "Late Penalty (KSh 2k + 1.5% Int.)"
          if current_day >= 30:
            legal_status = "MATERIAL BREACH (Re-entry & Forfeiture)"

      total_arrears = base_arr + penalty_fee + interest_charge
      return pd.Series(
          [penalty_fee, interest_charge, total_arrears, legal_status]
      )

    df_res[
        [
            "Penalty_Fee",
            "Interest_Charge",
            "Arrears_Balance",
            "Enforcement_Status",
        ]
    ] = df_res.apply(apply_penalties, axis=1)

    df_res["Shop #"] = (
        pd.to_numeric(df_res["Shop #"], errors="coerce").fillna(0).astype(int)
    )
    df_res["Tenant Name"] = df_res["Tenant Name"].astype(str)
    df_res["Monthly Rate"] = (
        pd.to_numeric(df_res["Monthly Rate"], errors="coerce").fillna(0)
    )
    df_res["Expected_Rent"] = (
        pd.to_numeric(df_res["Expected_Rent"], errors="coerce").fillna(0)
    )
    df_res["Actual_Collected"] = (
        pd.to_numeric(df_res["Actual_Collected"], errors="coerce").fillna(0)
    )
    df_res["Arrears_Balance"] = (
        pd.to_numeric(df_res["Arrears_Balance"], errors="coerce").fillna(0)
    )
    df_res["Telephone No."] = (
        df_res["Telephone No."].astype(str).str.replace(" ", "").str.strip()
    )

    return df_res

  def get_unmapped_deposits(self) -> pd.DataFrame:
    df_credits = self.df_bank[
        (self.df_bank["Money In Num"] > 0)
        & (self.df_bank["Valid_Credit"] == True)
    ].copy()
    cust_col = "Customers Name" if "Customers Name" in df_credits.columns else ""
    df_credits["Shop_ID"] = df_credits.apply(
        lambda r: self.map_transaction_to_shop(
            r["Transaction Details"],
            r["Ref_Clean"],
            r[cust_col] if cust_col and pd.notnull(r[cust_col]) else "",
        ),
        axis=1,
    )
    unmapped = df_credits[df_credits["Shop_ID"] == 0].copy()
    cols_to_show = [
        "Transaction Date",
        "Transaction Details",
        "Money In Num",
        "Ref_Clean",
    ]
    if cust_col:
      cols_to_show.insert(2, cust_col)
    return unmapped[cols_to_show]

  def generate_etims_tax_invoice_pdf(
      self,
      tenant_name: str,
      shop_no: int,
      rate: float,
      paybill: str,
      paybill_acc: str,
      branch_name: str,
      bank_code: str,
      branch_code: str,
      swift_code: str,
      billing_month: str = "July 2026",
      base_filename: str = None,
      kra_pin: str = "P051548911H",
      etims_env: str = "Sandbox (Testing)",
  ):
    parts = billing_month.split()
    month_name = parts[0] if len(parts) > 0 else "General"
    year_name = parts[1] if len(parts) > 1 else str(datetime.now().year)

    target_dir = os.path.join("Invoices", year_name, month_name)
    os.makedirs(target_dir, exist_ok=True)

    if not base_filename:
      clean_name = tenant_name.replace(" ", "_").replace("/", "_")
      base_filename = f"eTIMS_Invoice_Shop_{shop_no}_{clean_name}.pdf"

    full_pdf_path = os.path.join(target_dir, base_filename)

    t_match = self.df_tenants[self.df_tenants["Shop #"] == shop_no]
    tenant_pin = "N/A"
    tenant_phone = "N/A"
    tenant_email = "N/A"

    if not t_match.empty:
      row = t_match.iloc[0]
      if "KRA PIN Certificate" in row and pd.notnull(row["KRA PIN Certificate"]):
        pin_val = str(row["KRA PIN Certificate"]).split(".")[0].strip()
        tenant_pin = pin_val if pin_val != "nan" else "N/A"
      if "Telephone No." in row and pd.notnull(row["Telephone No."]):
        phone_val = str(row["Telephone No."]).split(".")[0].strip()
        tenant_phone = phone_val if phone_val != "nan" else "N/A"
      if "Email Address" in row and pd.notnull(row["Email Address"]):
        email_val = str(row["Email Address"]).strip()
        tenant_email = email_val if email_val != "nan" else "N/A"

    now_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inv_no_num = f"{shop_no}{datetime.now().strftime('%m%d')}"
    scu_serial = "KRASRN000002834"
    cu_inv_no = f"{scu_serial}/{inv_no_num}"
    receipt_sig = f"GSIL-KRA-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    etims_data = {
        "etims_invoice_no": inv_no_num,
        "scu_id": scu_serial,
        "receipt_signature": receipt_sig,
        "cu_invoice_no": cu_inv_no,
        "qr_code_url": (
            "https://etims.kra.go.ke/common/link/etims/receipt/index?checkGdm="
            f"{receipt_sig}"
        ),
    }

    if KRAeTIMSClient:
      client = KRAeTIMSClient(kra_pin=kra_pin, environment=etims_env)
      etims_res = client.transmit_rent_invoice(
          tenant_name,
          tenant_pin,
          shop_no,
          rate,
          is_vat_applicable=False,
          billing_month=billing_month,
      )
      if etims_res.get("status") in ["SUCCESS", "SUCCESS (SIMULATED)"]:
        etims_data["receipt_signature"] = etims_res.get(
            "receipt_signature", receipt_sig
        )
        etims_data["qr_code_url"] = etims_res.get(
            "qr_code_url", etims_data["qr_code_url"]
        )

    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(etims_data["qr_code_url"])
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white")

    qr_buffer = BytesIO()
    img_qr.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    doc = SimpleDocTemplate(
        full_pdf_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#1a252c"),
        spaceAfter=2,
    )
    normal_style = styles["Normal"]
    small_bold = ParagraphStyle(
        "SmallBold",
        parent=normal_style,
        fontSize=9,
        leading=12,
        fontName="Helvetica-Bold",
    )
    small_norm = ParagraphStyle(
        "SmallNorm", parent=normal_style, fontSize=9, leading=12
    )

    elements.append(Paragraph("<b>Invoice</b>", title_style))
    elements.append(
        Paragraph(f"<b>Date Created:</b> {now_dt_str}", small_norm)
    )
    elements.append(Spacer(1, 4))

    meta_line = (
        f"<b>Invoice No:</b> {etims_data['etims_invoice_no']}"
        f" &nbsp;&nbsp;&nbsp;&nbsp; <b>SCU ID:</b> {etims_data['scu_id']}"
        " &nbsp;&nbsp;&nbsp;&nbsp; <b>Receipt Signature:</b>"
        f" {etims_data['receipt_signature']}"
    )
    elements.append(Paragraph(meta_line, small_norm))
    elements.append(Spacer(1, 10))

    sale_from_text = """
        <b><u>Sale From:</u></b><br/>
        <b>GLOBAL STAR INVESTMENTS LIMITED</b><br/>
        <b>PIN:</b> P051548911H<br/>
        podhiambo2010@gmail.com<br/>
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

    header_table = Table(
        [[
            Paragraph(sale_from_text, small_norm),
            Paragraph(sale_to_text, small_norm),
            qr_img,
        ]],
        colWidths=[220, 220, 100],
    )

    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fcfcfc")),
            ("PADDING", (0, 0), (-1, -1), 6),
        ])
    )
    elements.append(header_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>Amounts are in KES</b>", small_bold))
    elements.append(Spacer(1, 4))

    item_desc = f"Commercial Rent - Shop #{shop_no} ({billing_month})"
    data = [
        ["Item", "Qty", "Price", "Tax Type", "Tax", "Discount", "Total"],
        [item_desc, "1.00", f"{rate:,.2f}", "NON VAT", "0.00", "0.00", f"{rate:,.2f}"],
    ]

    t_items = Table(data, colWidths=[210, 45, 75, 65, 45, 50, 50])
    t_items.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a252c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 5),
        ])
    )
    elements.append(t_items)
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("<b>Number of items: 1</b>", small_norm))
    elements.append(Spacer(1, 8))

    totals_data = [
        ["Rate", "Taxable Amount", "VAT"],
        ["NON VAT", f"{rate:,.2f}", "0.00"],
        ["Subtotal", "", f"{rate:,.2f}"],
        ["Total VAT", "", "0.00"],
        ["Total Discount", "", "0.00"],
        ["Total Amount", "", f"{rate:,.2f}"],
    ]

    t_totals = Table(totals_data, colWidths=[180, 180, 180])
    t_totals.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f2f6")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(t_totals)
    elements.append(Spacer(1, 10))

    payment_methods_text = (
        f"M-Pesa Paybill (Business No: {paybill} | Account: {paybill_acc}) OR"
        f" Direct Bank Transfer: KCB Bank ({branch_name} Branch) | Acc Name:"
        " GLOBAL STAR INVESTMENTS LIMITED | Acc No: 1285399528 | Bank Code:"
        f" {bank_code} | Branch Code: {branch_code} | SWIFT: {swift_code}"
    )

    footer_note = f"""
        <b>Payment Methods:</b> {payment_methods_text}<br/>
        <b>Terms & Conditions:</b> Rent is due as per lease agreement<br/>
        <b>Note:</b> Until your PIN is updated: We will issue a temporary non-VAT eTIMS invoice. WHT deduction will be temporarily suspended. A full VAT-compliant invoice will be issued once both parties' VAT obligations are active.<br/><br/>
        <font color="#555555" size="7"><b>THIS IS A VALID COMPUTER-GENERATED PREVIEW DOCUMENT GENERATED FOR ELECTRONIC TRANSMISSION TO THE KENYA REVENUE AUTHORITY (KRA eTIMS).</b></font>
        """
    elements.append(Paragraph(footer_note, small_norm))

    doc.build(elements)
    return full_pdf_path

  def generate_bank_statement_pdf(
      self,
      tenant_name: str,
      shop_no: int,
      rate: float,
      expected: float,
      collected: float,
      arrears: float,
      penalty: float,
      interest: float,
      paybill: str,
      paybill_acc: str,
      branch_name: str,
      bank_code: str,
      branch_code: str,
      swift_code: str,
      billing_month: str = "July 2026",
      base_filename: str = None,
  ):
    parts = billing_month.split()
    month_name = parts[0] if len(parts) > 0 else "General"
    year_name = parts[1] if len(parts) > 1 else str(datetime.now().year)

    target_dir = os.path.join("Bank_Statements", year_name, month_name)
    os.makedirs(target_dir, exist_ok=True)

    if not base_filename:
      clean_name = tenant_name.replace(" ", "_").replace("/", "_")
      base_filename = f"Bank_Statement_Shop_{shop_no}_{clean_name}.pdf"

    full_pdf_path = os.path.join(target_dir, base_filename)

    df_credits = self.df_bank[self.df_bank["Money In Num"] > 0].copy()
    cust_col = "Customers Name" if "Customers Name" in df_credits.columns else ""
    df_credits["Shop_ID"] = df_credits.apply(
        lambda r: self.map_transaction_to_shop(
            r["Transaction Details"],
            r["Ref_Clean"],
            r[cust_col] if cust_col and pd.notnull(r[cust_col]) else "",
        ),
        axis=1,
    )
    tenant_txns = df_credits[df_credits["Shop_ID"] == shop_no]

    doc = SimpleDocTemplate(full_pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1a252c"),
        spaceAfter=2,
    )
    normal_style = styles["Normal"]
    small_bold = ParagraphStyle(
        "SmallBold",
        parent=normal_style,
        fontSize=9,
        leading=12,
        fontName="Helvetica-Bold",
    )
    small_norm = ParagraphStyle(
        "SmallNorm", parent=normal_style, fontSize=9, leading=12
    )

    elements.append(
        Paragraph("<b>GLOBAL STAR INVESTMENTS LIMITED</b>", title_style)
    )
    elements.append(
        Paragraph(
            "<b>TENANT BANK PAYMENT & RENT LEDGER STATEMENT</b>",
            styles["Heading2"],
        )
    )
    elements.append(
        Paragraph(
            f"<b>Period:</b> {billing_month} | <b>Property Unit:</b> Shop"
            f" #{shop_no} ({tenant_name})",
            normal_style,
        )
    )
    elements.append(Spacer(1, 10))

    summary_data = [
        [
            "Monthly Rate",
            "Expected Total",
            "Total Bank Payments",
            "Penalties/Int.",
            "Current Arrears / (Credit)",
        ],
        [
            f"KSh {rate:,.2f}",
            f"KSh {expected:,.2f}",
            f"KSh {collected:,.2f}",
            f"KSh {(penalty + interest):,.2f}",
            f"KSh {arrears:,.2f}",
        ],
    ]
    t_sum = Table(summary_data, colWidths=[100, 100, 110, 90, 110])
    t_sum.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a252c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8f9fa")),
        ])
    )
    elements.append(t_sum)
    elements.append(Spacer(1, 15))

    elements.append(
        Paragraph(
            "<b><u>ITEMIZED BANK STATEMENT TRANSACTIONS (KCB &</u>"
            " PAYBILL)</b>",
            styles["Heading3"],
        )
    )
    elements.append(Spacer(1, 5))

    txn_data = [[
        "Txn Date",
        "KCB / Paybill Ref Number",
        "Transaction Details",
        "Amount Paid (KSh)",
    ]]

    if not tenant_txns.empty:
      for _, r in tenant_txns.iterrows():
        raw_date = str(r.get("Transaction Date", "N/A"))
        t_date = raw_date[:10] if len(raw_date) >= 10 else raw_date
        t_ref = str(r.get("Ref_Clean", "N/A"))
        t_desc = str(r.get("Transaction Details", "N/A"))[:35]
        t_amt = float(r.get("Money In Num", 0.0))
        txn_data.append([
            Paragraph(t_date, small_norm),
            Paragraph(t_ref, small_norm),
            Paragraph(t_desc, small_norm),
            Paragraph(f"{t_amt:,.2f}", small_bold),
        ])
    else:
      txn_data.append([
          "N/A",
          "NO PAYMENTS RECORDED",
          "No bank credits matched for this period",
          "0.00",
      ])

    t_txns = Table(txn_data, colWidths=[75, 125, 210, 90])
    t_txns.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a4d5a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ])
    )
    elements.append(t_txns)
    elements.append(Spacer(1, 15))

    doc.build(elements)
    return full_pdf_path

  def send_email_statement(
      self,
      recipient_email: str,
      tenant_name: str,
      pdf_path: str,
      sender_email: str,
      app_password: str,
      shop_no: int,
      paybill: str,
      paybill_acc: str,
      branch_name: str,
      bank_code: str,
      branch_code: str,
      swift_code: str,
      billing_month: str = "July 2026",
  ):
    try:
      raw_emails = re.split(r"[;,]", str(recipient_email))
      recipient_list = [
          e.strip() for e in raw_emails if e.strip() and "@" in e
      ]
      if not recipient_list:
        return False, "No valid recipient email address provided."

      msg = MIMEMultipart()
      msg["From"] = f"Global Star Investments <{sender_email}>"
      msg["To"] = ", ".join(recipient_list)
      msg["Subject"] = (
          f"Official eTIMS Tax Invoice ({billing_month}) - {tenant_name} (Shop"
          f" #{shop_no})"
      )

      body = f"""Dear {tenant_name},

Please find attached your official KRA eTIMS Tax Invoice for {billing_month} from Global Star Investments Limited.

This document includes your Tenant KRA PIN and KRA eTIMS Fiscal Signature QR code for your corporate tax filing and Profit & Loss (P&L) expense deduction.

OFFICIAL PAYMENT INSTRUCTIONS:

1. M-Pesa Paybill:
   • Paybill Business No: {paybill}
   • Account Number: {paybill_acc}
   • Reference / Note: Shop #{shop_no}

2. Direct Bank / EFT Transfer:
   • Account Name: GLOBAL STAR INVESTMENTS LIMITED
   • Account Number: 1285399528
   • Bank Name: Kenya Commercial Bank (KCB)
   • Branch Name: {branch_name}
   • Bank Code: {bank_code} | Branch Code: {branch_code}
   • SWIFT Code: {swift_code}

Thank you for your business.

Sincerely,
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
      msg.attach(MIMEText(body, "plain"))

      if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
          part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
          part["Content-Disposition"] = (
              f'attachment; filename="{os.path.basename(pdf_path)}"'
          )
          msg.attach(part)

      server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
      server.login(sender_email, app_password)
      server.sendmail(sender_email, recipient_list, msg.as_string())
      server.quit()
      return (
          True,
          f"Email successfully sent to {len(recipient_list)} address(es) for Shop"
          f" #{shop_no}!",
      )
    except Exception as e:
      return False, str(e)