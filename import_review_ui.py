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
CATEGORIES = {
    "unclassified_credit": "Incoming credit — not yet allocated",
    "rent_receipt_candidate": "Possible rent receipt (verify tenant)",
    "tenant_deposit_candidate": "Possible tenant deposit (liability)",
    "other_income_candidate": "Possible other income",
    "unclassified_debit": "Outgoing debit — investigate",
    "bank_charge_candidate": "Possible bank fee or charge",
    "loan_repayment_candidate": "Possible loan repayment",
    "operating_expense_candidate": "Possible operating expense",
    "internal_transfer_candidate": "Possible internal transfer",
    "reversal_candidate": "Possible reversal — match original movement",
    "opening_balance": "Opening balance — not a movement",
    "tenant_change": "Tenant change",
    "legitimate_vacancy": "Legitimate vacancy",
}
DIRECTIONS = {
    "money_in": "Money IN",
    "money_out": "Money OUT",
    "non_movement": "Non-movement",
    "invalid_both": "Invalid / both",
    "tenant_register": "Tenant register",
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
                 .select("id,source_kind,source_row_id,source_snapshot,suggested_classification,final_classification,decision,reason,reviewed_at,evidence_reference,movement_direction,accounting_category,shared_reference_count,classification_note")
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
    bank = [r for r in items if r["source_kind"] == "bank_statement"]
    incoming = [r for r in bank if r.get("movement_direction") == "money_in"]
    outgoing = [r for r in bank if r.get("movement_direction") == "money_out"]
    zero = [r for r in bank if r.get("movement_direction") == "non_movement"]
    d1,d2,d3 = st.columns(3)
    d1.metric("Money IN · bank rows", len(incoming))
    d2.metric("Money OUT · bank rows", len(outgoing))
    d3.metric("Non-movement rows", len(zero))
    def amount(rows, column):
        return sum(abs(float(r["source_snapshot"].get(column) or 0)) for r in rows)
    st.caption(
        f"Bank movements: KES {amount(incoming, 'money_in'):,.2f} IN · "
        f"KES {amount(outgoing, 'money_out'):,.2f} OUT. "
        "Bank credits are not automatically tenant rent; debits are not automatically expenses."
    )
    st.warning(
        "Automatic accounting categories are only suggestions. Shared bank references do not "
        "prove duplication. Reversals must be linked to their original entries. "
        "No production imports are enabled."
    )
    status = st.selectbox("Decision status", ["pending", "approved_import", "approved_no_import", "rejected", "all"])
    source = st.selectbox("Source", ["all", "bank_statement", "tenant_register"])
    direction = st.selectbox("Bank direction", ["all", "money_in", "money_out", "non_movement", "tenant_register"],
                             format_func=lambda x: "All directions" if x == "all" else DIRECTIONS.get(x,x))
    category_filter = st.selectbox("Accounting category", ["all"] + list(CATEGORIES),
                                   format_func=lambda x: "All categories" if x == "all" else CATEGORIES[x])
    selection = [r for r in items if (status == "all" or r["decision"] == status)
                 and (source == "all" or r["source_kind"] == source)
                 and (direction == "all" or r.get("movement_direction") == direction)
                 and (category_filter == "all" or r.get("accounting_category") == category_filter)]
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
        "Direction": DIRECTIONS.get(r.get("movement_direction"), "Not assessed"),
        "Accounting category": CATEGORIES.get(r.get("accounting_category"), "Not assessed"),
        "Same reference rows": r.get("shared_reference_count",0),
        "Suggested": CLASSES[r["suggested_classification"]],
        "Decision": r["decision"],
    } for r in selection]), hide_index=True, use_container_width=True)

    choice = st.selectbox("Select row for detailed review", range(len(selection)),
                          format_func=lambda i: label(selection[i]))
    item = selection[choice]
    st.json(item["source_snapshot"], expanded=False)
    st.write("Suggested classification:", CLASSES[item["suggested_classification"]])
    st.write("Movement:", DIRECTIONS.get(item.get("movement_direction"), "Not assessed"))
    st.write("Accounting category:", CATEGORIES.get(item.get("accounting_category"), "Not assessed"))
    st.caption(item.get("classification_note") or "")
    if (item.get("shared_reference_count") or 0)>1:
        st.warning(
            f"Bank reference appears on {item['shared_reference_count']} rows. "
            "Compare their dates, amounts and descriptions before deciding whether any are duplicates."
        )
    if item["decision"] != "pending":
        st.success(f"Finalized: {item['decision']} — {item.get('reason') or ''}")
    else:
        with st.form(f"decision_{item['id']}"):
            classification = st.selectbox("Confirmed classification", list(CLASSES),
                                          index=list(CLASSES).index(item["suggested_classification"]),
                                          format_func=lambda k: CLASSES[k])
            allowed_categories = (
                ["tenant_change", "legitimate_vacancy"] if item["source_kind"]=="tenant_register"
                else [k for k in CATEGORIES if k not in ("tenant_change", "legitimate_vacancy")]
            )
            default_category = item.get("accounting_category")
            category = st.selectbox("Accounting category (confirm, do not assume)",
                                    allowed_categories,
                                    index=allowed_categories.index(default_category) if default_category in allowed_categories else 0,
                                    format_func=lambda k: CATEGORIES[k])
            decision = st.selectbox("Decision", list(DECISIONS), format_func=lambda k: DECISIONS[k])
            reason = st.text_area("Reason / explanation (mandatory)")
            evidence = st.text_input("Supporting document / reconciliation reference (recommended)")
            submitted = st.form_submit_button("Record approval decision", disabled=not can_approve)
        if submitted:
            if not reason.strip():
                st.error("Provide a reason before recording a decision.")
            elif decision == "approved_import" and item.get("movement_direction") == "non_movement":
                st.error("Balance brought forward is not a bank transaction.")
            elif decision == "approved_import" and category in ("unclassified_credit", "unclassified_debit", "reversal_candidate", "opening_balance"):
                st.error("Unresolved categories cannot be approved for import. Investigate and reconcile first.")
            elif decision == "approved_import" and classification not in ("new_transaction", "tenant_change"):
                st.error("Only verified new transactions or tenant changes can be approved for import.")
            else:
                try:
                    sb.rpc("review_import_difference_v2", {
                        "p_item_id": item["id"],
                        "p_classification": classification,
                        "p_decision": decision,
                        "p_category": category,
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
