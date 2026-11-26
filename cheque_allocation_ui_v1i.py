"""Stage 1I Streamlit review UI — no bank mutation, no rent ledger writes."""
from datetime import date
import json

import streamlit as st

from cheque_allocation_v1i import eligible_clearance, latest_allocations, record_allocation


def render_stage_1i(returned_cheques, review_register,
                    clearance_path="cheque_clearance_reviews_v1h.json",
                    allocation_path="cheque_allocations_v1i.json"):
    st.subheader("Stage 1I — Cleared cheque rent allocation review")
    st.caption(
        "Only the later successful bank credit may be allocated. This is an "
        "audited allocation decision, NOT a payment posted to the tenant ledger "
        "or Supabase. Original deposits, reversals and Stage 1H decisions remain unchanged."
    )
    try:
        existing = latest_allocations(allocation_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Stage 1I allocation register needs repair; no saves permitted: {exc}")
        return
    candidates = {}
    for pair in returned_cheques:
        later = pair.get("later_credit_candidates", [])
        if len(later) != 1:
            continue
        bank = later[0]
        credit_id = str(bank.get("bank_row_id", ""))
        if not credit_id:
            continue
        try:
            source = eligible_clearance(clearance_path, credit_id)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if (str(source.get("original_credit_row_id")) != str(pair.get("credit_row_id"))
                or str(source.get("returned_debit_row_id")) != str(pair.get("debit_row_id"))
                or str(source.get("successful_credit_reference")) != str(bank.get("reference"))
                or str(source.get("successful_credit_date")) != str(bank.get("date"))
                or str(source.get("amount_ksh")) != str(pair.get("amount_ksh"))):
            st.error(f"Cheque {pair.get('cheque_number')}: bank evidence conflicts with Stage 1H. Investigate.")
            continue
        if str(bank.get("date")) != "2025-11-11":
            continue
        if credit_id in candidates:
            st.error(f"Bank credit {credit_id} appears twice in returned cheque candidates; allocation blocked.")
            candidates[credit_id] = None
            continue
        candidates[credit_id] = source
    valid_candidates = {key: val for key, val in candidates.items() if val is not None}
    if not valid_candidates:
        st.info("No bank-cleared, 11 November 2025 cheque credits are eligible for allocation.")
        return
    for credit_id, source in valid_candidates.items():
        cheque = str(source["cheque_number"])
        current = existing.get(credit_id)
        with st.container(border=True):
            st.markdown(
                f"**Cheque {cheque} — {source['tenant_name']} — "
                f"KSh {source['amount_ksh']}**"
            )
            st.caption(
                f"Successful credit: {source['successful_credit_date']} | "
                f"Bank reference: {source['successful_credit_reference']} | "
                f"Bank row: {credit_id}"
            )
            st.caption(
                f"Original deposit {source['original_credit_row_id']} and "
                f"returned debit {source['returned_debit_row_id']} cancel to zero."
            )
            if current:
                prior_parts = current.get("allocations") or [
                    {"rent_period": current["rent_period"], "amount_ksh": current["amount_ksh"]}
                ]
                breakdown = ", ".join(
                    f"{part['rent_period']}: KSh {part['amount_ksh']}"
                    for part in prior_parts
                )
                st.success(
                    f"Allocation approved: {breakdown}. "
                    "Ledger posting still pending. Save locked."
                )
                amend = st.checkbox(
                    "Amend existing allocation decision (audited)",
                    key=f"v1i_amend_{cheque}_{credit_id}",
                )
                if not amend:
                    continue
            else:
                amend = False

            eligible_tenancies = {
                str(row["Tenancy_ID"]): str(row["Tenant Name"])
                for _, row in review_register.iterrows()
                if str(row.get("Tenancy_Status", "")) != "vacancy"
            }
            tenancy_id = str(source["tenancy_id"])
            if tenancy_id not in eligible_tenancies:
                st.error("Stage 1H tenancy is not in the current tenancy register. Allocation blocked.")
                continue
            st.text_input(
                "Verified tenancy (locked to Stage 1H)",
                value=f"{eligible_tenancies[tenancy_id]} — {tenancy_id}",
                disabled=True, key=f"v1i_tenancy_{cheque}_{credit_id}",
            )
            is_quarterly = cheque == "4525"
            if is_quarterly:
                st.info(
                    "Owner-confirmed quarterly rent: November 2025, December 2025 "
                    "and January 2026 at KSh 20,000 each. One KSh 60,000 receipt "
                    "is allocated over three months; the bank receipt is NOT duplicated."
                )
                parts = [
                    {"rent_period": "2025-11-01", "amount_ksh": "20000.00"},
                    {"rent_period": "2025-12-01", "amount_ksh": "20000.00"},
                    {"rent_period": "2026-01-01", "amount_ksh": "20000.00"},
                ]
                st.dataframe([
                    {"Rent month": p["rent_period"], "Amount (KSh)": p["amount_ksh"]}
                    for p in parts
                ], hide_index=True, width="stretch")
                entered_date = date(2025, 11, 1)
            else:
                prior_parts = current.get("allocations") if current else None
                default_period = date.fromisoformat(
                    (prior_parts[0]["rent_period"] if prior_parts else current["rent_period"])
                    if current else "2025-11-01"
                )
                entered_date = st.date_input(
                    "Rent month being settled (first day of month)",
                    value=default_period,
                    key=f"v1i_period_{cheque}_{credit_id}",
                )
                parts = [
                    {"rent_period": entered_date.isoformat(),
                     "amount_ksh": str(source["amount_ksh"])}
                ]
            st.number_input(
                "Full cleared credit to allocate (KSh)",
                value=float(source["amount_ksh"]), disabled=True,
                key=f"v1i_amount_{cheque}_{credit_id}",
            )
            checked_period = st.checkbox(
                ("I checked all three quarterly rent months against lease/invoice evidence"
                 if is_quarterly else
                 "I checked the applicable rent month against lease/invoice evidence"),
                key=f"v1i_period_confirm_{cheque}_{credit_id}",
            )
            checked_amount = st.checkbox(
                "I checked that this exact cleared bank credit covers this allocation",
                key=f"v1i_amount_confirm_{cheque}_{credit_id}",
            )
            reviewer = st.text_input("Reviewer", key=f"v1i_reviewer_{cheque}_{credit_id}")
            explanation = st.text_area(
                "Rent period and invoice/lease evidence (required, 15+ characters)",
                key=f"v1i_note_{cheque}_{credit_id}",
            )
            correction_reason = ""
            if amend:
                correction_reason = st.text_area(
                    "Why this allocation must be corrected (20+ characters)",
                    key=f"v1i_reason_{cheque}_{credit_id}",
                )
            confirmed = st.checkbox(
                "I confirm this allocation review; it must not post rent automatically",
                key=f"v1i_final_{cheque}_{credit_id}",
            )
            valid = (
                entered_date.day == 1 and checked_period and checked_amount
                and confirmed and len(reviewer.strip()) >= 3
                and len(explanation.strip()) >= 15
                and (not amend or len(correction_reason.strip()) >= 20)
                and (not current or (current.get("allocations") or [
                    {"rent_period": current["rent_period"], "amount_ksh": current["amount_ksh"]}
                ]) != parts)
            )
            if st.button(
                "Save audited allocation decision (NO rent posting)",
                disabled=not valid,
                key=f"v1i_save_{cheque}_{credit_id}",
            ):
                try:
                    record_allocation(
                        allocation_path, clearance_path,
                        successful_credit_row_id=credit_id,
                        tenancy_id=tenancy_id,
                        rent_period=entered_date.isoformat(),
                        amount_ksh=source["amount_ksh"],
                        reviewer=reviewer, explanation=explanation,
                        verified_period=checked_period,
                        verified_amount=checked_amount,
                        confirmed=confirmed, amend=amend,
                        correction_reason=correction_reason,
                        allocations=parts,
                    )
                    st.rerun()
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    st.error(f"Allocation NOT saved: {exc}")
    st.info(
        "Stage 1I records allocation decisions locally only. Separate guarded, "
        "idempotent rent-ledger posting must be developed and verified before "
        "any tenant balance changes."
    )
