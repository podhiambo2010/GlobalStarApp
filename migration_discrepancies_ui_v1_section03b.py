"""Section 03B discrepancy investigation — read-only, no resolution writes."""
import json

import streamlit as st

from migration_discrepancies_v1_section03b import investigate_discrepancies
from migration_full_source_inspection_v1_section03b import inspect_full_source


def render_section_03b(plan, original_bank_frame=None):
    with st.expander("Section 03B — Historical review discrepancies (NO WRITES)", expanded=False):
        st.caption(
            "Inspect unmatched historical bank-row reviews and stale tenancy IDs. "
            "Prior decisions are preserved; no automatic reassignment, import or rent posting."
        )
        classified = st.session_state.get("v1_section03a_result")
        if not plan or not classified:
            st.info("Complete Section 03A evidence classification in this session first.")
            return
        if st.button("Investigate unmatched evidence (read-only)", key="v1_section03b_run_button"):
            try:
                st.session_state["v1_section03b_result"] = investigate_discrepancies(plan, classified)
            except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
                st.session_state.pop("v1_section03b_result", None)
                st.error(f"Investigation blocked: {exc}. No records were changed.")
                return
        result = st.session_state.get("v1_section03b_result")
        if not result:
            st.info("No discrepancy report has been generated in this session.")
            return
        a, b, c = st.columns(3)
        a.metric("Historical reviews", result["original_review_count"])
        b.metric("Unmatched bank reviews", result["unmatched_historical_reviews"])
        c.metric("Stale tenancy assignments", result["stale_tenancy_assignments_in_current_bank_rows"])
        st.warning("Investigation only. All affected records remain held; approved imports and rent postings: 0.")
        st.json({
            "unmatched_decisions_by_type": result["unmatched_decisions_by_type"],
            "possible_causes_not_confirmed": result["possible_causes_not_confirmed"],
            "historical_files_pending": result["historical_files_pending"],
        })
        st.subheader("Historical bank-row reviews absent from current source")
        st.dataframe(result["unmatched_review_details"], hide_index=True, width="stretch")
        st.subheader("Assigned tenancy IDs not found in current register")
        st.dataframe(result["stale_tenancy_details"], hide_index=True, width="stretch")
        st.divider()
        st.subheader("Full original statement verification (includes zero-value entries)")
        if original_bank_frame is None:
            st.info("Original bank dataframe unavailable; cannot inspect zero-amount rows.")
        elif st.button("Check full original KCB statement (read-only)", key="v1_section03b_full_source_button"):
            try:
                full = inspect_full_source(plan, result, original_bank_frame)
                st.session_state["v1_section03b_full_source_result"] = full
            except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
                st.session_state.pop("v1_section03b_full_source_result", None)
                st.error(f"Full-statement inspection blocked: {exc}. No decisions were changed.")
        full = st.session_state.get("v1_section03b_full_source_result")
        if full:
            st.json({
                "total_original_statement_rows_in_memory": full["total_original_statement_rows_in_memory"],
                "nonzero_migration_rows": full["nonzero_migration_rows"],
                "zero_amount_original_rows": full["zero_amount_original_rows"],
                "row_id_algorithm_consistent_with_source": full["row_id_algorithm_consistent_with_source"],
                "unmatched_match_categories": full["unmatched_match_categories"],
            })
            if not full["row_id_algorithm_consistent_with_source"]:
                st.error("Bank row IDs differ from regenerated IDs. Treat as investigation-only.")
            st.dataframe(full["unmatched_review_evidence"], hide_index=True, width="stretch")
            st.subheader("Historical tenancy identification — suggestions only")
            st.dataframe(full["stale_tenancy_evidence"], hide_index=True, width="stretch")
            st.download_button(
                "Download complete-source investigation (NO WRITES)",
                json.dumps(full, indent=2, ensure_ascii=False),
                file_name="GSIL_Section03B_FullSource_DIAGNOSTIC_ONLY.json",
                mime="application/json", key="v1_section03b_full_source_download",
            )
        st.download_button(
            "Download Section 03B discrepancy report (review only)",
            json.dumps(result, indent=2, ensure_ascii=False),
            file_name="GSIL_Section03B_DISCREPANCIES_NO_WRITES.json",
            mime="application/json",
            key="v1_section03b_download",
        )
