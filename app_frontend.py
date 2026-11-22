"""
Global Star Investments - Frontend Engine
==================================================
GOVERNANCE & ARCHITECTURE CONSTITUTION:
- Data Integrity: All financial/eTIMS calculations must be deterministic and audited.
- Security: Zero hardcoded secrets; environment variables (.env) are mandatory.
- Modularity: Strict separation between database layers, business logic, and UI.
"""

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

st.sidebar.markdown("## Data Upload & Portal Setup")
st.sidebar.markdown("---")

uploaded_tenant_file = st.sidebar.file_uploader("Upload Tenants Details (Excel)", type=["xlsx"])
uploaded_bank_file = st.sidebar.file_uploader("Upload Bank Statement (Excel)", type=["xlsx"])

# Validate source file type before initializing the Excel-based reporting engine.
# V1 does not send or store workbooks in a database.
from io import BytesIO
def _workbook_category(upload):
    if upload is None:
        return None
    try:
        with pd.ExcelFile(BytesIO(upload.getvalue())) as workbook:
            for tab in workbook.sheet_names:
                for header in (0, 14):
                    cols = {str(col).strip().casefold() for col in
                            pd.read_excel(workbook, sheet_name=tab, header=header, nrows=0).columns}
                    if {"transaction date", "money in", "money out", "bank reference number"} <= cols:
                        return "bank"
                    if {"tenant name", "monthly rate"} <= cols and (
                            "shop / unit #" in cols or "shop #" in cols):
                        return "tenants"
    except Exception:
        return "invalid"
    return "unknown"

if uploaded_tenant_file is not None and _workbook_category(uploaded_tenant_file) != "tenants":
    st.error("The first upload must be the Tenant Details workbook. Check the selected file.")
    st.stop()
if uploaded_bank_file is not None and _workbook_category(uploaded_bank_file) != "bank":
    st.error("The second upload must be the KCB Bank Statement workbook. Check the selected file.")
    st.stop()


# TenantPortalBackend uses os.path.exists() and expects filesystem paths,
# not Streamlit UploadedFile objects. Keep uploads in a temporary session directory.
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

if "_v1_excel_tmp_dir" not in st.session_state:
    st.session_state["_v1_excel_tmp_dir"] = TemporaryDirectory(prefix="globalstar-v1-")
_session_dir = Path(st.session_state["_v1_excel_tmp_dir"].name)

def _excel_file_path(upload, kind, fallback):
    if upload is None:
        return fallback
    content = upload.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    path = _session_dir / f"{kind}_{digest}.xlsx"
    if not path.is_file():
        path.write_bytes(content)
    return str(path)

tenant_path = _excel_file_path(uploaded_tenant_file, "tenants", "Tenants_Details.xlsx")
bank_path = _excel_file_path(uploaded_bank_file, "bank", "KCB_Bank_Statement.xlsx")

if not os.path.exists("Tenants_Details.xlsx") and uploaded_tenant_file is None:
    st.warning("⚠️ Please upload your `Tenants_Details.xlsx` file using the sidebar.")
if not os.path.exists("KCB_Bank_Statement.xlsx") and uploaded_bank_file is None:
    st.warning("⚠️ Please upload your `KCB_Bank_Statement.xlsx` file using the sidebar.")

@st.cache_resource
def get_backend(t_path, b_path):
    return TenantPortalBackend(
        tenant_excel_path=t_path,
        bank_excel_path=b_path,
    )

if (os.path.exists("Tenants_Details.xlsx") or uploaded_tenant_file is not None) and \
   (os.path.exists("KCB_Bank_Statement.xlsx") or uploaded_bank_file is not None):
    backend = get_backend(tenant_path, bank_path)
