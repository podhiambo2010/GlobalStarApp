"""Section 02: read-only comparison UI for the dedicated Streamlit schema."""
import json
import os

import streamlit as st

from supabase_compare_v1_readonly import compare_summary, read_remote_state


def _configured_readonly_dsn():
    """Use a temporary environment override or private local Streamlit secrets."""
    temporary = os.environ.get("GS_V1_READONLY_DSN", "").strip()
    if temporary:
        return temporary
    try:
        return str(st.secrets.get("GS_V1_READONLY_DSN", "")).strip()
    except (FileNotFoundError, KeyError):
        return ""
    except st.errors.StreamlitSecretNotFoundError:
        return ""


def render_section_02(plan):
    with st.expander("Section 02 — Compare with Supabase (read-only)", expanded=False):
        st.caption(
            "Target: GlobalStarInvestmentsDB / gs_streamlit_v1. "
            "No tenant, payment, bank transaction, or audit event is imported or posted. "
            "Financial evidence remains local."
        )
        if not plan:
            st.warning("A valid Stage 1D dry-run manifest must be prepared before comparison.")
            return
        dsn = _configured_readonly_dsn()
        if not dsn:
            st.info(
                "Read-only connection not configured. Run the one-time local setup "
                "(python setup_gs_v1_connection.py) to create the private "
                ".streamlit/secrets.toml file. Never share credentials in chat or GitHub."
            )
            return
        if st.button("Run Section 02 read-only comparison", key="v1_section02_compare"):
            try:
                counts, fingerprints = read_remote_state(dsn=dsn)
                result = compare_summary(plan, counts, fingerprints)
                st.session_state["v1_section02_comparison"] = result
            except (ValueError, RuntimeError, PermissionError, OSError, ImportError) as exc:
                st.error(f"Read-only comparison could not complete: {exc.__class__.__name__}. "
                         "Check the dedicated account, database permissions and network. No import occurred.")
                return
        result = st.session_state.get("v1_section02_comparison")
        if not result:
            st.info("No remote comparison has been run in this session.")
            return
        st.success("Read-only comparison complete. No financial data was imported.")
        st.json(result)
        st.download_button(
            "Download comparison summary (no raw bank narrations)",
            json.dumps(result, indent=2),
            file_name="GSIL_Section02_readonly_comparison.json",
            mime="application/json", key="v1_section02_summary_download",
        )
