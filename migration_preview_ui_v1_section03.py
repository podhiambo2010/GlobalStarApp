"""Section 03 migration inspection: no import controls or database writes."""
import json

import streamlit as st

from migration_preview_v1_section03 import build_migration_preview


def render_section_03(plan):
    with st.expander("Section 03 — Controlled migration preview (NO WRITES)", expanded=False):
        st.caption(
            "Read-only preview of local identities, original bank rows and audit evidence. "
            "Every row is HELD; no imports, rent postings or approvals are possible here."
        )
        comparison = st.session_state.get("v1_section02_comparison")
        if not plan or not comparison:
            st.info("Run Section 02 read-only comparison before preparing the Section 03 preview.")
            return
        if st.button("Prepare Section 03 preview (no changes)", key="v1_section03_prepare_button"):
            try:
                preview = build_migration_preview(plan, comparison)
            except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
                st.error(
                    f"Preview blocked: {exc}. "
                    "No evidence was altered and no database writes were attempted."
                )
                return
            st.session_state["v1_section03_preview"] = preview
        preview = st.session_state.get("v1_section03_preview")
        if not preview:
            st.info("No migration preview has been prepared in this session.")
            return
        st.warning(
            f"HELD: {preview['preview_held_rows']} bank rows. "
            "Approved to import: 0. Approved rent postings: 0."
        )
        st.json(preview)
        st.download_button(
            "Download Section 03 review-only preview",
            json.dumps(preview, indent=2, ensure_ascii=False),
            file_name="GSIL_Section03_PREVIEW_NO_WRITES.json",
            mime="application/json",
            key="v1_section03_preview_download",
        )
