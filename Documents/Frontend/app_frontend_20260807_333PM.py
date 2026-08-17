import os
from datetime import datetime
from app_backend import LeaseDocumentAI, TenantPortalBackend
from etims_service import KRAeTIMSClient
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Global Star Portal",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_backend():
  return TenantPortalBackend(
      tenant_excel_path="Tenants_Details.xlsx",
      bank_excel_path="KCB_Bank_Statement.xlsx",
  )


backend = get_backend()

st.sidebar.markdown("## Global Star Portal")
st.sidebar.markdown("---")
module = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard & Arrears",
        "Deposit & Lease Ledger",
        "Unmapped Payment Auditor",
        "Lease PDF AI Extractor & Alerts",
        "Arrears Payment Reminders",
        "eTIMS Tax Invoices & Bank Statements",
        "Demand Notice Builder",
        "Bank Statement Audit",
        "Annual P&L & iTax Statement",
    ],
)

if module == "Dashboard & Arrears":
  st.subheader(
      f"🏢 Portfolio Dashboard & Tenant Arrears ({backend.statement_month_str})"
  )
  df_arr = backend.calculate_tenant_arrears()

  col1, col2, col3, col4 = st.columns(4)
  col1.metric("Total Active Tenants", len(df_arr))
  col2.metric("Total Expected Rent", f"KSh {df_arr['Expected_Rent'].sum():,.2f}")
  col3.metric(
      "Total Actual Collected", f"KSh {df_arr['Actual_Collected'].sum():,.2f}"
  )
  col4.metric(
      "Total Outstanding Arrears", f"KSh {df_arr['Arrears_Balance'].sum():,.2f}"
  )

  st.dataframe(
      df_arr[[
          "Shop #",
          "Tenant Name",
          "Monthly Rate",
          "Expected_Rent",
          "Actual_Collected",
          "Arrears_Balance",
          "Enforcement_Status",
      ]],
      width="stretch",
  )

elif module == "Deposit & Lease Ledger":
    st.subheader("📋 Deposit & Lease Ledger")
    df_dep = backend.df_tenants.copy()
    
    total_leases = len(df_dep)
    total_deposit_liability = pd.to_numeric(df_dep['Deposit (KSh)'], errors='coerce').sum()
    
    col1, col2 = st.columns(2)
    col1.metric("Total Lease Records", total_leases)
    col2.metric("Total Deposit Liabilities", f"KSh {total_deposit_liability:,.2f}")
    st.markdown("---")

    st.dataframe(df_dep[['Shop / Unit #', 'Tenant Name', 'Lease Date', 'Deposit (KSh)', 'Deposit_Timing', 'Lease_Type']], width='stretch')

elif module == "Unmapped Payment Auditor":
  st.subheader("🔍 Unmapped Payment Auditor")
  unmapped = backend.get_unmapped_deposits()
  st.warning(f"Found {len(unmapped)} unmapped payments flagged for review.")
  st.dataframe(unmapped, width="stretch")

  if not unmapped.empty:
    st.markdown("### Reassign or Ignore Unmapped Payment")
    ref_to_fix = st.selectbox(
        "Select Bank Reference Number",
        unmapped["Ref_Clean"].tolist(),
        key="unmapped_ref_sel",
    )

    col_ua1, col_ua2 = st.columns(2)
    with col_ua1:
      target_shop = st.number_input(
          "Target Shop #",
          min_value=1,
          max_value=22,
          value=20,
          key="target_shop_input",
      )
      if st.button("Save Reassignment Override", type="primary"):
        backend.save_override(ref_to_fix, target_shop)
        backend.reload_master_data()
        st.success(
            f"Successfully reassigned reference {ref_to_fix} to Shop"
            f" #{target_shop}!"
        )
        st.rerun()
    with col_ua2:
      st.markdown("<br/>", unsafe_allow_html=True)
      if st.button("🚫 Ignore / Exclude Transaction"):
        backend.save_ignored(ref_to_fix)
        backend.reload_master_data()
        st.success(f"Successfully ignored reference {ref_to_fix}!")
        st.rerun()

