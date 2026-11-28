"""Section 03D: human-readable review of bank particulars. Absolutely no writes."""
import streamlit as st
import pandas as pd

from historical_review_human_evidence_v1 import build_human_review_sheet


def render_section_03d(original_bank_frame):
    with st.expander("Section 03D — Review dates, amounts and bank particulars (NO WRITES)", expanded=True):
        st.caption(
            "Examine the saved historical review decisions alongside original KCB dates, amounts "
            "and transaction particulars. Historical audit events contain review dates and bank "
            "references, but do not contain the original transaction amount or particulars. "
            "Suggested current-statement rows are NOT verified matches."
        )
        discrepancy = st.session_state.get("v1_section03b_result")
        if discrepancy is None:
            st.info("Run the Section 03B discrepancy report first. No extra statement is needed.")
            return
        if st.button("Show historical cases and bank particulars (read-only)",
                     key="v1_section03d_show_cases"):
            try:
                st.session_state["v1_section03d_evidence"] = build_human_review_sheet(
                    discrepancy, original_bank_frame
                )
            except (ValueError, KeyError, TypeError, OSError) as exc:
                st.session_state.pop("v1_section03d_evidence", None)
                st.error(f"Source inspection blocked: {exc}. No review records were changed.")
                return
        evidence = st.session_state.get("v1_section03d_evidence")
        if not evidence:
            st.info("Click the button above to display the transaction evidence in familiar bank-statement columns.")
            return
        cases = evidence["cases"]
        st.metric("Historical cases requiring human investigation", len(cases))
        labels = [f"Case {case['case']}: {case['previous_decision']} · "
                  f"{case['bank_references_from_audit'] or 'Reference not recorded'}"
                  for case in cases]
        index = st.selectbox("Select a historical review case", range(len(cases)),
                             format_func=lambda i: labels[i], key="v1_section03d_case")
        case = cases[index]
        st.markdown("**Previously saved review (preserved, not changed)**")
        st.dataframe(pd.DataFrame([case]).drop(
            columns=["historical_bank_row_id", "original_transaction_date_proven",
                     "original_amount_proven"], errors="ignore"
        ), hide_index=True, width="stretch")
        st.markdown("**Current KCB statement rows with the same bank reference — suggestions only**")
        matches = [c for c in evidence["reference_candidates"] if c["case"] == case["case"]]
        if matches:
            st.dataframe(pd.DataFrame(matches).drop(
                columns=["candidate_only_not_a_verified_match"]), hide_index=True, width="stretch")
            st.warning("A shared bank reference does not prove it is the same transaction. "
                       "Check the particulars, date and amount manually.")
        else:
            st.info("No transaction in the currently uploaded KCB statement shares this saved "
                    "audit reference. The historical transaction date and amount cannot be "
                    "recovered from the saved audit record alone.")
        st.markdown("**Search all rows in the current KCB statement**")
        query = st.text_input(
            "Search by tenant name, narration, bank reference, date or amount",
            key="v1_section03d_search", placeholder="e.g. Mash, cheque, 2025-11-10, 30000",
        ).strip()
        if query:
            all_rows = pd.DataFrame(evidence["full_current_statement"])
            columns = ["transaction_date", "value_date", "money_in_ksh",
                       "money_out_ksh", "bank_reference", "full_particulars"]
            mask = all_rows[columns].astype(str).apply(
                lambda column: column.str.contains(query, case=False, regex=False, na=False)
            ).any(axis=1)
            found = all_rows.loc[mask, columns]
            st.caption(f"{len(found)} current bank statement row(s) match the search text.")
            st.dataframe(found, hide_index=True, width="stretch")
        st.caption("No save or allocation buttons are present. Existing decisions remain intact.")
