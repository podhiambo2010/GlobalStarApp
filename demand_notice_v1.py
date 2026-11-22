"""Excel-only, local draft demand notices. No sending or network/database I/O."""
from datetime import date
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether


def render_draft_demand_notice(
    *, tenant_name: str, unit: str, outstanding: float, as_of: date,
    response_by: date, account_period: str, additional_notes: str = ""
) -> bytes:
    """Return a PDF draft; no external action. Caller must verify all sums."""
    if not tenant_name.strip() or not unit.strip():
        raise ValueError("Tenant and unit are required")
    if outstanding <= 0:
        raise ValueError("A demand notice requires a positive verified arrears figure")
    if response_by < as_of:
        raise ValueError("Response date must not precede the draft date")
    if len(additional_notes) > 1500:
        raise ValueError("Additional notes are too long")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="NoticeBodyGS", parent=styles["BodyText"], fontSize=10.5,
        leading=16, spaceAfter=10, alignment=TA_LEFT
    ))
    styles.add(ParagraphStyle(
        name="NoticeHeadingGS", parent=styles["Heading2"],
        fontSize=14, leading=18, textColor=colors.HexColor("#213247"), spaceAfter=16
    ))
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=22*mm, leftMargin=22*mm,
        topMargin=20*mm, bottomMargin=20*mm
    )
    esc = lambda v: escape(str(v), quote=True).replace("\n", "<br/>")
    body = [
        Paragraph("GLOBAL STAR INVESTMENTS LIMITED", styles["NoticeHeadingGS"]),
        Paragraph("<b>DRAFT — PAYMENT DEMAND FOR REVIEW (NOT SENT)</b>", styles["NoticeHeadingGS"]),
        Paragraph(f"<b>Date:</b> {as_of:%d %B %Y}", styles["NoticeBodyGS"]),
        Paragraph(f"<b>To:</b> {esc(tenant_name)}", styles["NoticeBodyGS"]),
        Paragraph(f"<b>Premises:</b> Unit {esc(unit)}, Tintin La Plaza, Siaya", styles["NoticeBodyGS"]),
        Spacer(1, 8),
        Paragraph("<b>RE: OUTSTANDING COMMERCIAL RENT ACCOUNT</b>", styles["NoticeBodyGS"]),
        Paragraph(f"According to the uploaded tenant and bank records for {esc(account_period)}, "
                  f"the account currently shows an outstanding balance of "
                  f"<b>KSh {outstanding:,.2f}</b>. This amount must be reconciled "
                  f"against the tenant ledger and supporting payment records before this "
                  f"draft is issued.", styles["NoticeBodyGS"]),
        Paragraph(f"Please review the account and arrange settlement of any verified "
                  f"amount outstanding, or provide documentary evidence of payments "
                  f"or disputed charges, by <b>{response_by:%d %B %Y}</b>.", styles["NoticeBodyGS"]),
        Paragraph("Payment may be made through the company’s verified official channels. "
                  "Please confirm payment instructions independently before issuing.", styles["NoticeBodyGS"]),
    ]
    if additional_notes.strip():
        body.append(Paragraph("<b>Additional information:</b> " + esc(additional_notes), styles["NoticeBodyGS"]))
    body.extend([
        Spacer(1, 12),
        Paragraph("Yours faithfully,<br/>Management<br/>Global Star Investments Limited",
                  styles["NoticeBodyGS"]),
        Spacer(1, 25),
        Paragraph("<b>Internal review checklist:</b> verify lease and occupancy status; "
                  "confirm accounting period, opening credits, disputed payments, "
                  "rent, adjustments and all statutory/contractual notice requirements. "
                  "This PDF is a draft and does not constitute proof of service.",
                  styles["NoticeBodyGS"]),
    ])
    doc.build(body)
    return output.getvalue()
