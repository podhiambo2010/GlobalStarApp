"""Controlled bank/tenant difference review. No production import actions."""
import os
import pandas as pd
import streamlit as st
from supabase import create_client

CLASSES = {
    "new_transaction": "New transaction",
    "existing_historical": "Existing historical transaction",
    "tenant_change": "Tenant change",
    "legitimate_vacancy": "Legitimate vacancy",
    "needs_investigation": "Needs investigation",
}
DECISIONS = {
    "approved_import": "Approve for future import",
    "approved_no_import": "Approve without import",
    "rejected": "Reject",
}
ORG = os.getenv("GLOBALSTAR_ORGANIZATION_ID", "5a767e49-cbc6-40cc-8c4e-17518eb76d13")


def _client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not (url and key):
        st.error("Configure SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (or SUPABASE_ANON_KEY) in server secrets.")
        return None
    if "_review_supabase" not in st.session_state:
        st.session_state["_review_supabase"] = create_client(url, key)
    return st.session_state["_review_supabase"]


def show_import_review():
    st.subheader("03 · Review and Approve Differences")
    st.info("Review-only workflow. This page never inserts or changes transactions, tenants, leases or units.")
    sb = _client()
    if sb is None:
        return

    session = sb.auth.get_session()
    if not session:
        with st.form("review_login"):
            email = st.text_input("Supabase account email")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Sign in for review")
        if login:
            try:
                sb.auth.sign_in_with_password({"email": email, "password": password})
                st.rerun()
            except Exception as exc:
                st.error(f"Authentication failed: {exc}")
        return

    user = sb.auth.get_user().user
    st.caption(f"Authenticated as {user.email}")
    if st.button("Sign out of review", key="review_signout"):
        sb.auth.sign_out()
        st.rerun()

    try:
        membership = (sb.table("organization_members")
                      .select("role").eq("organization_id", ORG)
                      .eq("user_id", user.id).limit(1).execute().data)
        role = membership[0]["role"] if membership else "none"
    except Exception:
        role = "unverified"
    can_approve = role in ("owner", "admin")
    st.caption(f"Membership: {role} · Approval permission: {'enabled' if can_approve else 'read-only'}")
    if not can_approve:
        st.warning("Approval is restricted to owner/admin. Current membership cannot approve financial differences.")

    try:
        items = (sb.table("import_review_items")
                 .select("id,source_kind,source_row_id,source_snapshot,suggested_classification,final_classification,decision,reason,reviewed_at,evidence_reference")
                 .eq("organization_id", ORG).order("source_kind").order("source_row_id")
                 .range(0, 999).execute().data or [])
    except Exception as exc:
        st.error(f"Could not load review queue: {exc}")
        return

    pending = sum(r["decision"] == "pending" for r in items)
    approved = sum(r["decision"] == "approved_import" for r in items)
    closed = sum(r["decision"] in ("approved_no_import", "rejected") for r in items)
    a,b,c = st.columns(3)
    a.metric("Pending", pending)
    b.metric("Approved for import (not imported)", approved)
    c.metric("Closed without import", closed)
    status = st.selectbox("Decision status", ["pending", "approved_import", "approved_no_import", "rejected", "all"])
    source = st.selectbox("Source", ["all", "bank_statement", "tenant_register"])
    selection = [r for r in items if (status == "all" or r["decision"] == status)
                 and (source == "all" or r["source_kind"] == source)]
    if not selection:
        st.info("No review rows match this filter.")
        return
    def label(r):
        snap = r["source_snapshot"]
        return (f"{r['source_kind']} #{r['source_row_id']} | "
                f"{snap.get('reference_number') or snap.get('tenant_name') or 'no reference'} | "
                f"{snap.get('money_in') or snap.get('money_out') or snap.get('monthly_rate') or ''}")

    st.dataframe(pd.DataFrame([{
        "Row": r["source_row_id"],
        "Source": r["source_kind"],
        "Reference / tenant": r["source_snapshot"].get("reference_number") or r["source_snapshot"].get("tenant_name"),
        "Money in": r["source_snapshot"].get("money_in"),
        "Money out": r["source_snapshot"].get("money_out"),
        "Suggested": CLASSES[r["suggested_classification"]],
        "Decision": r["decision"],
    } for r in selection]), hide_index=True, use_container_width=True)

    choice = st.selectbox("Select row for detailed review", range(len(selection)),
                          format_func=lambda i: label(selection[i]))
    item = selection[choice]
    st.json(item["source_snapshot"], expanded=False)
    st.write("Suggested classification:", CLASSES[item["suggested_classification"]])
    if item["decision"] != "pending":
        st.success(f"Finalized: {item['decision']} — {item.get('reason') or ''}")
    else:
        with st.form(f"decision_{item['id']}"):
            classification = st.selectbox("Confirmed classification", list(CLASSES),
                                          index=list(CLASSES).index(item["suggested_classification"]),
                                          format_func=lambda k: CLASSES[k])
            decision = st.selectbox("Decision", list(DECISIONS), format_func=lambda k: DECISIONS[k])
            reason = st.text_area("Reason / explanation (mandatory)")
            evidence = st.text_input("Supporting document / reconciliation reference (recommended)")
            submitted = st.form_submit_button("Record approval decision", disabled=not can_approve)
        if submitted:
            if not reason.strip():
                st.error("Provide a reason before recording a decision.")
            elif decision == "approved_import" and classification not in ("new_transaction", "tenant_change"):
                st.error("Only verified new transactions or tenant changes can be approved for import.")
            else:
                try:
                    sb.rpc("review_import_difference", {
                        "p_item_id": item["id"],
                        "p_classification": classification,
                        "p_decision": decision,
                        "p_reason": reason,
                        "p_evidence_reference": evidence or None,
                    }).execute()
                    st.success("Decision and audit entry saved. No live financial entry was created.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Review decision not saved: {exc}")

    try:
        events = (sb.table("import_review_audit")
                  .select("recorded_at,action,actor_id,reason,item_id")
                  .eq("organization_id", ORG)
                  .order("recorded_at", desc=True).limit(100).execute().data or [])
        with st.expander("Review audit trail"):
            if events:
                st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)
            else:
                st.caption("No approval decisions recorded yet.")
    except Exception as exc:
        st.warning(f"Audit history unavailable: {exc}")
