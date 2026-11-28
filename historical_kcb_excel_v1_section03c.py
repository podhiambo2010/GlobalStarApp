"""Read an archived KCB Excel worksheet for Section 03C, without side effects.

Retain original transaction fields; normalize only columns necessary to reproduce
the existing bank_row_ids algorithm. Never update current statement or reviews.
"""
from __future__ import annotations

from io import BytesIO
import pandas as pd
from bank_review_v1 import bank_row_ids

REQUIRED = ("Transaction Date", "Value Date", "Transaction Details",
            "Money In Num", "Money Out Num", "Ref_Clean")


def load_historical_kcb_xlsx(upload, *, max_bytes=20_000_000):
    """Return normalized in-memory frame, source sheet and row count.

    Supports an original KCB workbook with preamble/header at arbitrary row.
    Rejects ambiguous sheets, blank transactions and invalid financial values.
    """
    data = upload if isinstance(upload, bytes) else upload.read()
    if not isinstance(data, bytes) or not data or len(data) > max_bytes:
        raise ValueError("Historical workbook is empty or exceeds the 20 MB safety limit")
    with pd.ExcelFile(BytesIO(data), engine="openpyxl") as workbook:
        matches = []
        for sheet in workbook.sheet_names:
            raw = pd.read_excel(workbook, sheet_name=sheet, header=None, dtype=object)
            header_idx = None
            for i in range(min(100, len(raw))):
                names = {str(v).strip().lower() for v in raw.iloc[i].values}
                if ("transaction date" in names and
                        ("bank reference number" in names or "ref_clean" in names) and
                        ("transaction details" in names or "description" in names)):
                    header_idx = i
                    break
            if header_idx is None:
                continue
            cols = [str(c).strip() for c in raw.iloc[header_idx].values]
            frame = raw.iloc[header_idx + 1:].copy().reset_index(drop=True)
            frame.columns = cols
            frame = frame.dropna(how="all").copy()
            if frame.empty:
                continue
            matches.append((sheet, frame))
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one populated KCB transaction worksheet; "
            "check the original workbook or select a single-statement export"
        )
    sheet, frame = matches[0]
    normalized_names = {str(c).lower(): c for c in frame.columns}

    def column(*choices):
        for choice in choices:
            found = normalized_names.get(choice.lower())
            if found is not None:
                return found
        raise ValueError("Historical KCB workbook missing: " + "/".join(choices))

    date_col = column("Transaction Date")
    value_col = column("Value Date")
    details_col = column("Transaction Details", "Description")
    ref_col = column("Bank Reference Number", "Ref_Clean")
    money_in = column("Money In", "Credit", "Money In Num")
    money_out = column("Money Out", "Debit", "Money Out Num")
    result = pd.DataFrame()
    result["Transaction Date"] = frame[date_col]
    result["Value Date"] = frame[value_col]
    result["Transaction Details"] = frame[details_col].astype(str)
    result["Ref_Clean"] = frame[ref_col].astype(str).str.strip()
    for source, target in ((money_in, "Money In Num"), (money_out, "Money Out Num")):
        original = frame[source].fillna(0).astype(str).str.replace(",", "", regex=False).str.strip()
        parsed = pd.to_numeric(original, errors="coerce")
        if parsed.isna().any():
            raise ValueError("Non-numeric bank amount found in archived worksheet")
        result[target] = parsed
    if result["Transaction Date"].isna().any() or result["Value Date"].isna().any():
        raise ValueError("Incomplete transaction date in historical KCB worksheet")
    if result["Transaction Details"].isin(["nan", ""]).any():
        raise ValueError("Missing historical transaction narration")
    if result["Money In Num"].eq(0).mul(result["Money Out Num"].eq(0)).all():
        raise ValueError("No nonzero movements found in historical workbook")
    result["Bank_Row_ID"] = bank_row_ids(result)
    return result, sheet
