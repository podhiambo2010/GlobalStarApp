"""Section 03A held evidence classification UI; never posts transactions."""
import json

import streamlit as st

from migration_classification_v1_section03a import classify_evidence


def render_section_03a(plan):
    with st.expander("Section 03A — Evidence classification and migration readiness (NO WRITES)", expanded=False):
        st.caption(
            "Matches existing reviews by the original Bank_Row_ID. Separates cheque "
            "deposit / reversal / cleared credit, exclusions, pending decisions, "
            "and unreviewed bank rows. No bank rows are approved for import or rent posting."
        )
        preview = st.session_state.get("v1_section03_preview")
        if not plan or not preview:
            st.info("Prepare Section 03 preview before classifying individual bank evidence.")
            return
        if st.button("Classify evidence (read-only)", key="v1_section03a_classify_button"):
            try:
                st.session_state["v1_section03a_result"] = classify_evidence(plan, preview)
            except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
                st.session_state.pop("v1_section03a_result", None)
                st.error(f"Classification blocked: {exc}. No bank or database records were changed.")
                return
        result = st.session_state.get("v1_section03a_result")
        if not result:
            st.info("No current evidence classification has been produced.")
            return
        st.warning(
            f"HELD: {result['total_original_bank_rows']} original bank rows. "
            "Approved imports: 0. Approved rent postings: 0."
        )
        st.subheader("Review categories")
        st.json({
            "total_original_bank_rows": result["total_original_bank_rows"],
            "matched_review_decisions": result["matched_review_decisions"],
            "orphan_review_decisions": result["orphan_review_decisions"],
            "cheque_related_bank_rows": result["cheque_related_bank_rows"],
            "classification_counts": result["classification_counts"],
            "stage_1h_current_cheques": result["stage_1h_current_cheques"],
            "stage_1i_current_allocation_decisions_not_posted": result[
                "stage_1i_current_allocation_decisions_not_posted"
            ],
            "historical_file_warnings": result["historical_file_warnings"],
        })
        if result["orphan_review_decisions"]:
            st.error("Some prior review bank row IDs do not occur in the uploaded statement. "
                     "Investigate before any future migration.")
        st.caption("The classification table contains original row IDs and review categories only.")
        st.dataframe(result["row_classifications"], hide_index=True, width="stretch")
        st.download_button(
            "Download Section 03A classification (review only)",
            json.dumps(result, indent=2, ensure_ascii=False),
            file_name="GSIL_Section03A_CLASSIFICATION_NO_WRITES.json",
            mime="application/json",
            key="v1_section03a_download",
        )
