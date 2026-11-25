"""Conservative, evidence-bearing parser for GSIL commercial lease documents.

Extracted values are suggestions for review, never ledger writes.
"""
import re
from datetime import datetime

_AMOUNT = r"(?:KSh\.?|KES|KSHS?\.?)\s*([\d,]+(?:\.\d{1,2})?)"
_MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
           "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}


def parse_lease_fields(raw_text):
    """Return only defensible fields and page/wording evidence; never infer from filename."""
    text = raw_text or ""
    flattened = re.sub(r"\s+", " ", text)
    result = {"Tenant Name": None, "Shop #": None, "Monthly Rent (KSh)": None,
              "Security Deposit (KSh)": None, "Commencement": None,
              "Email": None, "KRA PIN": None, "Telephone No.": None,
              "Billing Cycle": None, "Quarterly Base Rent (KSh)": None,
              "Quarterly VAT (KSh)": None, "Quarterly Gross Rent (KSh)": None,
              "Lease End Date": None, "Field Evidence": {}, "Parser Warnings": []}

    def assign(field, match, value, source=None):
        if match is None or value is None:
            return
        if result[field] is not None and result[field] != value:
            result["Parser Warnings"].append("Conflicting evidence for " + field)
            result[field] = None
            result["Field Evidence"].pop(field, None)
            return
        result[field] = value
        result["Field Evidence"][field] = (source or match.group(0)).strip()[:240]

    def money(field, pattern, flags=re.I):
        m = re.search(pattern, flattened, flags)
        if m:
            try:
                assign(field, m, float(m.group(1).replace(",", "")))
            except ValueError:
                pass

    # Match tenant name from explicit party lines or tables, not arbitrary mentions.
    m = re.search(r"(?im)^\s*TENANT\s+NAME\s*[:|\-]?\s*([^\n|]{4,90})", text)
    if m:
        candidate = m.group(1).strip(" :-")
        if not re.search(r"^(?:information|details?)\b", candidate, re.I):
            assign("Tenant Name", m, candidate)
    if result["Tenant Name"] is None:
        m = re.search(r"\bAND\s+(HAND\s+IN\s+HAND\s+EASTERN\s*AFRICA)\s*[,.\n]", text, re.I)
        if m:
            assign("Tenant Name", m, re.sub(r"\s+", " ", m.group(1)).title())
    # Structured numeric unit references are safe; never take the land title plot number.
    m = re.search(r"\b(?:OFFICE|SHOP|UNIT)\s*(?:NO\.?|NUMBER|#)\s*[:.\-]?\s*(\d{1,3})\b", flattened, re.I)
    if m:
        assign("Shop #", m, int(m.group(1)))

    money("Monthly Rent (KSh)", r"(?:monthly\s+rent|rent\s+per\s+month|pay\s+(?:a\s+)?monthly\s+rent\s+of)\s*(?:of|:|=)?\s*" + _AMOUNT)
    if result["Monthly Rent (KSh)"] is None:
        money("Monthly Rent (KSh)", r"(?:rent|pay)\s+(?:of\s+)?"+_AMOUNT+r"\s*(?:per\s+month|monthly)")
    money("Quarterly Base Rent (KSh)", r"(?:gross\s+)?quarterly\s+base\s+rent\s*[:\-]?\s*"+_AMOUNT)
    money("Quarterly VAT (KSh)", r"value\s+added\s+tax\s*\([^)]*\)\s*[:\-]?\s*"+_AMOUNT)
    money("Quarterly Gross Rent (KSh)", r"total\s+gross\s+quarterly\s+obligation\s*[:\-]?\s*"+_AMOUNT)
    money("Security Deposit (KSh)", r"(?:refundable\s+)?security\s+deposit\s+(?:of\s+exactly\s+|of\s+|amount(?:ing)?\s+to\s+)?"+_AMOUNT)
    if result["Security Deposit (KSh)"] is None:
        money("Security Deposit (KSh)", r"(?:security\s+deposit|deposit\s+of).{0,105}?\b"+_AMOUNT)
    # Multipliers are obligations, not proof of payment; only calculate where an
    # explicitly extracted monthly rent and the multiplier occur in the same clause.
    if result["Security Deposit (KSh)"] is None and result["Monthly Rent (KSh)"] is not None:
        m = re.search(r"security\s+deposit\s+equivalent\s+to\s+(three|four|3|4)\s*(?:\(\d\)\s*)?months", flattened, re.I)
        if m:
            n = 3 if m.group(1).lower() in ("three", "3") else 4
            assign("Security Deposit (KSh)", m, n * result["Monthly Rent (KSh)"],
                   m.group(0) + " × explicitly stated monthly rent (calculated obligation)")

    def normal_date(day, month, year):
        try:
            mm = int(month) if month.isdigit() else _MONTHS[month.lower()]
            yyyy = int(year)
            if yyyy < 100: yyyy += 2000
            return datetime(yyyy, mm, int(day)).date().isoformat()
        except (ValueError, KeyError):
            return None

    date_patterns = [
      r"(?:shall\s+commence|commencing|commence(?:ment)?(?:\s+date)?|start\s+date)\s*(?:on|from|:|=)?\s*(\d{1,2})(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?([A-Za-z]+|\d{1,2})[\s/.\-]+(\d{2,4})",
      r"(?:shall\s+commence|commencing|commence(?:ment)?(?:\s+date)?|start\s+date)\s*(?:on|from|:|=)?\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})"
    ]
    for pattern in date_patterns:
        m = re.search(pattern, flattened, re.I)
        if m:
            date = normal_date(*m.groups())
            if date:
                assign("Commencement", m, date)
                break
    m = re.search(r"\bexpir(?:ing|es?)\s+on\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?([A-Za-z]+)\s+(\d{4})", flattened, re.I)
    if m:
        assign("Lease End Date", m, normal_date(*m.groups()))
    if re.search(r"\bquarterly\s+in\s+advance\b|\bper\s+quarter\b", flattened, re.I):
        result["Billing Cycle"] = "Quarterly"
    elif re.search(r"\bper\s+month\b|\bmonth-to-month\b|\bmonthly\s+rent\b", flattened, re.I):
        result["Billing Cycle"] = "Monthly"
    if result["Quarterly Base Rent (KSh)"] is not None and result["Monthly Rent (KSh)"] is None:
        result["Parser Warnings"].append("Quarterly rent retained as quarterly; no monthly figure assumed.")
    return result
