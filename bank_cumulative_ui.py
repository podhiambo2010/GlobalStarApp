"""Cumulative KCB workbook update: match, preview, stage only. Never posts to accounting."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import hashlib
import re
import pandas as pd
import streamlit as st
from import_review_ui import _client, ORG

FIELDS = ("Transaction Date", "Value Date", "Transaction Details",
          "Money Out", "Money In", "Ledger Balance", "Bank Reference Number")
MAX_BYTES = 15 * 1024 * 1024


def _money(value):
    if value is None or pd.isna(value):
        return Decimal("0.00")
    raw = str(value).strip().replace(",", "").replace("KES", "").replace(" ", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    if not raw:
        return Decimal("0.00")
    try:
        result = Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Unparseable bank amount") from exc
    if not result.is_finite():
        raise ValueError("Non-finite bank amount")
    return result


def _date(value, mandatory=False):
    if value is None or pd.isna(value) or str(value).strip() == "":
        if mandatory:
            raise ValueError("A transaction date is missing")
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.date().isoformat() if isinstance(value, (datetime, pd.Timestamp)) else value.isoformat()
    raw = str(value).strip()
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", raw):
        return datetime.strptime(raw, "%d.%m.%Y").date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw).isoformat()
    raise ValueError("Unsupported transaction date: " + raw[:25])


def _fingerprint(item):
    canonical = "|".join([
        item["transaction_date"],
        item["reference_number"].strip().lower(),
        item["transaction_details"].strip().lower(),
        f'{Decimal(item["money_in"]):.2f}',
        f'{Decimal(item["money_out"]):.2f}',
    ])
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def parse_bank_workbook(blob):
    if len(blob) > MAX_BYTES or not blob.startswith(b"PK"):
        raise ValueError("Please upload a valid .xlsx file of 15 MB or less.")
    excel = pd.ExcelFile(BytesIO(blob))
    compatible = []
    for name in excel.sheet_names:
        for header in (14, 0):
            columns = pd.read_excel(excel, sheet_name=name, header=header, nrows=0).columns
            if set(FIELDS).issubset(set(columns)):
                compatible.append((name, header))
                break
    if len(compatible) != 1:
        raise ValueError("Expected exactly one bank statement sheet with the standard seven KCB headings.")
    sheet, header = compatible[0]
    df = pd.read_excel(excel, sheet_name=sheet, header=header)
    df = df[list(FIELDS)]
    rows = []
    nonmovements = 0
    for line, (_, rec) in enumerate(df.iterrows(), header + 2):
        if pd.isna(rec["Transaction Date"]) or str(rec["Transaction Date"]).strip() == "":
            continue
        if str(rec["Transaction Date"]).strip() == "Transaction Date":
            continue
        try:
            posted_date = _date(rec["Transaction Date"], True)
            value_date = _date(rec["Value Date"])
            incoming = _money(rec["Money In"])
            outgoing_source = _money(rec["Money Out"])
            if incoming < 0:
                raise ValueError("Money IN must not be negative")
            outgoing = -abs(outgoing_source)
            if incoming > 0 and outgoing != 0:
                raise ValueError("Both Money IN and Money OUT are populated")
            details = "" if pd.isna(rec["Transaction Details"]) else str(rec["Transaction Details"]).strip()
            reference = "" if pd.isna(rec["Bank Reference Number"]) else str(rec["Bank Reference Number"]).strip()
            if incoming == 0 and outgoing == 0:
                if "balance" not in details.lower():
                    raise ValueError("Unexplained zero-amount movement")
                nonmovements += 1
                continue
            if len(reference) > 500 or len(details) > 2000:
                raise ValueError("Reference or description exceeds limits")
            rows.append({
                "transaction_date": posted_date,
                "value_date": value_date,
                "reference_number": reference,
                "transaction_details": details,
                "money_in": str(incoming),
                "money_out": str(outgoing),
                "excel_row": line,
            })
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f"Excel row {line}: {exc}") from exc
    if not rows or len(rows) > 5000:
        raise ValueError("There must be 1–5000 bank movements.")
    fingerprints = [_fingerprint(r) for r in rows]
    if len(set(fingerprints)) < len(fingerprints):
        raise ValueError(
            "Exact repeated statement rows detected. They may be legitimate, but need "
            "manual review before staging; bank reference alone does not establish duplication."
        )
    return rows, sheet, nonmovements


def _fetch_all(sb, table, fields, org):
    all_rows = []
    start = 0
    while True:
        page = sb.table(table).select(fields).eq("organization_id", org).range(start, start + 999).execute().data or []
        all_rows.extend(page)
        if len(page) < 1000:
            return all_rows
        start += 1000
        if start > 100000:
            raise ValueError("Too many bank history rows for a safe comparison")


def show_cumulative_bank_updates():
    st.title("04 · Cumulative Bank Updates")
    st.info("An overlapping annual statement extends one historical bank record. "
            "Existing rows are retained, new movements are staged for review, and "
            "nothing is posted to accounting or tenant balances.")
    sb = _client()
    if sb is None:
        return
    if not sb.auth.get_session():
        st.warning("Sign in on 'Review and Approve Differences' first, then return here.")
        return
    user = sb.auth.get_user().user
    try:
        roles = sb.table("organization_members").select("role").eq("organization_id", ORG).eq("user_id", user.id).execute().data or []
        role = roles[0]["role"] if roles else "none"
        existing = _fetch_all(sb, "bank_cumulative_movements",
                              "identity_hash,transaction_date,money_in,money_out,review_state", ORG)
        batches = _fetch_all(sb, "bank_upload_batches",
                             "id,filename,file_sha256,uploaded_at,source_rows,new_rows,matched_rows", ORG)
    except Exception as exc:
        st.error("Cannot inspect cumulative bank history: " + str(exc))
        return
    admin = role in ("owner", "admin")
    st.caption(f"Authenticated: {user.email} · Role: {role}")
    baseline = [r for r in existing if r["review_state"] == "legacy_baseline"]
    pending = [r for r in existing if r["review_state"] == "pending"]
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Retained historical rows", len(baseline))
    c2.metric("New pending rows", len(pending))
    c3.metric("Unique movements", len(existing))
    c4.metric("Registered uploads", len(batches))
    if existing:
        st.caption("Cumulative coverage: " +
                   min(r["transaction_date"] for r in existing) + " → " +
                   max(r["transaction_date"] for r in existing))
    st.subheader("Compare new annual statement")
    upload = st.file_uploader("Bank statement (.xlsx)", type=["xlsx"], key="rolling_bank_excel")
    if upload is None:
        st.caption("Select your latest KCB workbook. The initial comparison makes no database changes.")
        return
    blob = upload.getvalue()
    file_sha = hashlib.sha256(blob).hexdigest()
    if any(b["file_sha256"] == file_sha for b in batches):
        st.warning("This exact workbook was already staged. The file will not be imported twice.")
        return
    try:
        rows, sheet, skipped = parse_bank_workbook(blob)
    except Exception as exc:
        st.error(f"Workbook not accepted: {exc}")
        return
    known = {r["identity_hash"] for r in existing}
    matches = [r for r in rows if _fingerprint(r) in known]
    new = [r for r in rows if _fingerprint(r) not in known]
    a,b,c = st.columns(3)
    a.metric("Source movements", len(rows))
    b.metric("Already in cumulative history", len(matches))
    c.metric("New for controlled review", len(new))
    st.caption(f"Sheet: {sheet} · Excluded statement balance rows: {skipped} · "
               f"SHA-256: {file_sha[:12]}…")
    st.write("Statement coverage:", min(r["transaction_date"] for r in rows),
             "through", max(r["transaction_date"] for r in rows))
    if new:
        st.dataframe(pd.DataFrame(new[:100])[["excel_row", "transaction_date", "reference_number",
                                             "transaction_details", "money_in", "money_out"]],
                     hide_index=True, use_container_width=True)
        if len(new) > 100:
            st.caption("Showing first 100 new candidates; all validated rows will be staged.")
    else:
        st.success("Every bank movement is already retained. No new records are needed.")
    if not admin:
        st.warning("Only an organization admin/owner can stage new bank movements.")
        return
    st.warning("Staging stores only unique bank movements and a compact upload register. "
               "It does not approve entries, allocate rent, or change financial statements.")
    confirmed = st.checkbox("I confirm this is the correct bank statement, and understand "
                            "that staging does not post accounting entries.")
    if st.button("Stage unique movements for review", disabled=not confirmed,
                 type="primary", key="stage_rolling_bank"):
        try:
            cleaned = [{k: v for k, v in row.items() if k != "excel_row"} for row in rows]
            result = sb.rpc("stage_rolling_bank_statement", {
                "p_organization_id": ORG,
                "p_filename": upload.name,
                "p_file_sha256": file_sha,
                "p_rows": cleaned,
            }).execute().data
            st.success(f"Batch recorded: {result['new_rows']} new movements staged, "
                       f"{result['matched_rows']} matched historical entries. "
                       "Financial postings: 0.")
            st.json(result, expanded=False)
        except Exception as exc:
            st.error(f"Staging was not completed: {exc}")