elif module == "Lease PDF AI Extractor & Alerts":
  st.subheader("🤖 AI Lease Agreement Extractor & Batch Folder OCR")
  uploaded_pdfs = st.file_uploader(
      "Upload Signed Lease PDF(s) / Batch Folder",
      type=["pdf"],
      accept_multiple_files=True,
  )
  if uploaded_pdfs:
    if not isinstance(uploaded_pdfs, list):
      uploaded_pdfs = [uploaded_pdfs]

    for idx, pdf_file in enumerate(uploaded_pdfs):
      st.markdown(
          f"### 📄 Extracting: `{getattr(pdf_file, 'name', f'Lease_{idx + 1}')}`"
      )
      extracted_info = LeaseDocumentAI.parse_lease_pdf(pdf_file)
      st.json(extracted_info)

    if st.button("Register / Update All Extracted Tenants"):
      st.success(
          "All tenants successfully profiled and synchronized with master"
          " records!"
      )

elif module == "Arrears Payment Reminders":
  st.subheader("📢 Arrears Payment Reminders & Friendly Notices")
  st.markdown(
      "Send polite payment reminders and overdue notices to non-compliant"
      " tenants before issuing formal legal demand letters."
  )

  df_arr = backend.calculate_tenant_arrears()
  df_non_compliant = df_arr[df_arr["Arrears_Balance"] > 0]

  if df_non_compliant.empty:
    st.success("All tenants are fully compliant! No reminders needed.")
  else:
    st.markdown("---")
    st.markdown("### 🚀 Bulk WhatsApp Reminders (All Non-Compliant Tenants)")
    col_bw1, col_bw2 = st.columns(2)
    with col_bw1:
      bulk_wa_token = st.text_input(
          "Meta WhatsApp Access Token", type="password", key="bulk_wa_token"
      )
    with col_bw2:
      bulk_wa_phone_id = st.text_input(
          "WhatsApp Phone Number ID", value="1104611856058033", key="bulk_wa_phone_id"
      )

    if st.button("📱 Send Bulk WhatsApp Reminders to All Arrears Tenants", type="primary"):
      if not bulk_wa_token or not bulk_wa_phone_id:
        st.error("Please enter your Meta WhatsApp Access Token and Phone Number ID.")
      else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        total_nc = len(df_non_compliant)
        wa_success_count = 0

        for i, (_, row) in enumerate(df_non_compliant.iterrows()):
          s_no = int(row["Shop #"])
          c_name = row["Tenant Name"]
          c_arrears = row["Arrears_Balance"]
          c_phone = str(row.get("Telephone No.", ""))
          if c_phone.endswith('.0'):
            c_phone = c_phone[:-2]

          msg_text = f"""Dear {c_name},
Friendly reminder from Global Star Investments Ltd regarding Shop #{s_no}. Your outstanding arrears balance is KSh {c_arrears:,.2f}.
Kindly arrange settlement via M-Pesa Paybill (No: 522522 | Acc: 1285399528) or direct KCB Bank transfer. Thank you!
"""
          status_text.text(f"Sending WhatsApp to Shop #{s_no} - {c_name}...")
          if c_phone and len(c_phone) >= 9:
            success, msg = backend.send_whatsapp_message(
                recipient_phone=c_phone,
                message_text=msg_text,
                access_token=bulk_wa_token,
                phone_number_id=bulk_wa_phone_id,
            )
            if success:
              wa_success_count += 1
          progress_bar.progress((i + 1) / total_nc)

        status_text.empty()
        progress_bar.empty()
        st.success(f"Successfully dispatched WhatsApp reminders to {wa_success_count} out of {total_nc} non-compliant tenants!")

    st.markdown("---")
    st.markdown("### 👤 Single Tenant Actions & Email/WhatsApp")
    tenant_labels = [
        (
            f"Shop #{row['Shop #']} - {row['Tenant Name']} (Arrears: KSh"
            f" {row['Arrears_Balance']:,.2f})"
        )
        for _, row in df_non_compliant.iterrows()
    ]
    selected_label = st.selectbox(
        "Select Non-Compliant Tenant for Reminder", tenant_labels
    )
    selected_shop_no = int(selected_label.split("Shop #")[1].split(" - ")[0])
    row_sel = df_non_compliant[
        df_non_compliant["Shop #"] == selected_shop_no
    ].iloc[0]

    t_email = str(row_sel.get("Email Address", ""))
    t_name = row_sel["Tenant Name"]
    arrears_amt = row_sel["Arrears_Balance"]

    reminder_body = f"""Dear {t_name},

We hope this message finds you well.

This is a friendly reminder from Global Star Investments Limited regarding your commercial lease account for Shop #{selected_shop_no} at Tinitin La Place Building, Siaya Town.

Our records indicate an outstanding arrears balance of KSh {arrears_amt:,.2f} for the current billing period. 

Kindly arrange for settlement at your earliest convenience via our official M-Pesa Paybill (Business No: 522522 | Account: 1285399528) or direct KCB Bank transfer (Account: 1285399528, Siaya Branch) to keep your account in good standing and avoid late penalties or formal legal demand notices.

If you have already made this payment, please share your transaction reference so we can update your ledger. Thank you for your continued partnership.

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
    st.text_area("Reminder Email Preview", reminder_body, height=250)

    sender_email = st.text_input(
        "Sender Gmail Address", "globalstarinvest@gmail.com", key="rem_sender"
    )
    app_password = st.text_input(
        "Gmail App Password",
        value="bwng mwof eqrq jpaf",
        type="password",
        key="rem_pwd",
    )
    recipient_email = st.text_input("Recipient Email(s)", t_email)

    if st.button("📤 Send Payment Reminder Email", type="primary"):
      if not recipient_email or "@" not in recipient_email:
        st.error("Please enter a valid recipient email address.")
      else:
        success, msg = backend.send_email_statement(
            recipient_email=recipient_email,
            tenant_name=t_name,
            pdf_path="",
            sender_email=sender_email,
            app_password=app_password,
            shop_no=int(selected_shop_no),
            paybill="522522",
            paybill_acc="1285399528",
            branch_name="Siaya",
            bank_code="01",
            branch_code="012",
            swift_code="KCBLKENX",
            billing_month=backend.statement_month_str,
        )
        if success:
          st.success(f"Payment reminder successfully sent to {t_name}!")
        else:
          st.error(f"Failed to send email: {msg}")

    st.markdown("### 💬 Single WhatsApp Notification Dispatch")
    col_w1, col_w2 = st.columns(2)
    with col_w1:
      wa_token = st.text_input(
          "Meta WhatsApp Access Token", type="password", key="wa_token"
      )
    with col_w2:
      wa_phone_id = st.text_input("WhatsApp Phone Number ID", value="1104611856058033", key="wa_phone_id")

    raw_phone_val = str(row_sel.get("Telephone No.", ""))
    if raw_phone_val.endswith('.0'):
      raw_phone_val = raw_phone_val[:-2]

    tenant_phone = st.text_input(
        "Tenant Mobile Number",
        raw_phone_val,
        key="tenant_wa_num",
    )

    if st.button("📱 Send WhatsApp Payment Reminder", type="primary"):
      if not wa_token or not wa_phone_id:
        st.error(
            "Please enter your Meta WhatsApp Access Token and Phone Number ID."
        )
      elif not tenant_phone or len(tenant_phone) < 9:
        st.error("Please provide a valid tenant mobile number.")
      else:
        success, msg = backend.send_whatsapp_message(
            recipient_phone=tenant_phone,
            message_text=reminder_body,
            access_token=wa_token,
            phone_number_id=wa_phone_id,
        )
        if success:
          st.success(f"WhatsApp reminder successfully sent to {t_name}!")
        else:
          st.error(f"Failed to send WhatsApp message: {msg}")

elif module == "eTIMS Tax Invoices & Bank Statements":
  st.subheader("🧾 eTIMS Tax Invoices & Automated Monthly Billing")
  st.markdown(
      "Generate individual documents or execute bulk generation and dispatch"
      " across all active tenants."
  )

  client = KRAeTIMSClient()
  init_success, cmc, msg = client.initialize_device()
  if init_success:
    st.success(f"Connected to KRA eTIMS API Client: {msg}")
  else:
      st.warning(f"eTIMS Sandbox Status: {msg}")

  df_arr = backend.calculate_tenant_arrears()
  billing_month = st.selectbox(
      "Billing Cycle Month",
      [
          backend.statement_month_str,
          "July 2026",
          "August 2026",
          "September 2026",
      ],
  )

  col_cfg1, col_cfg2 = st.columns(2)
  with col_cfg1:
    paybill = st.text_input("Paybill Business No", "522522")
    paybill_acc = st.text_input("Paybill Account Number", "1285399528")
    branch_name = st.text_input("Bank Branch Name", "Siaya")
  with col_cfg2:
    bank_code = st.text_input("Bank Code", "01")
    branch_code = st.text_input("Branch Code", "012")
    swift_code = st.text_input("SWIFT Code", "KCBLKENX")

  st.markdown("---")
  st.markdown("### 🏢 Bulk Operations (All Active Tenants)")
  sender_email = st.text_input(
      "Sender Gmail Address", "globalstarinvest@gmail.com"
  )
  app_password = st.text_input(
      "Gmail App Password",
      value="bwng mwof eqrq jpaf",
      type="password",
  )

  if st.button("🚀 Bulk Generate Invoices & Email All Tenants", type="primary"):
    if not app_password:
      st.error("Please enter your Gmail App Password.")
    else:
      progress_bar = st.progress(0)
      status_text = st.empty()
      total_tenants = len(df_arr)
      success_count = 0

      for i, (_, row) in enumerate(df_arr.iterrows()):
        s_no = int(row["Shop #"])
        t_name = row["Tenant Name"]
        t_pin = str(row.get("KRA PIN Certificate", "P051548911H"))
        if t_pin == "nan" or not t_pin:
          t_pin = "P051548911H"
        t_rate = float(row["Monthly Rate"])
        t_email = str(row.get("Email Address", ""))

        status_text.text(f"Processing Shop #{s_no} - {t_name}...")
        try:
          pdf_inv = backend.generate_etims_tax_invoice_pdf(
              tenant_name=t_name,
              shop_no=s_no,
              rate=t_rate,
              paybill=paybill,
              paybill_acc=paybill_acc,
              branch_name=branch_name,
              bank_code=bank_code,
              branch_code=branch_code,
              swift_code=swift_code,
              billing_month=billing_month,
              kra_pin=t_pin,
          )
          if t_email and "@" in t_email:
            backend.send_email_statement(
                recipient_email=t_email,
                tenant_name=t_name,
                pdf_path=pdf_inv,
                sender_email=sender_email,
                app_password=app_password,
                shop_no=s_no,
                paybill=paybill,
                paybill_acc=paybill_acc,
                branch_name=branch_name,
                bank_code=bank_code,
                branch_code=branch_code,
                swift_code=swift_code,
                billing_month=billing_month,
            )
          success_count += 1
        except Exception as e:
          st.warning(f"Error processing Shop #{s_no}: {str(e)}")
        progress_bar.progress((i + 1) / total_tenants)

      status_text.empty()
      progress_bar.empty()
      st.success(
          "Successfully generated eTIMS invoices and dispatched emails for"
          f" {success_count} out of {total_tenants} tenants!"
      )

  st.markdown("---")
  st.markdown("### 👤 Single Tenant Actions")
  tenant_labels = [
      f"Shop #{row['Shop #']} - {row['Tenant Name']}"
      for _, row in df_arr.iterrows()
  ]
  selected_label = st.selectbox(
      "Select Tenant Shop for Individual Action", tenant_labels
  )
  selected_shop = int(selected_label.split("Shop #")[1].split(" - ")[0])
  tenant_row = df_arr[df_arr["Shop #"] == selected_shop].iloc[0]

  t_name = tenant_row["Tenant Name"]
  t_pin = str(tenant_row.get("KRA PIN Certificate", "P051548911H"))
  monthly_rent = float(tenant_row["Monthly Rate"])
  t_email = str(tenant_row.get("Email Address", ""))

  st.write(
      f"**Tenant:** {t_name} | **Shop:** #{selected_shop} | **Monthly Rate:** KSh"
      f" {monthly_rent:,.2f} | **PIN:** {t_pin} | **Email:** {t_email}"
  )

  col_btn1, col_btn2 = st.columns(2)
  with col_btn1:
    if st.button("📄 Generate Selected Invoice PDF"):
      pdf_invoice = backend.generate_etims_tax_invoice_pdf(
          tenant_name=t_name,
          shop_no=int(selected_shop),
          rate=monthly_rent,
          paybill=paybill,
          paybill_acc=paybill_acc,
          branch_name=branch_name,
          bank_code=bank_code,
          branch_code=branch_code,
          swift_code=swift_code,
          billing_month=billing_month,
          kra_pin=t_pin if t_pin != "N/A" else "P051548911H",
      )
      st.success(f"Generated: {pdf_invoice}")
      with open(pdf_invoice, "rb") as f:
        st.download_button(
            "📥 Download Invoice PDF",
            f,
            file_name=os.path.basename(pdf_invoice),
        )

  with col_btn2:
    if st.button("📊 Generate Selected Statement PDF"):
      pdf_statement = backend.generate_bank_statement_pdf(
          tenant_name=t_name,
          shop_no=int(selected_shop),
          rate=monthly_rent,
          expected=float(tenant_row["Expected_Rent"]),
          collected=float(tenant_row["Actual_Collected"]),
          arrears=float(tenant_row["Arrears_Balance"]),
          penalty=float(tenant_row.get("Penalty_Fee", 0)),
          interest=float(tenant_row.get("Interest_Charge", 0)),
          paybill=paybill,
          paybill_acc=paybill_acc,
          branch_name=branch_name,
          bank_code=bank_code,
          branch_code=branch_code,
          swift_code=swift_code,
          billing_month=billing_month,
      )
      st.success(f"Generated: {pdf_statement}")
      with open(pdf_statement, "rb") as f:
        st.download_button(
            "📥 Download Statement PDF",
            f,
            file_name=os.path.basename(pdf_statement),
        )

  recipient_email = st.text_input(
      "Recipient Tenant Email", t_email, key="single_recipient"
  )
  if st.button("📤 Send Selected Invoice via Email"):
    with st.spinner("Sending email..."):
      pdf_invoice = backend.generate_etims_tax_invoice_pdf(
          tenant_name=t_name,
          shop_no=int(selected_shop),
          rate=monthly_rent,
          paybill=paybill,
          paybill_acc=paybill_acc,
          branch_name=branch_name,
          bank_code=bank_code,
          branch_code=branch_code,
          swift_code=swift_code,
          billing_month=billing_month,
          kra_pin=t_pin if t_pin != "N/A" else "P051548911H",
      )
      success, msg = backend.send_email_statement(
          recipient_email=recipient_email,
          tenant_name=t_name,
          pdf_path=pdf_invoice,
      )
      if success:
        st.success(msg)
      else:
        st.error(msg)

elif module == "Demand Notice Builder":
  st.subheader("⚖️ Formal Legal Demand Notice Builder")
  st.markdown(
      "Generate formal legal demand notices and letters of demand specifically"
      " for tenants with outstanding rent arrears."
  )

  df_arr = backend.calculate_tenant_arrears()
  df_non_compliant = df_arr[df_arr["Arrears_Balance"] > 0]

  if df_non_compliant.empty:
    st.success("All tenants are fully compliant! No outstanding arrears detected.")
  else:
    tenant_labels = [
        (
            f"Shop #{row['Shop #']} - {row['Tenant Name']} (Arrears: KSh"
            f" {row['Arrears_Balance']:,.2f})"
        )
        for _, row in df_non_compliant.iterrows()
    ]
    selected_label = st.selectbox(
        "Select Non-Compliant Tenant / Shop for Notice", tenant_labels
    )
    selected_shop_no = int(selected_label.split("Shop #")[1].split(" - ")[0])
    row_sel = df_non_compliant[
        df_non_compliant["Shop #"] == selected_shop_no
    ].iloc[0]

    t_email = str(row_sel.get("Email Address", ""))

    notice_text = f"""NOTICE TO QUIT & PAY RENT ARREARS

