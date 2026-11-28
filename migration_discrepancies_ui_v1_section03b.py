"""Section 03B discrepancy investigation — read-only, no resolution writes."""
import json

import streamlit as st

from migration_discrepancies_v1_section03b import investigate_discrepancies


def render_section_03b(plan):
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
        st.download_button(
            "Download Section 03B discrepancy report (review only)",
            json.dumps(result, indent=2, ensure_ascii=False),
            file_name="GSIL_Section03B_DISCREPANCIES_NO_WRITES.json",
            mime="application/json",
            key="v1_section03b_download",
        )
