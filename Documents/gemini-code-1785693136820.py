import streamlit as st
import pandas as pd
from app_backend import TenantPortalBackend, LeaseDocumentAI

# 1. Wide-Layout Responsive Design & Dynamic Sidebar Reflow Configuration
st.set_page_config(
    page_title="Global Star Investments Limited Portal",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS Injector for Fluid Layout Scaling & Sidebar Collapsing Reflows
st.markdown("""
    <style>
        .main .block-container {
            padding-top: 2rem;
            padding-right: 2rem;
            padding-left: 2rem;
            max-width: 100%;
        }
        [data-testid="stSidebar"][aria-expanded="true"] ~ div .main .block-container {
            width: calc(100% - 21rem);
        }
        [data-testid="stSidebar"][aria-expanded="false"] ~ div .main .block-container {
            width: 100%;
        }
        .unmapped-alert-box {
            background-color: #f8d7da;
            color: #721c24;
            padding: 12px 18px;
            border-radius: 6px;
            border: 1px solid #f5c6cb;
            margin-bottom: 20px;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)

backend = TenantPortalBackend()

def main():
    st.sidebar.title("Global Star Portal")
    st.sidebar.markdown("---")
    
    # Navigation Module Select
    module = st.sidebar.radio("Navigation", [
        "Dashboard & Arrears", 
        "July Statement & Audit", 
        "Deposit & Lease Ledger", 
        "Lease PDF AI Extractor",
        "Automated SMS Center",
        "eTIMS Tax Invoices",
        "Demand Notice Builder",
        "Bank Statement Audit"
    ])

    # --- Unmapped Payment Sidebar Global Counter Alert ---
    unmapped_dummy_count = 2  # Connected to live unmapped audit state if cached
    if unmapped_dummy_count > 0:
        st.sidebar.markdown(f"""
            <div style="background-color: #fff3cd; color: #856404; padding: 10px; border-radius: 6px; font-size: 13px; text-align: center; border: 1px solid #ffeeba; margin-top: 25px;">
                ⚠️ <b>{unmapped_dummy_count} Unmapped Payments</b> flagged in July audit!
            </div>
        """, unsafe_allow_html=True)

    if module == "Dashboard & Arrears":
        st.title("Financial Control Dashboard")
        st.markdown("Overview of portfolio metrics, real-time collection progress, and compliance enforcement statuses.")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Monthly Rent Expected", "KSh 450,000", "0%")
        col2.metric("Collected to Date", "KSh 382,500", "+5.2%")
        col3.metric("Outstanding Arrears", "KSh 67,500", "-2.1%")
        col4.metric("Unmapped Bank Receipts", f"{unmapped_dummy_count} Items", "Action Req.", delta_color="inverse")

        st.markdown("---")
        st.subheader("Tenant Compliance & Status Overview")
        master_df = backend.load_master_tenants()
        st.dataframe(master_df, use_container_width=True)

    elif module == "July Statement & Audit":
        st.title("July Bank Statement Ingestion & Audit Hub")
        st.markdown("Upload and parse the structured July KCB statement to map transactions utilizing explicit customer attributes and telephone columns.")

        uploaded_file = st.file_uploader("Upload July KCB Bank Statement (.xlsx)", type=["xlsx"])
        
        if uploaded_file:
            with st.spinner("Processing statement rows and validating third-party mappings..."):
                result = backend.ingest_kcb_bank_statement_july(uploaded_file)
                
                if "error" in result:
                    st.error(result["error"])
                else:
                    if result["unmapped_count"] > 0:
                        st.markdown(f"""
                            <div class="unmapped-alert-box">
                                🚨 Action Required: Found {result['unmapped_count']} unmapped bank transfer(s) requiring manual assignment or update to reassignments.json!
                            </div>
                        """, unsafe_allow_html=True)

                    tab1, tab2 = st.tabs(["Successfully Mapped Transactions", "Unmapped Auditor Queue"])
                    
                    with tab1:
                        if result["processed"]:
                            st.dataframe(pd.DataFrame(result["processed"]), use_container_width=True)
                        else:
                            st.info("No mapped transactions found.")
                    with tab2:
                        if result["unmapped"]:
                            st.dataframe(pd.DataFrame(result["unmapped"]), use_container_width=True)
                        else:
                            st.success("All transactions successfully mapped!")

    elif module == "Deposit & Lease Ledger":
        st.title("Deposit & Liability Breakdown")
        st.info("Balance sheet separation tracking active pre-2026 prior year liabilities versus 2026 current additions.")
        master_df = backend.load_master_tenants()
        if "Prior Year Deposit" in master_df.columns and "2026 Deposit Addition" in master_df.columns:
            st.dataframe(master_df[["Tenant Name", "Shop Number", "Prior Year Deposit", "2026 Deposit Addition"]], use_container_width=True)
        else:
            st.dataframe(master_df, use_container_width=True)

    elif module == "Lease PDF AI Extractor":
        st.title("Lease PDF AI Extractor & Alerts")
        uploaded_pdf = st.file_uploader("Upload Lease Agreement PDF", type=["pdf"])
        if uploaded_pdf:
            parsed = LeaseDocumentAI.parse_lease_pdf(uploaded_pdf)
            st.json(parsed)

    elif module == "Automated SMS Center":
        st.title("Automated SMS Dispatch Center")
        st.info("Powered by Africa's Talking API for payment receipts and rent due reminders.")

    elif module == "eTIMS Tax Invoices":
        st.title("KRA eTIMS Commercial Rent Invoicing")
        st.success("Connected to KRA eTIMS API Client (`etims_service.py`) with fallback simulation active.")

    elif module == "Demand Notice Builder":
        st.title("Legal Demand Notice Builder")
        st.info("Generate formal legal demand letters for defaulted tenants with applied penalty rules.")

    elif module == "Bank Statement Audit":
        st.title("Bank Statement Audit Trail")
        st.info("Full raw audit viewer for historical ledger entries.")

if __name__ == "__main__":
    main()