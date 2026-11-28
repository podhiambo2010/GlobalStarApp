"""Section 03C — historical identity diagnostic, never a financial write."""
import io
import json

import pandas as pd
import streamlit as st

from migration_identity_recovery_v1_section03c import inspect_historical_identity, historical_tenancy_context
from historical_kcb_excel_v1_section03c import load_historical_kcb_xlsx


def render_section_03c(plan):
    with st.expander("Section 03C — Historical statement identity recovery (NO WRITES)", expanded=False):
        st.caption(
            "Investigates 16 preserved historical decisions using the local bank-review audit "
            "history and, optionally, an older normalized KCB export. No automatic reassignment."
        )
        discrepancy = st.session_state.get("v1_section03b_result")
        full_source = st.session_state.get("v1_section03b_full_source_result")
        if not discrepancy or not full_source:
            st.info("Complete the Section 03B discrepancy report AND full-source check in this session.")
            return
        history_csv = st.file_uploader(
            "Optional historical KCB statement — original Excel (.xlsx), or normalized CSV",
            type=["xlsx", "csv"], key="v1_section03c_historical_csv"
        )
        st.caption(
            "First run without an archive to inspect saved audit events. Original KCB Excel "
            "exports are read in memory and never change the currently uploaded statement."
        )
        if st.button("Investigate historical identities (read-only)", key="v1_section03c_run_button"):
            try:
                archived_frame = None
                if history_csv is not None:
                    if history_csv.name.lower().endswith(".xlsx"):
                        archived_frame, source_sheet = load_historical_kcb_xlsx(history_csv.getvalue())
                        st.caption(f"Historical Excel evidence read from sheet: {source_sheet}")
                    else:
                        archived_frame = pd.read_csv(io.BytesIO(history_csv.getvalue()),
                                                     dtype={"Ref_Clean": "string", "Bank Reference Number": "string"})
                report = inspect_historical_identity(discrepancy, full_source,
                                                     historical_bank=archived_frame)
                st.session_state["v1_section03c_report"] = report
            except (ValueError, KeyError, TypeError, OSError, UnicodeError,
                    json.JSONDecodeError, pd.errors.ParserError, ImportError) as exc:
                st.session_state.pop("v1_section03c_report", None)
                st.error(f"Identity inspection blocked: {exc}. No original decisions were altered.")
                return
        report = st.session_state.get("v1_section03c_report")
        if not report:
            st.info("No identity investigation has been run in this session.")
            return
        a, b, c = st.columns(3)
        a.metric("Preserved unmatched reviews", report["original_unmatched_reviews"])
        b.metric("Historical audit events", report["historical_audit_events_total"])
        c.metric("Historical export rows", report["historical_statement_rows"])
        st.warning("Read-only investigation. Approved imports: 0. Approved rent postings: 0.")
        st.json({
            "evidence_categories": report["evidence_categories"],
            "historical_review_audit_file_present": report["historical_review_audit_file_present"],
            "historical_statement_provided": report["historical_statement_provided"],
            "interpretation": report["interpretation"],
        })
        st.dataframe(report["review_records"], hide_index=True, width="stretch")
        st.subheader("Separate historical tenancy identity investigation")
        st.caption("Same-unit matches are search hints, not evidence of the earlier tenant.")
        st.json(historical_tenancy_context(plan, full_source))
        st.download_button(
            "Download Section 03C diagnostic (NO WRITES)",
            json.dumps(report, ensure_ascii=False, indent=2),
            file_name="GSIL_Section03C_HistoricalIdentity_NO_WRITES.json",
            mime="application/json",
            key="v1_section03c_download",
        )