else:
    st.stop()

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
    
    unmapped['Display_Label'] = unmapped.apply(
        lambda r: f"Ref: {r['Ref_Clean']} | Amt: KSh {r['Money In Num']:,.2f} | {str(r['Transaction Details'])[:40]}...", 
        axis=1
    )
    
    selected_display = st.selectbox(
        "Select Unmapped Transaction to Reassign",
        unmapped['Display_Label'].tolist(),
        key="unmapped_ref_sel",
    )
    
    ref_to_fix = selected_display.split(" | ")[0].replace("Ref: ", "").strip()

    col_ua1, col_ua2 = st.columns(2)
    with col_ua1:
      target_shop = st.number_input(
          "Target Shop # (1 to 22)",
          min_value=1,
          max_value=22,
          value=1,
          key="target_shop_input",
      )
      
      matched_tenant_row = backend.df_tenants[backend.df_tenants['Shop #'] == target_shop]
      tenant_preview_name = matched_tenant_row['Tenant Name'].values[0] if not matched_tenant_row.empty else "Unknown"
      st.info(f"Target Preview: **Shop #{target_shop} - {tenant_preview_name}**")

      if st.button("Save Reassignment Override", type="primary"):
        backend.save_override(ref_to_fix, target_shop)
        backend.reload_master_data()
        st.success(
            f"Successfully reassigned reference {ref_to_fix} to Shop"
            f" #{target_shop} ({tenant_preview_name})!"
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
    st.subheader("🤖 AI Lease Agreement Extractor & Active Leases Overview")
    st.markdown("Lease overview from the uploaded tenant workbook. This view does not read or update any database.")
    tenant_cols = [
        name for name in ("Shop / Unit #", "Tenant Name", "Monthly Rate",
                          "Lease Date", "Calculated_Lease_End", "Calculated_Status")
        if name in backend.df_tenants.columns
    ]
    if tenant_cols:
        st.dataframe(backend.df_tenants[tenant_cols], width="stretch", hide_index=True)
    else:
        st.info("No lease details found in the uploaded tenant workbook.")

    st.markdown("---")
    st.markdown("### 📂 Optional: Upload New Lease Agreement (Instant OCR & Master Verification)")

    with st.expander("📁 Batch Process from 'Lease_Agreements' Folder", expanded=False):
        if st.button("Scan & Extract All Leases from Root Folder"):
            folder_leases = backend.process_lease_agreements_folder("Lease_Agreements")
            if folder_leases:
                st.success(f"Successfully processed {len(folder_leases)} lease agreement(s) from the folder!")
                
                verification_summaries = []
                for fl in folder_leases:
                    v_res = backend.verify_ocr_against_master(fl)
                    fl["Master Verification"] = "Pass" if not v_res["Discrepancies"] else "Discrepancy Found"
                    fl["Discrepancy Details"] = ", ".join(v_res["Discrepancies"]) if v_res["Discrepancies"] else "None"
                    verification_summaries.append(fl)
                
                st.dataframe(pd.DataFrame(verification_summaries), width="stretch")
            else:
                st.warning("No PDF lease agreements found in the 'Lease_Agreements' folder.")
    
    uploaded_pdfs = st.file_uploader(
        "Upload Signed Lease PDF(s) for Instant Extraction",
        type=["pdf"],
        accept_multiple_files=True,
    )
    if uploaded_pdfs:
        if not isinstance(uploaded_pdfs, list):
            uploaded_pdfs = [uploaded_pdfs]

        for idx, pdf_file in enumerate(uploaded_pdfs):
            st.markdown(f"### 📄 Extracting: `{getattr(pdf_file, 'name', f'Lease_{idx + 1}')}`")
            extracted_info = LeaseDocumentAI.parse_lease_pdf(pdf_file)
            st.json(extracted_info)
            
            verification = backend.verify_ocr_against_master(extracted_info)
            if verification["Match Found"]:
                st.info(f"📋 Master Ledger Match Found! Registered Tenant: **{verification.get('Master Tenant Name')}** | Manual Status: **{verification.get('Manual Status')}**")
                if verification["Discrepancies"]:
                    for disc in verification["Discrepancies"]:
                        st.warning(f"⚠️ {disc}")
                else:
                    st.success("✅ OCR terms match master spreadsheet records perfectly.")
            else:
                st.warning("⚠️ Unit not found in master spreadsheet ledger. Review before registering.")

        st.info(
            "OCR and master verification are preview-only in the Excel-based V1. "
            "To update tenants, revise the source workbook and upload it again."
        )

    if st.button("Clear All Reassignment Overrides"):
        if os.path.exists("reassignments.json"):
            os.remove("reassignments.json")
        backend.overrides = {}
        backend.reload_master_data()
        st.success("All manual reassignments cleared!")
        st.rerun()

elif module == "Arrears Payment Reminders":
    st.subheader("📢 Arrears Payment Reminders & Friendly Notices")
    st.markdown(
        "Send polite payment reminders and overdue notices to non-compliant "
        "tenants through multiple channels (Email, WhatsApp, and SMS) with both single and bulk options."
    )

    df_arr = backend.calculate_tenant_arrears()
    df_non_compliant = df_arr[df_arr["Arrears_Balance"] > 0]

    if df_non_compliant.empty:
        st.success("All tenants are fully compliant! No reminders needed.")
    else:
        st.markdown("---")
        st.markdown("### 👤 Step 1: Select Tenant for Single Actions")
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

        raw_phone_val = str(row_sel.get("Telephone No.", ""))
        if raw_phone_val.endswith('.0'):
            raw_phone_val = raw_phone_val[:-2]

        st.markdown("---")
        st.markdown("### 📧 Step 2: Email Reminder Dispatch (Single & Bulk)")
        
        col_em1, col_em2 = st.columns(2)
        with col_em1:
            sender_email = st.text_input("Sender Gmail Address", "globalstarinvest@gmail.com", key="rem_sender")
        with col_em2:
            app_password = st.text_input("Gmail App Password", value="", type="password", key="rem_pwd")

        tab_email_single, tab_email_bulk = st.tabs(["👤 Single Tenant Email", "🚀 Bulk Email (All Arrears)"])
        
        with tab_email_single:
            recipient_email = st.text_input("Recipient Email", value=t_email)
            
            comprehensive_email_body = f"""Dear {t_name},

We hope this message finds you well.

This is a formal reminder from Global Star Investments Limited regarding your commercial lease account for Shop #{selected_shop_no} at Tinitin La Place Building, Siaya Town.

Our records indicate an outstanding arrears balance of KSh {arrears_amt:,.2f} for the current billing period ({backend.statement_month_str}). 

Kindly arrange for settlement at your earliest convenience using any of our official payment channels:
1. M-Pesa Paybill: Business No. 522522 | Account: 1285399528
2. M-Pesa Paybill: Business No. 522533 | Account: 8035949
3. Direct KCB Bank Transfer: Account No. 1285399528, Siaya Branch

Please find attached your itemized bank payment and rent ledger statement for your review.

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""

            st.text_area("Single Email Preview", value=comprehensive_email_body, height=220)

            st.markdown("---")
            st.markdown("### 📄 Tenant Statement Generation & Download")
            pdf_filename = f"Statement_Shop_{selected_shop_no}_{t_name.replace(' ', '_')}.pdf"
            
            monthly_rate_val = row_sel.get('Monthly Rate', 0.0)
            expected_rent_val = row_sel.get('Expected_Rent', 0.0)
            actual_collected_val = row_sel.get('Actual_Collected', 0.0)
            arrears_balance_val = row_sel.get('Arrears_Balance', 0.0)
            penalty_fee_val = row_sel.get('Penalty_Fee', 0.0)
            interest_charge_val = row_sel.get('Interest_Charge', 0.0)

            res = backend.generate_bank_statement_pdf(
                shop_no=int(selected_shop_no),
                tenant_name=str(t_name),
                rate=float(monthly_rate_val),
                expected=float(expected_rent_val),
                collected=float(actual_collected_val),
                arrears=float(arrears_balance_val),
                penalty=float(penalty_fee_val),
                interest=float(interest_charge_val),
                paybill="522522",
                paybill_acc="1285399528",
                branch_name="Siaya",
                bank_code="01",
                branch_code="012",
                swift_code="KCBLKENX",
                billing_month=backend.statement_month_str
            )

            if isinstance(res, str):
                pdf_filename = res
                with open(pdf_filename, "rb") as f:
                    pdf_bytes = f.read()
            else:
                pdf_bytes = res
                with open(pdf_filename, "wb") as f:
                    f.write(pdf_bytes)
            
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    label="📥 Download Tenant Statement PDF",
                    data=pdf_bytes,
                    file_name=pdf_filename,
                    mime="application/pdf",
                    key=f"dl_pdf_{selected_shop_no}"
                )

            st.markdown("---")
            if st.button("📤 Send Single Email Reminder (With Attached Statement)", type="primary"):
                if not recipient_email or "@" not in recipient_email:
                    st.error("Please enter a valid recipient email address.")
                else:
                    success, msg = backend.send_email_statement(
                        recipient_email=recipient_email, 
                        tenant_name=t_name, 
                        pdf_path=pdf_filename, 
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
                        st.success(f"Payment reminder and itemized statement successfully sent to {t_name}!")
                    else:
                        st.error(f"Failed to send email: {msg}")

        with tab_email_bulk:
            st.info(f"Ready to dispatch bulk reminder emails to all {len(df_non_compliant)} non-compliant tenants.")
            if st.button("📤 Send Bulk Emails to All Arrears Tenants", type="primary"):
                if not app_password:
                    st.error("Please enter your Gmail App Password.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total_nc = len(df_non_compliant)
                    email_success_count = 0

                    for i, (_, row) in enumerate(df_non_compliant.iterrows()):
                        s_no = int(row["Shop #"])
                        c_name = row["Tenant Name"]
                        c_email = str(row.get("Email Address", ""))
                        
                        status_text.text(f"Emailing Shop #{s_no} - {c_name}...")
                        if c_email and "@" in c_email:
                            success, _ = backend.send_email_statement(
                                recipient_email=c_email, tenant_name=c_name, pdf_path="",
                                sender_email=sender_email, app_password=app_password, shop_no=s_no,
                                paybill="522522", paybill_acc="1285399528", branch_name="Siaya",
                                bank_code="01", branch_code="012", swift_code="KCBLKENX", billing_month=backend.statement_month_str,
                            )
                            if success:
                                email_success_count += 1
                        progress_bar.progress((i + 1) / total_nc)

                    status_text.empty()
                    progress_bar.empty()
                    st.success(f"Successfully dispatched bulk emails to {email_success_count} out of {total_nc} tenants!")

        st.markdown("---")
        st.markdown("### 💬 Step 3: WhatsApp Reminder Dispatch (Single & Bulk)")
        
        col_wa1, col_wa2 = st.columns(2)
        with col_wa1:
            wa_token = st.text_input(
                "Meta WhatsApp Access Token",
                value="", type="password", key="shared_wa_token"
            )
        with col_wa2:
            wa_phone_id = st.text_input("WhatsApp Phone Number ID", value="1104611856058033", key="shared_wa_phone_id")

        tab_wa_single, tab_wa_bulk = st.tabs(["👤 Single Tenant WhatsApp", "🚀 Bulk WhatsApp (All Arrears)"])

        with tab_wa_single:
            tenant_phone = st.text_input("Tenant Mobile Number", value=raw_phone_val, key=f"wa_phone_{selected_shop_no}")
            
            single_wa_text = f"""Dear {t_name},

We hope this message finds you well.

This is a formal reminder from Global Star Investments Limited regarding your commercial lease account for Shop #{selected_shop_no} at Tinitin La Place Building, Siaya Town.

Our records indicate an outstanding arrears balance of KSh {arrears_amt:,.2f} for the current billing period ({backend.statement_month_str}). 

Kindly arrange for settlement at your earliest convenience using any of our official payment channels:
1. M-Pesa Paybill: Business No. 522522 | Account: 1285399528
2. M-Pesa Paybill: Business No. 522533 | Account: 8035949
3. Direct KCB Bank Transfer: Account No. 1285399528, Siaya Branch

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
            edited_wa_text = st.text_area("Single WhatsApp Preview", value=single_wa_text, height=220, key=f"wa_preview_{selected_shop_no}")

            if st.button("📱 Send Single WhatsApp Reminder", type="primary"):
                if not wa_token or not wa_phone_id:
                    st.error("Please enter your WhatsApp credentials.")
                elif not tenant_phone or len(tenant_phone) < 9:
                    st.error("Please provide a valid tenant mobile number.")
                else:
                    success, msg = backend.send_whatsapp_message(
                        recipient_phone=tenant_phone, message_text=edited_wa_text,
                        access_token=wa_token, phone_number_id=wa_phone_id
                    )
                    if success:
                        st.success(f"WhatsApp reminder successfully sent to {t_name}!")
                    else:
                        st.error(f"Failed to send WhatsApp message: {msg}")

        with tab_wa_bulk:
            st.info(f"Ready to dispatch bulk WhatsApp messages to all {len(df_non_compliant)} non-compliant tenants.")
            if st.button("📱 Send Bulk WhatsApp to All Arrears Tenants", type="primary"):
                if not wa_token or not wa_phone_id:
                    st.error("Please enter your WhatsApp credentials.")
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

                        bulk_wa_text = f"""Dear {c_name},

We hope this message finds you well.

This is a formal reminder from Global Star Investments Limited regarding your commercial lease account for Shop #{s_no} at Tinitin La Place Building, Siaya Town.

Our records indicate an outstanding arrears balance of KSh {c_arrears:,.2f} for the current billing period ({backend.statement_month_str}). 

Kindly arrange for settlement at your earliest convenience using any of our official payment channels:
1. M-Pesa Paybill: Business No. 522522 | Account: 1285399528
2. M-Pesa Paybill: Business No. 522533 | Account: 8035949
3. Direct KCB Bank Transfer: Account No. 1285399528, Siaya Branch

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
                        
                        status_text.text(f"Sending WhatsApp to Shop #{s_no} - {c_name}...")
                        if c_phone and len(c_phone) >= 9:
                            success, _ = backend.send_whatsapp_message(
                                recipient_phone=c_phone, message_text=bulk_wa_text,
                                access_token=wa_token, phone_number_id=wa_phone_id
                            )
                            if success:
                                wa_success_count += 1
                        progress_bar.progress((i + 1) / total_nc)

                    status_text.empty()
                    progress_bar.empty()
                    st.success(f"Successfully dispatched bulk WhatsApp reminders to {wa_success_count} out of {total_nc} tenants!")

        st.markdown("---")
        st.markdown("### 💬 Step 4: SMS Reminder Dispatch (Single & Bulk)")
        
        col_sms1, col_sms2 = st.columns(2)
        with col_sms1:
            at_username = st.text_input("Africa's Talking Username", value="POdhiambo2010", key="at_user")
        with col_sms2:
            at_apikey = st.text_input(
                "Africa's Talking API Key",
                value="", type="password",
                key="at_key"
            )

        tab_sms_single, tab_sms_bulk = st.tabs(["👤 Single Tenant SMS", "🚀 Bulk SMS (All Arrears)"])

        with tab_sms_single:
            sms_phone = st.text_input("Tenant Mobile Number for SMS", value=raw_phone_val, key=f"sms_phone_{selected_shop_no}")
            
            sms_text_preview = f"""Dear {t_name},

We hope this message finds you well.

This is a formal reminder from Global Star Investments Limited regarding your commercial lease account for Shop #{selected_shop_no} at Tinitin La Place Building, Siaya Town.

Our records indicate an outstanding arrears balance of KSh {arrears_amt:,.2f} for the current billing period ({backend.statement_month_str}). 

Kindly arrange for settlement at your earliest convenience using any of our official payment channels:
1. M-Pesa Paybill: Business No. 522522 | Account: 1285399528
2. M-Pesa Paybill: Business No. 522533 | Account: 8035949
3. Direct KCB Bank Transfer: Account No. 1285399528, Siaya Branch

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
            edited_sms = st.text_area("Single SMS Message Preview", value=sms_text_preview, height=220, key=f"sms_preview_{selected_shop_no}")

            if st.button("📱 Send Single SMS Reminder", type="primary"):
                if not at_apikey:
                    st.error("Please enter your Africa's Talking Sandbox API Key.")
                elif not sms_phone or len(sms_phone) < 9:
                    st.error("Please provide a valid tenant mobile number.")
                else:
                    success, msg = backend.send_sms_reminder(
                        recipient_phone=sms_phone, message_text=edited_sms,
                        username=at_username, api_key=at_apikey
                    )
                    if success:
                        st.success(f"SMS reminder successfully sent to {t_name} via Africa's Talking Sandbox!")
                    else:
                        st.error(f"Failed to send SMS: {msg}")

        with tab_sms_bulk:
            bulk_sms_text_preview = f"""Dear Tenant,

This is a formal reminder from Global Star Investments Limited regarding your commercial lease account at Tinitin La Place Building, Siaya Town.

Our records indicate outstanding arrears for the current billing period ({backend.statement_month_str}). 

Kindly arrange for settlement using our official payment channels:
1. M-Pesa Paybill: Business No. 522522 | Account: 1285399528
2. M-Pesa Paybill: Business No. 522533 | Account: 8035949
3. Direct KCB Bank Transfer: Account No. 1285399528, Siaya Branch

Sincerely,
Management
Global Star Investments Limited
Email: globalstarinvest@gmail.com
Tel: +254 723 562 286
"""
            edited_bulk_sms = st.text_area("Bulk SMS Message Preview", value=bulk_sms_text_preview, height=220, key="bulk_sms_preview")
            
            st.info(f"Ready to dispatch bulk SMS messages to all {len(df_non_compliant)} non-compliant tenants.")
            if st.button("📱 Send Bulk SMS to All Arrears Tenants", type="primary"):
                if not at_apikey:
                    st.error("Please enter your Africa's Talking Sandbox API Key.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    total_nc = len(df_non_compliant)
                    sms_success_count = 0

                    for i, (_, row) in enumerate(df_non_compliant.iterrows()):
                        s_no = int(row["Shop #"])
                        c_name = row["Tenant Name"]
                        c_phone = str(row.get("Telephone No.", ""))
                        if c_phone.endswith('.0'):
                            c_phone = c_phone[:-2]

                        status_text.text(f"Sending SMS to Shop #{s_no} - {c_name}...")
                        if c_phone and len(c_phone) >= 9:
                            success, _ = backend.send_sms_reminder(
                                recipient_phone=c_phone, message_text=edited_bulk_sms,
                                username=at_username, api_key=at_apikey
                            )
                            if success:
                                sms_success_count += 1
                        progress_bar.progress((i + 1) / total_nc)

                    status_text.empty()
                    progress_bar.empty()
                    st.success(f"Successfully dispatched bulk SMS reminders to {sms_success_count} out of {total_nc} tenants!")

elif module == "eTIMS Tax Invoices & Bank Statements":
    st.subheader("eTIMS — Unverified Integration")
    st.error("Official invoice issuance and KRA submission are disabled until a verified integration is available.")
    st.warning("Past locally generated invoice identifiers or QR codes must not be treated as KRA acknowledgements.")
    st.info("Arrears status does not determine statutory invoice obligations.")
    billing = backend.calculate_tenant_arrears()
    columns = [k for k in ("Shop #", "Tenant Name", "Monthly Rate", "Arrears_Balance") if k in billing.columns]
    st.dataframe(billing[columns], width="stretch", hide_index=True)

elif module == "Demand Notice Builder":
    from datetime import date, timedelta
    from demand_notice_v1 import render_draft_demand_notice

    st.subheader("📄 Demand Notice Builder")
    st.info(
        "Excel-only draft workflow. This page creates a reviewable PDF, "
        "does not send notices, and does not change financial records."
    )
    df_notice = backend.calculate_tenant_arrears()
    if df_notice.empty:
        st.warning("No tenant accounts found in the uploaded workbook.")
    else:
        eligible = df_notice.copy()
        eligible["Arrears_Balance"] = pd.to_numeric(
            eligible["Arrears_Balance"], errors="coerce"
        ).fillna(0)
        eligible = eligible[eligible["Arrears_Balance"] > 0].copy()
        if eligible.empty:
            st.success("No positive arrears appear in the uploaded tenant data.")
        else:
            choice = st.selectbox(
                "Select tenant with outstanding arrears",
                list(eligible.index),
                format_func=lambda idx: (
                    f'Unit {eligible.loc[idx, "Shop #"]} · '
                    f'{eligible.loc[idx, "Tenant Name"]} · '
                    f'KSh {eligible.loc[idx, "Arrears_Balance"]:,.2f}'
                ),
                key="v1_notice_select",
            )
            row = eligible.loc[choice]
            tenant_name = str(row["Tenant Name"])
            unit = str(row["Shop #"])
            amount = float(row["Arrears_Balance"])
            st.metric("Workbook arrears (unverified)", f"KSh {amount:,.2f}")
            st.caption(
                "Check payment allocations, opening balances, renewals and "
                "contractual notice requirements before using this draft."
            )
            date_of_notice = st.date_input(
                "Draft date", value=date.today(), key="v1_notice_date"
            )
            response_date = st.date_input(
                "Requested response date",
                value=date.today() + timedelta(days=14),
                key="v1_notice_response",
            )
            notes = st.text_area(
                "Optional factual notes for the draft",
                max_chars=1500,
                placeholder="Only add information confirmed from the lease or accounts.",
                key="v1_notice_notes",
            )
            if response_date < date_of_notice:
                st.error("Response date must not precede the notice date.")
            else:
                st.markdown("#### Draft preview (not sent)")
                st.write(f"**To:** {tenant_name} — Unit {unit}")
                st.write(
                    f"**Outstanding balance per workbook:** KSh {amount:,.2f}"
                )
                st.write(f"**Accounts period:** {backend.statement_month_str}")
                st.write(f"**Response requested by:** {response_date:%d %B %Y}")
                verified = st.checkbox(
                    "I understand this is a draft and the arrears, lease and "
                    "notice requirements must be verified before service.",
                    key="v1_notice_confirm",
                )
                if verified:
                    try:
                        pdf = render_draft_demand_notice(
                            tenant_name=tenant_name,
                            unit=unit,
                            outstanding=amount,
                            as_of=date_of_notice,
                            response_by=response_date,
                            account_period=backend.statement_month_str,
                            additional_notes=notes,
                        )
                        st.download_button(
                            "Download DRAFT Demand Notice (PDF)",
                            data=pdf,
                            file_name=f"DRAFT_Demand_Notice_Unit_{unit}.pdf",
                            mime="application/pdf",
                            key="v1_notice_pdf",
                        )
                    except Exception as exc:
                        st.error(f"Could not generate the draft PDF: {exc}")

elif module == "Bank Statement Audit":
    from bank_reconciliation_v1 import reconcile_bank_ledger, export_reconciliation
    st.subheader("🏦 KCB Bank Statement Audit & Reconciliation")
    full_bank = backend.df_bank_full
    st.caption(f"Uploaded statement: {backend.statement_period_str}. Read-only examination of original bank movements.")
    audit, exceptions, recon = reconcile_bank_ledger(full_bank)
    first, second, third = st.columns(3)
    first.metric("Original bank rows", recon["rows"])
    second.metric("Unreconciled rows", recon["exceptions"])
    third.metric("Net balance differences", f"KSh {recon['difference']:,.2f}")
    if recon["exceptions"]:
        st.error("Balance differences require investigation against the original KCB statement. No source rows are changed.")
        st.dataframe(exceptions, width="stretch", hide_index=True)
    else:
        st.success("No arithmetic differences found between consecutive bank balances (source completeness not verified).")
    st.caption(f"Rows excluded from historical tenant analysis but retained in bank audit: {recon['excluded_from_legacy_analysis']}. Shared references are not treated as duplicates.")
    st.markdown("#### Full original bank statement — with audit columns")
    st.dataframe(audit, width="stretch", hide_index=True)
    st.download_button("Download READ-ONLY bank reconciliation (Excel)",
        data=export_reconciliation(audit, exceptions, recon),
        file_name="UNVERIFIED_KCB_Bank_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif module == "Annual P&L & iTax Statement":
    from financial_review_v1 import financial_period, review_bank_movements, excel_review_export
    st.subheader("Financial Review — Unclassified Bank Movements")
    st.warning("This is not a completed P&L or KRA computation. Credits are not automatically rent; debits are not automatically deductible expenses.")
    fy = st.selectbox("Financial year ending 30 June", [2026, 2025, 2024, 2027])
    period = st.selectbox("Reporting period", ["Annual", "Bi-Annual", "Quarterly"])
    subperiod = ""
    if period == "Bi-Annual":
        subperiod = st.selectbox("Half-year", ["H1", "H2"])
    elif period == "Quarterly":
        subperiod = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"])
    start, end = financial_period(fy, period, subperiod)
    st.info(f"Financial period: {start:%d %B %Y} – {end:%d %B %Y}")
    transactions, summary = review_bank_movements(backend.df_bank_full, start, end)
    if not summary["complete"]:
        st.error("INCOMPLETE BANK COVERAGE: uploaded statement does not span the selected period. A full financial report is unavailable.")
    else:
        st.warning("Date coverage alone does not establish correct accounting classifications.")
    first, second, third = st.columns(3)
    first.metric("Money IN (unclassified)", f"KSh {summary['in']:,.2f}")
    second.metric("Money OUT (unclassified)", f"KSh {summary['out']:,.2f}")
    third.metric("Records", summary["rows"])
    st.caption(f"Opening balance/zero-movement rows within selected period: {summary['nonmovement']}.")
    st.write("**Accounting profit: Not determined · Chargeable income: Not determined · KRA tax: Not determined.**")
    st.write("Verify each receipt, reversal, transfer, expense and loan principal/interest split. Loan principal is not a P&L deduction.")
    st.dataframe(transactions, width="stretch", hide_index=True)
    st.download_button("Download unverified bank review (Excel)",
        data=excel_review_export(transactions, summary, start, end),
        file_name=f"UNVERIFIED_FY{fy}_{period}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