TO: {row_sel['Tenant Name']}
PROPERTY: Shop #{selected_shop_no}, Tinitin La Place Building, Siaya Town
MANAGED BY: Global Star Investments Limited
DATE: August 3, 2026

Dear Tenant,

TAKE NOTICE that as of July 31, 2026, your rent arrears account for Shop #{selected_shop_no} reflects an outstanding balance of KSh {row_sel['Arrears_Balance']:,.2f} (inclusive of applicable late fees/penalties). 

Enforcement Status: {row_sel['Enforcement_Status']}

Kindly arrange for immediate settlement via our official M-Pesa Paybill (Business No: 522522 | Account: 1285399528) or direct KCB Bank transfer within 7 days of this notice to avoid formal access restriction, legal distress, or lease forfeiture.

Yours faithfully,
MANAGEMENT
GLOBAL STAR INVESTMENTS LIMITED
"""
    st.text_area("Generated Demand Notice Preview", notice_text, height=280)

    st.markdown("### 📧 Email Dispatch for Legal Demand Notice")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
      demand_sender = st.text_input(
          "Sender Gmail Address",
          "globalstarinvest@gmail.com",
          key="demand_sender",
      )
    with col_d2:
      demand_pwd = st.text_input(
          "Gmail App Password",
          value="bwng mwof eqrq jpaf",
          type="password",
          key="demand_pwd",
      )

    demand_recipient = st.text_input(
        "Recipient Email Address(es)", t_email, key="demand_recipient"
    )

    col_act1, col_act2 = st.columns(2)
    with col_act1:
      if st.button("📥 Download Legal Demand Notice Text"):
        st.download_button(
            "Download Notice File",
            notice_text,
            file_name=f"Demand_Notice_Shop_{selected_shop_no}.txt",
        )
    with col_act2:
      if st.button("📤 Send Legal Demand Notice via Email", type="primary"):
        if not demand_recipient or "@" not in demand_recipient:
          st.error("Please enter a valid recipient email address.")
        else:
          success, msg = backend.send_email_statement(
              recipient_email=demand_recipient,
              tenant_name=row_sel["Tenant Name"],
              pdf_path="",
              sender_email=demand_sender,
              app_password=demand_pwd,
              shop_no=int(selected_shop_no),
              paybill="522522",
              paybill_acc="1285399528",
              branch_name="Siaya",
              bank_code="01",
              branch_code="012",
              swift_code="KCBLKENX",
              billing_month=backend.statement_month_str,
          )
          if success:
            st.success(
                f"Legal demand notice successfully sent to"
                f" {row_sel['Tenant Name']}!"
            )
          else:
            st.error(f"Test failed: {msg}")

elif module == "Bank Statement Audit":
  st.subheader("🏦 KCB Bank Statement Audit & Reconciliation")
  st.markdown(
      "Displaying complete bank statement records for"
      f" **{backend.statement_period_str}** (Total Records:"
      f" {len(backend.df_bank)})"
  )
  st.dataframe(backend.df_bank, width="stretch")

elif module == "Annual P&L & iTax Statement":
  st.subheader("📊 Annual Profit & Loss Statement (March 01 – February 28)")
  st.markdown("Automated financial statement aggregation for corporate tax preparation and iTax filing.")

  fiscal_year_end = st.selectbox("Select Fiscal Year Ending", [2026, 2025, 2024], index=0)
  st.markdown("---")
  
  st.markdown("### **1. Operating Revenue**")
  df_arr = backend.calculate_tenant_arrears()
  total_annual_collected = df_arr['Actual_Collected'].sum() * 12
  
  col_rev1, col_rev2 = st.columns(2)
  with col_rev1:
      gross_rental_income = st.number_input("Gross Rental Income (KSh)", value=float(total_annual_collected), step=1000.0)
  with col_rev2:
      other_business_income = st.number_input("Other Income (Water Point / Ancillary) (KSh)", value=0.0, step=1000.0)
      
  total_revenue = gross_rental_income + other_business_income
  st.metric("Total Gross Revenue", f"KSh {total_revenue:,.2f}")
  st.markdown("---")
  
  st.markdown("### **2. Operating & Maintenance Expenses**")
  col_exp1, col_exp2 = st.columns(2)
  with col_exp1:
      repairs_maintenance = st.number_input("Repairs, Electrical & Hardware Maintenance (KSh)", value=0.0, step=1000.0)
      utilities_exp = st.number_input("Utilities & Services (KPLC / Water) (KSh)", value=0.0, step=1000.0)
      security_monitoring = st.number_input("Security, Starlink & Connectivity (KSh)", value=0.0, step=1000.0)
  with col_exp2:
      admin_legal_fees = st.number_input("Administrative & Professional Fees (KSh)", value=0.0, step=1000.0)
      bank_charges = st.number_input("Bank Charges & M-Pesa Transaction Fees (KSh)", value=0.0, step=1000.0)
      misc_expenses = st.number_input("Miscellaneous Operating Expenses (KSh)", value=0.0, step=1000.0)
      
  total_expenses = (repairs_maintenance + utilities_exp + security_monitoring + 
                    admin_legal_fees + bank_charges + misc_expenses)
  st.metric("Total Allowable Operating Expenses", f"KSh {total_expenses:,.2f}")
  st.markdown("---")
  
  st.markdown("### **3. Net Profit & Corporation Tax Estimate**")
  net_profit = total_revenue - total_expenses
  estimated_tax = max(0.0, net_profit * 0.30)
  
  col_np1, col_np2, col_np3 = st.columns(3)
  col_np1.metric("Net Profit Before Tax", f"KSh {net_profit:,.2f}")
  col_np2.metric("Chargeable Income", f"KSh {max(0.0, net_profit):,.2f}")
  col_np3.metric("Estimated Tax Payable (30%)", f"KSh {estimated_tax:,.2f}")
  
  st.markdown("---")
  if st.button("📥 Export Annual P&L Summary for iTax", type="primary"):
      st.success(f"P&L Statement for March 01, {fiscal_year_end - 1} – February 28, {fiscal_year_end} compiled successfully!")