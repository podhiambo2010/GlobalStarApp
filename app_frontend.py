"""
Global Star Investments - Frontend Engine
==================================================
GOVERNANCE & ARCHITECTURE CONSTITUTION:
- Data Integrity: All financial/eTIMS calculations must be deterministic and audited.
- Security: Zero hardcoded secrets; environment variables (.env) are mandatory.
- Modularity: Strict separation between database layers, business logic, and UI.
"""

import os
import json
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

tenant_path = uploaded_tenant_file if uploaded_tenant_file is not None else "Tenants_Details.xlsx"
bank_path = uploaded_bank_file if uploaded_bank_file is not None else "KCB_Bank_Statement.xlsx"

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
    st.subheader(f"🏢 Portfolio Dashboard — Tenancy History ({backend.statement_month_str})")
    if {'Tenancy Record Status', 'Lease End Date'}.issubset(backend.df_tenants.columns):
        register, credits = backend.tenancy_turnover_report()
        st.info(
            f"Excel-only tenancy history. Reporting period: "
            f"{backend.statement_start_date:%d %b %Y} to "
            f"{backend.statement_end_date:%d %b %Y}. "
            "These are period figures, NOT confirmed lifetime arrears."
        )
        current_count = int((register["Report_Status"] == "Current").sum())
        former_count = int((register["Tenancy_Status"] == "former").sum())
        pending_count = int((credits["Allocation_Status"] == "Review required").sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current tenant records", current_count)
        c2.metric("Former tenant records", former_count)
        c3.metric("Expected period rent", f"KSh {register['Expected_Rent'].sum():,.2f}")
        c4.metric("Credits needing review", int(credits["Allocation_Status"].isin(["Review required", "Legacy decision: reverify", "Stale tenancy assignment: reverify", "Pending (reviewed)"]).sum()))
        st.caption(
            "Verified collections include only reviewed tenancy-specific assignments. Suggested matches remain provisional. "
            "Vacancies are not billed. Future tenancies are not billed before their commencement. "
            "A former occupant's end date stops further accrual, without erasing historical records."
        )
        cols = ["Shop #", "Tenancy_ID", "Tenant Name", "Tenancy_Status",
                "Report_Status", "Lease_Date_Parsed", "End_Actual", "Rent_Rate",
                "Expected_Rent", "Actual_Collected", "Provisional_Credits",
                "Deposit_Received", "Advance_Rent_Received", "Split_Current_Rent_Received", "Period_Difference", "Review_Required"]
        st.dataframe(register[cols], width="stretch", hide_index=True)
        st.warning(
            "Opening balances, security deposits, unapplied payments and bank credits "
            "require reconciliation. Period Difference is not an enforceable arrears balance."
        )
        if not credits.empty:
            with st.expander("Bank credits — identified provisionally or awaiting allocation"):
                cols_credits = [c for c in ["Transaction Date", "Transaction Details",
                                           "Money In Num", "Ref_Clean", "Allocation_Status",
                                           "Tenancy_ID"] if c in credits.columns]
                st.dataframe(credits[cols_credits], width="stretch", hide_index=True)
        if register["Review_Required"].any():
            st.error(f"{int(register['Review_Required'].sum())} tenancy record(s) require clarification.")
    else:
        st.error(
            "This workbook lacks Tenancy Record Status and Lease End Date. "
            "Upload the reviewed tenancy-history workbook; old shop-based figures "
            "are not reliable when tenants have changed."
        )

elif module == "Deposit & Lease Ledger":
    st.subheader("📋 Deposit & Lease Ledger")
    df_dep = backend.df_tenants.copy()
    
    total_leases = len(df_dep)
    total_deposit_liability = pd.to_numeric(df_dep['Deposit (KSh)'], errors='coerce').sum()
    if {'Tenancy Record Status', 'Lease End Date'}.issubset(df_dep.columns):
        st.warning("Deposit figures are historical workbook amounts, not verified liabilities. Former-tenant refunds and settlements must be reconciled before relying on totals.")
    
    col1, col2 = st.columns(2)
    col1.metric("Total Lease Records", total_leases)
    col2.metric("Deposits Recorded (Unverified)", f"KSh {total_deposit_liability:,.2f}")
    st.markdown("---")

    st.dataframe(df_dep[['Shop / Unit #', 'Tenant Name', 'Lease Date', 'Deposit (KSh)', 'Deposit_Timing', 'Lease_Type']], width='stretch')

elif module == "Unmapped Payment Auditor":
    if {'Tenancy Record Status', 'Lease End Date'}.issubset(backend.df_tenants.columns):
        st.subheader("🔍 Bank Credit Review — Individual Tenancies")
        register, credits = backend.tenancy_turnover_report()
        st.info("Decisions are recorded per original bank row, not per shared reference. Existing shop-based reviews are retained as legacy history.")
        st.warning("Do not classify deposits, owner transfers, duplicate/reversed credits or unidentified receipts as rent without documentary support.")
        st.download_button("Download tenancy review decisions (backup JSON)",
            data=json.dumps(backend.tenancy_reviews, indent=2),
            file_name="GlobalStar_V1_Tenancy_Bank_Review_Backup.json",
            mime="application/json")
        backup = st.file_uploader("Restore a previously downloaded review backup (optional)",
            type=["json"], key="turnover_review_backup")
        if backup is not None:
            try:
                restored = json.loads(backup.getvalue().decode("utf-8"))
                if not isinstance(restored, dict):
                    raise ValueError("Backup must contain a JSON object")
                bank_ids = set(backend.df_bank_unfiltered["Bank_Row_ID"])
                if not set(restored).issubset(bank_ids):
                    raise ValueError("Backup contains bank rows not present in this uploaded statement")
                if not all(isinstance(v, dict) and
                           v.get("decision") in {"assign", "exclude", "pending"}
                           for v in restored.values()):
                    raise ValueError("Backup contains an invalid review decision")
                st.warning("Restoring replaces current decisions; download your current backup first.")
                if st.button("Confirm restore of reviewed bank rows"):
                    from bank_review_v1 import write_review
                    write_review(backend.tenancy_review_path, restored)
                    backend.tenancy_reviews = restored
                    st.success("Review backup restored")
                    st.rerun()
            except (ValueError, UnicodeError) as exc:
                st.error(f"Backup could not be restored: {exc}")
        from bank_review_v1 import load_event_history
        with st.expander("Restore Excluded Transaction", expanded=False):
            excluded = credits[credits["Allocation_Status"].isin([
                "Excluded (legacy)", "Excluded (reviewed)",
                "Legacy decision: reverify",
            ])].copy()
            excluded = excluded[
                (excluded["Allocation_Status"] != "Legacy decision: reverify")
                | excluded["Legacy_Decision"].astype(str).str.contains(
                    "exclusion", case=False, na=False)
            ]
            if excluded.empty:
                st.info("No currently excluded bank credits to restore for this period.")
            else:
                st.dataframe(excluded[[col for col in [
                    "Transaction Date", "Transaction Details", "Money In Num",
                    "Ref_Clean", "Bank_Row_ID", "Allocation_Status"
                ] if col in excluded.columns]], hide_index=True, width="stretch")
                restore_options = excluded["Bank_Row_ID"].astype(str).tolist()
                restore_id = st.selectbox("Select excluded bank transaction",
                    restore_options, key="restore_excluded_row")
                restore_row = excluded[excluded["Bank_Row_ID"] == restore_id].iloc[0]
                st.caption(f"Selected amount KSh {float(restore_row['Money In Num']):,.2f}; reference {restore_row['Ref_Clean']}")
                restore_reason = st.text_input("Reason for restoring this exclusion",
                    key="restore_exclusion_reason",
                    placeholder="e.g. Raphael or Everlyne rent incorrectly excluded")
                acknowledge = st.checkbox(
                    "I verified the original bank row and intend to reverse this exclusion",
                    key="restore_exclusion_ack")
                if st.button("Restore Excluded Transaction", type="primary",
                             disabled=not acknowledge or not restore_reason.strip(),
                             key="restore_exclusion_confirm"):
                    try:
                        backend.save_tenancy_bank_review(
                            restore_id, "restore", reason=restore_reason)
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
                    else:
                        st.success("Exclusion reversed for this row. Original matching rules will run again.")
                        st.rerun()
        with st.expander("Exclusion History", expanded=False):
            history = load_event_history(backend.tenancy_event_history_path)
            if history:
                st.dataframe(pd.DataFrame(history).iloc[::-1], hide_index=True, width="stretch")
                st.download_button("Download exclusion and review history (JSON)",
                    data=json.dumps(history, indent=2),
                    file_name="GlobalStar_Bank_Review_History.json", mime="application/json")
            else:
                st.info("No new audit events recorded yet. Earlier legacy exclusions remain in ignored_transactions.json.")
        with st.expander("Split / Allocate Receipt — Deposit and Advance Rent", expanded=False):
            st.info("Use this for refundable deposits or prepaid rent, including payments made before a lease begins. It does not automatically recognise advance rent as earned income.")
            st.warning("The component total must equal a single original bank credit. If KSh 100,000, 60,000 and 40,000 are separate bank credits, split or classify each bank row individually.")
            eligible_split_statuses = {"Review required", "Pending (reviewed)",
                "Stale tenancy assignment: reverify"}
            mode = st.radio("Show bank receipts",
                ["Unmatched / Requires Review", "Provisional matches — needs reclassification"],
                horizontal=True, key="split_receipt_filter")
            split_options = credits.loc[
                ~credits["Bank_Row_ID"].isin(backend.receipt_splits)].copy()
            if mode == "Unmatched / Requires Review":
                split_options = split_options.loc[
                    split_options["Allocation_Status"].isin(eligible_split_statuses)]
            else:
                split_options = split_options.loc[
                    split_options["Allocation_Status"].isin({
                        "Identified (verify before notice)",
                        "Identified (legacy override, verify tenancy)"})]
            st.caption(f"{len(split_options)} eligible bank receipts; approved and excluded entries remain protected.")
            if split_options.empty:
                st.info("No eligible incoming credits available for splitting.")
            else:
                split_id = st.selectbox("Select exact original bank credit",
                    split_options["Bank_Row_ID"].astype(str).tolist(),
                    format_func=lambda rid: (
                        f"{split_options.loc[split_options['Bank_Row_ID'] == rid, 'Transaction Date'].iloc[0]} | "
                        f"KSh {float(split_options.loc[split_options['Bank_Row_ID'] == rid, 'Money In Num'].iloc[0]):,.2f} | "
                        f"{str(split_options.loc[split_options['Bank_Row_ID'] == rid, 'Transaction Details'].iloc[0])[:65]} | {rid}"),
                    key="split_bank_row")
                bank_receipt = split_options.loc[split_options["Bank_Row_ID"] == split_id].iloc[0]
                st.caption(f"Original bank amount: KSh {float(bank_receipt['Money In Num']):,.2f}; bank reference: {bank_receipt['Ref_Clean']}")
                valid_tenants = register[(~register["Review_Required"]) &
                    (register["Tenancy_Status"] != "vacancy")].copy()
                if valid_tenants.empty:
                    st.error("No valid tenant records available.")
                else:
                    split_tenancy = st.selectbox("Allocate to individual tenancy",
                        valid_tenants["Tenancy_ID"].astype(str).tolist(),
                        format_func=lambda tid: (
                            f"Shop {valid_tenants.loc[valid_tenants['Tenancy_ID'] == tid, 'Shop #'].iloc[0]} — "
                            f"{valid_tenants.loc[valid_tenants['Tenancy_ID'] == tid, 'Tenant Name'].iloc[0]} ({tid})"),
                        key="split_tenancy")
                    selected_tenant = valid_tenants.loc[valid_tenants["Tenancy_ID"] == split_tenancy].iloc[0]
                    nparts = st.number_input("Number of allocation components", min_value=1, max_value=8, value=1, step=1, key="split_parts")
                    parts = []
                    for i in range(int(nparts)):
                        st.markdown(f"**Component {i+1}**")
                        left, right = st.columns(2)
                        kind = left.selectbox("Classification", ["Security deposit", "Advance rent", "Current rent"],
                            key=f"split_kind_{i}")
                        amount = right.number_input("Amount (KSh)", min_value=0.0, value=0.0, step=100.0,
                            key=f"split_amount_{i}")
                        item = {"kind": {"Security deposit": "security_deposit",
                            "Advance rent": "advance_rent", "Current rent": "current_rent"}[kind],
                            "amount": amount}
                        if kind != "Security deposit":
                            lease_start = selected_tenant["Lease_Date_Parsed"].date()
                            ds, de = st.columns(2)
                            item["period_start"] = ds.date_input("Rental period from", value=lease_start,
                                key=f"split_start_{i}")
                            item["period_end"] = de.date_input("Rental period through", value=lease_start,
                                key=f"split_end_{i}")
                        parts.append(item)
                    total = sum(float(x["amount"]) for x in parts)
                    balance = float(bank_receipt["Money In Num"]) - total
                    st.caption(f"Components KSh {total:,.2f} | Unallocated difference KSh {balance:,.2f}")
                    supporting = st.text_input("Supporting receipt / evidence and reason",
                        key="split_evidence", placeholder="Receipt ID and pre-tenancy deposit/advance details")
                    approved = st.checkbox("I verified the receipt, individual tenancy and applicable rental periods",
                        key="split_confirm")
                    if st.button("Save verified receipt split", type="primary",
                        disabled=not approved or not supporting.strip() or abs(balance) > 0.005,
                        key="save_split"):
                        try:
                            backend.save_receipt_split(split_id, split_tenancy, parts, supporting)
                        except (ValueError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            st.success("Bank receipt split recorded. Deposit and advance rent kept separate from recognised rent.")
                            st.rerun()
            if backend.receipt_splits:
                st.markdown("**Saved splits (read only)**")
                st.dataframe(pd.DataFrame([
                    {"Bank_Row_ID": rid, "Tenancy_ID": val["tenancy_id"],
                     "Original_Credit_KSh": val["original_amount_cents"]/100,
                     "Security_Deposit_KSh": sum(x["amount_cents"] for x in val["components"] if x["kind"] == "security_deposit")/100,
                     "Advance_Rent_KSh": sum(x["amount_cents"] for x in val["components"] if x["kind"] == "advance_rent")/100,
                     "Current_Rent_KSh": sum(x["amount_cents"] for x in val["components"] if x["kind"] == "current_rent")/100}
                    for rid, val in backend.receipt_splits.items()]), hide_index=True, width="stretch")
                st.download_button("Download saved receipt splits (backup JSON)",
                    data=json.dumps(backend.receipt_splits, indent=2),
                    file_name="GlobalStar_Receipt_Splits_Backup.json", mime="application/json")
        counts = credits["Allocation_Status"].value_counts()
        st.caption(" | ".join(f"{k}: {v}" for k, v in counts.items()))
        st.caption("Existing automatic description matches are suggestions, not manually verified rent receipts.")
        include_matched = st.checkbox("Show already identified, approved and excluded bank credits",
            value=False, key="turnover_show_all_bank_credits")
        finished_statuses = {
            "Identified (verify before notice)",
            "Identified (legacy override, verify tenancy)",
            "Assigned (reviewed)",
            "Excluded (reviewed)",
            "Excluded (legacy)",
            "Split (reviewed)",
        }
        reviewable = credits.copy() if include_matched else credits[
            ~credits["Allocation_Status"].isin(finished_statuses)].copy()
        st.caption(f"Showing {len(reviewable)} transactions requiring intervention"
            if not include_matched else f"Showing all {len(reviewable)} credit transactions")
        display_cols = [x for x in ["Bank_Row_ID", "Transaction Date", "Transaction Details",
            "Money In Num", "Ref_Clean", "Allocation_Status", "Legacy_Decision",
            "Tenancy_ID"] if x in reviewable.columns]
        st.dataframe(reviewable[display_cols], width="stretch", hide_index=True)
        if not reviewable.empty:
            options = reviewable["Bank_Row_ID"].tolist()
            selected_id = st.selectbox("Select exact bank row", options,
                format_func=lambda rid: (
                    f"{str(reviewable.loc[reviewable['Bank_Row_ID'] == rid, 'Transaction Date'].iloc[0])} | "
                    f"KSh {float(reviewable.loc[reviewable['Bank_Row_ID'] == rid, 'Money In Num'].iloc[0]):,.2f} | "
                    f"{rid} | "
                    f"{str(reviewable.loc[reviewable['Bank_Row_ID'] == rid, 'Transaction Details'].iloc[0])[:75]}"
                ), key="turnover_row_selector")
            picked = reviewable[reviewable["Bank_Row_ID"] == selected_id].iloc[0]
            st.caption(f"Selected reference: {picked.get('Ref_Clean', '')} — Row ID: {selected_id}")
            st.caption(f"Current classification: {picked['Allocation_Status']}")
            decision_label = st.radio("Review decision",
                ["Pending further evidence", "Assign to a specific tenancy", "Exclude from rental allocations"],
                key="turnover_action")
            eligible = register[(~register["Review_Required"]) &
                (register["Tenancy_Status"] != "vacancy")].copy()
            chosen_tenancy = None
            if decision_label == "Assign to a specific tenancy":
                tenancy_options = eligible["Tenancy_ID"].astype(str).tolist()
                chosen_tenancy = st.selectbox("Select individual tenancy", tenancy_options,
                    format_func=lambda tid: (
                        f"{eligible.loc[eligible['Tenancy_ID'] == tid, 'Shop #'].iloc[0]} — "
                        f"{eligible.loc[eligible['Tenancy_ID'] == tid, 'Tenant Name'].iloc[0]} "
                        f"({tid})"
                    ))
                st.warning("Confirm this payment belongs to the selected tenancy and is rental income before saving.")
            reason = st.text_input("Evidence / reason for decision",
                placeholder="e.g., verified rent receipt, deposit, bank reversal, unconfirmed payer")
            confirm = st.checkbox("I checked the transaction description and supporting records",
                key="turnover_confirm")
            if st.button("Save bank-row review", type="primary", disabled=not confirm or not reason.strip()):
                decision = {"Pending further evidence": "pending",
                    "Assign to a specific tenancy": "assign",
                    "Exclude from rental allocations": "exclude"}[decision_label]
                try:
                    backend.save_tenancy_bank_review(selected_id, decision, chosen_tenancy, reason)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("Decision recorded against this bank row only.")
                    st.rerun()
        st.stop()

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
    st.markdown("Lease overview from the uploaded tenant workbook (no database connection).")
    lease_columns = [
        c for c in ["Shop #", "Tenant Name", "Monthly Rate", "Lease_Date_Parsed",
                    "Calculated_Lease_End", "Calculated_Status"]
        if c in backend.df_tenants.columns
    ]
    st.dataframe(backend.df_tenants[lease_columns], width="stretch")

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

        st.info("PDF extraction is review-only. Update the tenant workbook after verifying the extracted lease; no database records are changed.")

    if st.button("Clear All Reassignment Overrides"):
        if os.path.exists("reassignments.json"):
            os.remove("reassignments.json")
        backend.overrides = {}
        backend.reload_master_data()
        st.success("All manual reassignments cleared!")
        st.rerun()

elif module == "Arrears Payment Reminders":
    # Tenancy-aware V1 mode does not issue notices/invoices from provisional balances.
    if {'Tenancy Record Status', 'Lease End Date'}.issubset(backend.df_tenants.columns):
        st.warning(
            "This action is disabled in V1 tenancy-history mode. Current period "
            "calculations are provisional until tenancy-level bank allocations, "
            "opening balances, and contractual terms have been verified."
        )
        st.stop()

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
            app_password = st.text_input("Gmail App Password", value="bwng mwof eqrq jpaf", type="password", key="rem_pwd")

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
                value="EAASZC9wb7QSABSJ1na0JlElvfaXaIUcmt5db7hSIuDeJiZC6gj9I0W8U8h9UtNuRRxC7etpMbKavX7AJ8duQZBs9qK0yc8dcJG4fQGDUzp8AYaW5LNWZC4eZCYpS5A0Fl0F6fBiheKWRNL0dWq98tDZAtZCXPBRFvl1AEsJbDH9VbEOQ964Ilo0ZCTvIMycANAZDZD",
                type="password", key="shared_wa_token"
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
                value="atsk_6e221d752268968c8a03946e86dc940ea18196e37039b28c147a0f7ab0178d2baa3d9d04",
                type="password",
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
    # Tenancy-aware V1 mode does not issue notices/invoices from provisional balances.
    if {'Tenancy Record Status', 'Lease End Date'}.issubset(backend.df_tenants.columns):
        st.warning(
            "This action is disabled in V1 tenancy-history mode. Current period "
            "calculations are provisional until tenancy-level bank allocations, "
            "opening balances, and contractual terms have been verified."
        )
        st.stop()

    st.subheader("🧾 eTIMS Tax Invoices & Automated Monthly Billing")
    st.markdown(
        "Generate official KRA eTIMS tax invoices exclusively for compliant tenants who have fully settled their rent."
    )

    client = KRAeTIMSClient()
    init_success, cmc, msg = client.initialize_device()
    if init_success:
        st.success(f"Connected to KRA eTIMS API Client: {msg}")
    else:
        st.warning(f"eTIMS Sandbox Status: {msg}")

    st.markdown("---")
    st.subheader("📋 KRA eTIMS Certification & Compliance Package")
    if st.button("📄 Generate KRA Sandbox Compliance Summary Report"):
        with st.spinner("Generating formal compliance summary PDF..."):
            report_path = backend.generate_kra_compliance_summary_pdf()
            st.success(f"Compliance summary successfully generated: {report_path}")
            with open(report_path, "rb") as f:
                st.download_button(
                    "📥 Download KRA Compliance Summary PDF",
                    f,
                    file_name=os.path.basename(report_path),
                    mime="application/pdf"
                )
    st.markdown("---")

    df_arr = backend.calculate_tenant_arrears()
    
    df_compliant = df_arr[df_arr["Arrears_Balance"] <= 0].copy()

    billing_month = st.selectbox(
        "Billing Cycle Month",
        [
            backend.statement_month_str,
            "July 2026",
            "August 2026",
            "September 2026",
        ],
        key="etims_billing_cycle_month",
    )

    parts = billing_month.split()
    m_name = parts[0] if len(parts) > 0 else "General"
    y_name = parts[1] if len(parts) > 1 else str(datetime.now().year)
    cycle_invoice_dir = os.path.join("Invoices", y_name, m_name)
    
    issued_shops = set()
    if os.path.exists(cycle_invoice_dir):
        for fname in os.listdir(cycle_invoice_dir):
            if fname.startswith("eTIMS_Invoice_Shop_"):
                try:
                    s_id = int(fname.split("_")[3])
                    issued_shops.add(s_id)
                except Exception:
                    pass

    df_pending_etims = df_compliant[~df_compliant["Shop #"].isin(issued_shops)]

    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        paybill = st.text_input("Paybill Business No", "522522", key="etims_pb")
        paybill_acc = st.text_input("Paybill Account Number", "1285399528", key="etims_pacc")
        branch_name = st.text_input("Bank Branch Name", "Siaya", key="etims_brn")
    with col_cfg2:
        bank_code = st.text_input("Bank Code", "01", key="etims_bcode")
        branch_code = st.text_input("Branch Code", "012", key="etims_brcode")
        swift_code = st.text_input("SWIFT Code", "KCBLKENX", key="etims_swift")

    st.markdown("---")
    st.markdown("### 🏢 Bulk Operations (Compliant & Pending Tenants)")
    sender_email = st.text_input(
        "Sender Gmail Address", "globalstarinvest@gmail.com", key="etims_sender"
    )
    app_password = st.text_input(
        "Gmail App Password",
        value="bwng mwof eqrq jpaf",
        type="password",
        key="etims_pwd"
    )

    st.info(f"Total Compliant Tenants: {len(df_compliant)} | Already Issued This Cycle: {len(issued_shops)} | Pending Dispatch: {len(df_pending_etims)}")

    if st.button("🚀 Bulk Generate Invoices & Email Pending Tenants", type="primary"):
        if df_pending_etims.empty:
            st.warning("No pending compliant tenants require eTIMS invoicing for this billing cycle.")
        elif not app_password:
            st.error("Please enter your Gmail App Password.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            total_pending = len(df_pending_etims)
            success_count = 0

            for i, (_, row) in enumerate(df_pending_etims.iterrows()):
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
                        backend.send_etims_invoice_email(
                            recipient_email=t_email,
                            tenant_name=t_name,
                            pdf_path=pdf_inv,
                            sender_email=sender_email,
                            app_password=app_password,
                            shop_no=s_no,
                            billing_month=billing_month,
                        )
                    success_count += 1
                except Exception as e:
                    st.warning(f"Error processing Shop #{s_no}: {str(e)}")
                progress_bar.progress((i + 1) / total_pending)

            status_text.empty()
            progress_bar.empty()
            st.success(
                "Successfully generated eTIMS invoices and dispatched transmittal emails for"
                f" {success_count} out of {total_pending} pending tenants!"
            )

    st.markdown("---")
    st.markdown("### 👤 Single Tenant Actions (All Tenants / Override Eligible)")
    
    tenant_labels = [
        f"Shop #{row['Shop #']} - {row['Tenant Name']} (Arrears: KSh {row['Arrears_Balance']:,.2f})"
        for _, row in df_arr.iterrows()
    ]
    selected_label = st.selectbox(
        "Select Tenant Shop for eTIMS Action", tenant_labels, key="etims_single_select"
    )
    selected_shop = int(selected_label.split("Shop #")[1].split(" - ")[0])
    tenant_row = df_arr[df_arr["Shop #"] == selected_shop].iloc[0]

    t_name = tenant_row["Tenant Name"]
    t_pin = str(tenant_row.get("KRA PIN Certificate", "P051548911H"))
    if t_pin == "nan" or not t_pin:
        t_pin = "P051548911H"
    monthly_rent = float(tenant_row["Monthly Rate"])
    t_email = str(tenant_row.get("Email Address", ""))
    if t_email == "nan":
        t_email = ""
    
    arrears_val = float(tenant_row["Arrears_Balance"])
    is_already_issued = selected_shop in issued_shops
    status_badge = "⚠️ Already Issued This Cycle" if is_already_issued else "✅ Ready for Dispatch"

    st.write(
        f"**Tenant:** {t_name} | **Shop:** #{selected_shop} | **Monthly Rate:** KSh"
        f" {monthly_rent:,.2f} | **Arrears:** KSh {arrears_val:,.2f} | **Status:** {status_badge}"
    )

    # Waiver checkbox constrained ONLY to delinquent tenants (Arrears > 0)
    waiver_override = False
    if arrears_val > 0:
        waiver_override = st.checkbox(
            f"🔓 Grant Temporary eTIMS Waiver / Override for Delinquent Tenant: {t_name}",
            value=False,
            key=f"waiver_{selected_shop}"
        )

    is_eligible = (arrears_val <= 0) or waiver_override

    if not is_eligible:
        st.warning("⚠️ This tenant has outstanding arrears. eTIMS invoice generation is restricted unless a temporary override waiver is granted above.")
    else:
        if waiver_override:
            st.info("ℹ️ Waiver active: Bypassing arrears validation for this session.")

        if st.button("📄 Generate Selected eTIMS Invoice PDF", key="gen_inv_btn"):
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
                kra_pin=t_pin,
            )
            st.success(f"Generated: {pdf_invoice}")
            with open(pdf_invoice, "rb") as f:
                st.download_button(
                    "📥 Download Invoice PDF",
                    f,
                    file_name=os.path.basename(pdf_invoice),
                    key=f"dl_inv_{selected_shop}"
                )

        recipient_email = st.text_input(
            "Recipient Tenant Email", value=t_email, key=f"etims_recipient_{selected_shop}"
        )
        
        if st.button("📤 Send Selected eTIMS Invoice via Email", key="send_etims_email_btn"):
            with st.spinner("Generating and sending official eTIMS tax invoice..."):
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
                    kra_pin=t_pin,
                )
                
                success, msg = backend.send_etims_invoice_email(
                    recipient_email=recipient_email,
                    tenant_name=t_name,
                    pdf_path=pdf_invoice,
                    sender_email=sender_email,
                    app_password=app_password,
                    shop_no=int(selected_shop),
                    billing_month=billing_month,
                )

                if success:
                    st.success(f"Official eTIMS Tax Invoice successfully transmitted to {t_name} ({recipient_email})!")
                else:
                    st.error(msg)

elif module == "Bank Statement Audit":
  st.subheader("🏦 KCB Bank Statement Audit & Reconciliation")
  st.markdown(
      "Displaying complete bank statement records for"
      f" **{backend.statement_period_str}** (Total Records:"
      f" {len(backend.df_bank)})"
  )
  st.dataframe(backend.df_bank, width="stretch")

elif module == "Annual P&L & iTax Statement":
  st.subheader("📊 Financial P&L Statement & KRA Tax Obligations")
  st.markdown("Automated financial statement aggregation with strict date-range filtering for Annual, Bi-Annual, or Quarterly returns.")

  col_per1, col_per2 = st.columns(2)
  with col_per1:
      report_type = st.selectbox("Reporting Period Type", ["Annual", "Bi-Annual (H1/H2)", "Quarterly (Q1-Q4)"], index=0)
  with col_per2:
      fiscal_year_end = st.selectbox("Select Fiscal Year Ending (FY)", [2026, 2025, 2024], index=0)

  base_year = fiscal_year_end - 1
  
  if report_type == "Annual":
      start_date = pd.Timestamp(f"{base_year}-03-01")
      end_date = pd.Timestamp(f"{fiscal_year_end}-02-28")
      period_label = f"Annual P&L (Mar 01, {base_year} – Feb 28, {fiscal_year_end})"
  elif report_type == "Bi-Annual (H1/H2)":
      half = st.selectbox("Select Half-Year", ["H1 (Mar 01 – Aug 31)", "H2 (Sep 01 – Feb 28)"])
      if "H1" in half:
          start_date = pd.Timestamp(f"{base_year}-03-01")
          end_date = pd.Timestamp(f"{base_year}-08-31")
          period_label = f"H1 Bi-Annual P&L ({base_year})"
      else:
          start_date = pd.Timestamp(f"{base_year}-09-01")
          end_date = pd.Timestamp(f"{fiscal_year_end}-02-28")
          period_label = f"H2 Bi-Annual P&L ({fiscal_year_end})"
  else:
      quarter = st.selectbox("Select Quarter", ["Q1 (Mar – May)", "Q2 (Jun – Aug)", "Q3 (Sep – Nov)", "Q4 (Dec – Feb)"])
      if "Q1" in quarter:
          start_date, end_date = pd.Timestamp(f"{base_year}-03-01"), pd.Timestamp(f"{base_year}-05-31")
      elif "Q2" in quarter:
          start_date, end_date = pd.Timestamp(f"{base_year}-06-01"), pd.Timestamp(f"{base_year}-08-31")
      elif "Q3" in quarter:
          start_date, end_date = pd.Timestamp(f"{base_year}-09-01"), pd.Timestamp(f"{base_year}-11-30")
      else:
          start_date, end_date = pd.Timestamp(f"{base_year}-12-01"), pd.Timestamp(f"{fiscal_year_end}-02-28")
      period_label = f"{quarter} P&L ({fiscal_year_end})"

  st.info(f"📅 **Active Statement Period Filter:** {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}")
  st.markdown("---")

  df_bank_filtered = backend.df_bank.copy()
  df_bank_filtered['Parsed_Date'] = pd.to_datetime(df_bank_filtered['Transaction Date'].astype(str).str.strip(), format='%d.%m.%Y', errors='coerce')
  
  df_period = df_bank_filtered[(df_bank_filtered['Parsed_Date'] >= start_date) & (df_bank_filtered['Parsed_Date'] <= end_date)]

  actual_bank_revenue = float(df_period['Money In Num'].sum())

  st.markdown("### **1. Operating Revenue**")
  col_rev1, col_rev2 = st.columns(2)
  with col_rev1:
      gross_rental_income = st.number_input("Gross Rental Income / Bank Collections (KSh)", value=actual_bank_revenue, step=1000.0)
  with col_rev2:
      other_business_income = st.number_input("Other Income (Water Point / Ancillary) (KSh)", value=0.0, step=1000.0)
      
  total_revenue = gross_rental_income + other_business_income
  st.metric("Total Gross Revenue", f"KSh {total_revenue:,.2f}")
  st.markdown("---")
  
  st.markdown("### **2. Operating Expenses & Loan Repayments (Filtered by Period)**")
  
  df_out = df_period.copy()
  money_out_col = [c for c in df_out.columns if 'Money Out' in str(c)][0]
  df_out['Money_Out_Num'] = pd.to_numeric(df_out[money_out_col].astype(str).str.replace(',', '').str.replace('(', '').str.replace(')', '').str.strip(), errors='coerce').fillna(0).abs()
  df_out_valid = df_out[df_out['Money_Out_Num'] > 0].copy()

  def categorize_outflow(row):
      desc = str(row['Transaction Details']).upper()
      amt = row['Money_Out_Num']
      
      if "AA LOAN REPAYME" in desc:
          return ('Loan Repayment', amt)
          
      if "254723562286" in desc:
          parts = desc.split('254723562286-')
          sub_desc = parts[1].split('MOBEE')[0].strip() if len(parts) > 1 else desc
          
          if any(k in sub_desc for k in ['LOAN REPAYMENT']):
              return ('Loan Repayment', amt)
          elif any(k in sub_desc for k in ['HW MATERIAL', 'HARDWARE', 'REPAIR', 'MAINTENANCE', 'VEHICLE REPAIR', 'COMPUTER']):
              return ('Repairs & Hardware', amt)
          elif any(k in sub_desc for k in ['KPLC', 'WATER', 'UTILITY']):
              return ('Utilities', amt)
          elif any(k in sub_desc for k in ['WAGE', 'LABOR', 'SALARY', 'STAFF ADVANCE', 'CASUAL LABOR', 'STAFF WAGES']):
              return ('Wages & Labor', amt)
          elif any(k in sub_desc for k in ['ITAX', 'TAX']):
              return ('Admin & Taxes', amt)
          else:
              return ('Miscellaneous', amt)
              
      if any(k in desc for k in ['WAGE', 'LABOR', 'SALARY']):
          return ('Wages & Labor', amt)
      elif any(k in desc for k in ['HW MATERIAL', 'HARDWARE', 'REPAIR', 'MAINTENANCE']):
          return ('Repairs & Hardware', amt)
      elif any(k in desc for k in ['KPLC', 'WATER', 'UTILITY']):
          return ('Utilities', amt)
      elif any(k in desc for k in ['ITAX', 'TAX']):
          return ('Admin & Taxes', amt)
      elif any(k in desc for k in ['CHARGE', 'INTEREST', 'SWIFT', 'EFT']):
          return ('Bank Charges & Fees', amt)
      else:
          return ('Miscellaneous', amt)

  cat_results = df_out_valid.apply(categorize_outflow, axis=1)
  df_out_valid['Category'] = [r[0] for r in cat_results]
  df_out_valid['Parsed_Amt'] = [r[1] for r in cat_results]
  
  cat_sums = df_out_valid.groupby('Category')['Parsed_Amt'].sum().to_dict()

  col_exp1, col_exp2 = st.columns(2)
  with col_exp1:
      repairs_maintenance = st.number_input("Repairs, Electrical & Hardware Maintenance (KSh)", value=float(cat_sums.get('Repairs & Hardware', 0.0)), step=1000.0)
      utilities_exp = st.number_input("Utilities & Services (KPLC / Water) (KSh)", value=float(cat_sums.get('Utilities', 0.0)), step=1000.0)
      wages_labor = st.number_input("Wages, Labor & Staff Costs (KSh)", value=float(cat_sums.get('Wages & Labor', 0.0)), step=1000.0)
  with col_exp2:
      admin_legal_fees = st.number_input("Administrative, iTax & Professional Fees (KSh)", value=float(cat_sums.get('Admin & Taxes', 0.0)), step=1000.0)
      bank_charges = st.number_input("Bank Charges & Interest Fees (KSh)", value=float(cat_sums.get('Bank Charges & Fees', 0.0)), step=1000.0)
      loan_repayments = st.number_input("Total Loan Principal Repayments Paid (KSh)", value=float(cat_sums.get('Loan Repayment', 0.0)), step=1000.0)
        
  total_expenses = (repairs_maintenance + utilities_exp + wages_labor + 
                    admin_legal_fees + bank_charges)
  
  col_tot1, col_tot2 = st.columns(2)
  col_tot1.metric("Total Allowable Operating Expenses", f"KSh {total_expenses:,.2f}")
  col_tot2.metric("Total Loan Repayments Deducted", f"KSh {loan_repayments:,.2f}")
  st.markdown("---")
  
  st.markdown("### **3. Net Profit & Chargeable Income Deduction**")
  net_profit_before_loan = total_revenue - total_expenses
  chargeable_income = max(0.0, net_profit_before_loan - loan_repayments)
  estimated_tax = chargeable_income * 0.30
  
  col_np1, col_np2, col_np3 = st.columns(3)
  col_np1.metric("Net Profit Before Loan", f"KSh {net_profit_before_loan:,.2f}")
  col_np2.metric("Final Chargeable Income", f"KSh {chargeable_income:,.2f}")
  col_np3.metric("Estimated Tax Payable (30%)", f"KSh {estimated_tax:,.2f}")
  
  st.markdown("---")
  if st.button("📥 Export Detailed Categorized P&L Report to Excel", type="primary"):
      output_dir = "P_L_Reports"
      os.makedirs(output_dir, exist_ok=True)
      output_path = os.path.join(output_dir, f"PL_Report_{report_type.replace(' ', '_')}_{fiscal_year_end}.xlsx")
      
      with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
          summary_data = {
              "Financial Item": [
                  "Reporting Period",
                  "Gross Rental Income / Bank Collections",
                  "Other Business Income",
                  "Total Gross Revenue",
                  "Repairs, Electrical & Hardware Maintenance",
                  "Utilities & Services (KPLC / Water)",
                  "Wages, Labor & Staff Costs",
                  "Administrative, iTax & Professional Fees",
                  "Bank Charges & Interest Fees",
                  "Total Allowable Operating Expenses",
                  "Net Profit Before Loan Deduction",
                  "Total Loan Principal Repayments Paid",
                  "Final Chargeable Income",
                  "Estimated Corporation Tax Payable (30%)"
              ],
              "Amount (KSh)": [
                  period_label,
                  total_revenue,
                  other_business_income,
                  total_revenue,
                  repairs_maintenance,
                  utilities_exp,
                  wages_labor,
                  admin_legal_fees,
                  bank_charges,
                  total_expenses,
                  net_profit_before_loan,
                  loan_repayments,
                  chargeable_income,
                  estimated_tax
              ]
          }
          df_summary = pd.DataFrame(summary_data)
          df_summary.to_excel(writer, sheet_name='P_L_Summary', index=False)
          
          export_cols = [c for c in ['Transaction Date', 'Transaction Details', 'Money_Out_Num', 'Category', 'Bank Reference Number'] if c in df_out_valid.columns]
          df_out_valid[export_cols].to_excel(writer, sheet_name='Detailed_Outflows', index=False)
          
      st.success(f"Detailed P&L report for **{period_label}** successfully exported to `{output_path}`!")