#!/usr/bin/env python3
"""
Daily Revenue Report Generator
Reads a SumUp GoBD daily zip archive and produces a PDF tax report.
"""

import csv
import io
import sys
import os
import argparse
import zipfile
from decimal import Decimal
from collections import defaultdict
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# Payment methods that represent real money received today
CASH_CARD_METHODS = {"CASH", "CARD"}
# All known methods including voucher redemption
ALL_METHODS = {"CASH", "CARD", "GIFT_CARD"}


def parse_decimal(value: str) -> Decimal:
    """Parse German-locale decimal string (comma as separator)."""
    return Decimal(value.strip().replace(",", "."))


def fmt(value: Decimal) -> str:
    """Format decimal as German locale currency string."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def read_csv_from_zip(zf: zipfile.ZipFile, name_fragment: str) -> list[dict]:
    """Read the first zip entry whose name contains name_fragment as a CSV."""
    match = next((n for n in zf.namelist() if name_fragment in n), None)
    if match is None:
        raise FileNotFoundError(f"No file matching '{name_fragment}' found in zip.")
    content = zf.read(match).decode("utf-8")
    reader = csv.DictReader(io.StringIO(content), delimiter=";")
    return [{k.strip('"'): v.strip('"') for k, v in row.items()} for row in reader]


def build_report(zip_file: str, output_file: str):
    """
    Build a daily PDF report from a GoBD daily zip archive.
    Returns the report date string (YYYY-MM-DD).
    """
    with zipfile.ZipFile(zip_file) as zf:
        payments = read_csv_from_zip(zf, "sales-payments")
        taxes = read_csv_from_zip(zf, "sales-taxes")
        totals = read_csv_from_zip(zf, "sales-totals")
        z_totals = read_csv_from_zip(zf, "daily-totals")

    # --- Aggregate payments ---
    # Only CASH and CARD count as revenue today; GIFT_CARD is a redemption
    total_revenue = Decimal("0")
    cash_revenue = Decimal("0")
    card_revenue = Decimal("0")
    gift_card_redeemed = Decimal("0")
    num_sales = len({p["Sale ID"] for p in payments})  # unique sales

    for p in payments:
        amount = parse_decimal(p["Total Payments"])
        method = p["Payment Method"].upper()
        if method == "CASH":
            cash_revenue += amount
            total_revenue += amount
        elif method == "CARD":
            card_revenue += amount
            total_revenue += amount
        elif method == "GIFT_CARD":
            gift_card_redeemed += amount

    # Build sale_id -> {method: amount} for all payments (handles split payments)
    sale_payments: dict[str, dict[str, Decimal]] = {}
    for p in payments:
        sid = p["Sale ID"]
        method = p["Payment Method"].upper()
        amount = parse_decimal(p["Total Payments"])
        sale_payments.setdefault(sid, {})[method] = amount

    def payment_shares(sale_id: str) -> dict[str, Decimal]:
        """Return {method: fraction} for a sale, based on actual payment amounts."""
        parts = sale_payments.get(sale_id, {})
        total = sum(parts.values())
        if not total:
            return {}
        return {m: amt / total for m, amt in parts.items()}

    # --- Aggregate tips per payment method (proportional for split payments) ---
    cash_tips = Decimal("0")
    card_tips = Decimal("0")
    for t in totals:
        tip = parse_decimal(t.get("Total Tips", "0"))
        if tip == 0:
            continue
        for method, share in payment_shares(t["Sale ID"]).items():
            portion = (tip * share).quantize(Decimal("0.01"))
            if method == "CASH":
                cash_tips += portion
            elif method == "CARD":
                card_tips += portion
    total_tips = cash_tips + card_tips

    # --- Aggregate taxes per payment method and rate (proportional for split payments) ---
    def empty_tax():
        return {"sales_incl": Decimal("0"), "sales_excl": Decimal("0"), "tax_amount": Decimal("0")}

    tax_totals: dict[str, dict[str, dict]] = {
        "CASH": defaultdict(empty_tax),
        "CARD": defaultdict(empty_tax),
        "GIFT_CARD": defaultdict(empty_tax),
    }

    for t in taxes:
        rate = t["Tax Rate"]
        if not rate:  # skip tax-exempt rows (handled separately below)
            continue
        for method, share in payment_shares(t["Sale ID"]).items():
            if method not in tax_totals:
                continue
            tax_totals[method][rate]["sales_incl"] += (parse_decimal(t["Total Sales Incl Tax"]) * share).quantize(Decimal("0.01"))
            tax_totals[method][rate]["sales_excl"] += (parse_decimal(t["Total Sales Excl Tax"]) * share).quantize(Decimal("0.01"))
            tax_totals[method][rate]["tax_amount"] += (parse_decimal(t["Total Tax Amount"]) * share).quantize(Decimal("0.01"))

    # --- Aggregate tax-exempt sales (empty Tax Rate) per payment method ---
    cash_exempt = Decimal("0")
    card_exempt = Decimal("0")
    for t in taxes:
        if t["Tax Rate"]:
            continue
        for method, share in payment_shares(t["Sale ID"]).items():
            amount = (parse_decimal(t["Total Sales Incl Tax"]) * share).quantize(Decimal("0.01"))
            if method == "CASH":
                cash_exempt += amount
            elif method == "CARD":
                card_exempt += amount
    total_exempt = cash_exempt + card_exempt

    # --- Derive report date, fiscal number and label ---
    dates = [p["Fiscal Date"][:10] for p in payments if p.get("Fiscal Date")]
    report_date = min(dates) if dates else ""

    fiscal_number = z_totals[0].get("Fiscal Number", "") if z_totals else ""
    merchant = payments[0]["Merchant Name"] if payments else "Unknown"

    date_label = ""
    if report_date:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
        day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        month_names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        date_label = f"{day_names[dt.weekday()]}, {dt.day:02d}. {month_names[dt.month - 1]} {dt.year}"

    # --- Build PDF ---
    doc = SimpleDocTemplate(
        output_file,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=16, spaceAfter=4)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10,
                                    textColor=colors.grey, spaceAfter=6, alignment=TA_CENTER)
    section_style = ParagraphStyle("section", parent=styles["Heading2"], fontSize=11,
                                   spaceBefore=8, spaceAfter=4)
    subsection_style = ParagraphStyle("subsection", parent=styles["Normal"], fontSize=10,
                                      fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2)
    note_style = ParagraphStyle("note", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    FONT_SIZE = 10
    PAD = 4

    def tax_table_style():
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.HexColor("#ecf0f1"), colors.white]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#d5e8d4")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#2c3e50")),
            ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#2c3e50")),
            ("TOPPADDING", (0, 0), (-1, -1), PAD),
            ("BOTTOMPADDING", (0, 0), (-1, -1), PAD),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])

    story = []
    story.append(Paragraph(f"Tagesbericht – {merchant}", title_style))

    # Header row: date label left, date + fiscal number right
    fiscal_label = f"Z-Bericht Nr. {fiscal_number}" if fiscal_number else ""
    date_right = report_date.replace("-", ".") if report_date else ""
    header_right = f"{date_right}   {fiscal_label}".strip()
    header_table = Table(
        [[Paragraph(date_label, subtitle_style), Paragraph(header_right, subtitle_style)]],
        colWidths=[11 * cm, 6 * cm],
    )
    header_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)

    # --- Revenue summary ---
    story.append(Paragraph("Umsatzübersicht", section_style))
    summary_data = [
        ["", "Betrag"],
        ["Gesamtumsatz (Bar + Karte)", fmt(total_revenue)],
        ["davon Barzahlung", fmt(cash_revenue)],
        ["davon Kartenzahlung", fmt(card_revenue)],
        ["Anzahl Transaktionen", str(num_sales)],
        ["Trinkgeld gesamt", fmt(total_tips)],
        ["davon Barzahlung", fmt(cash_tips)],
        ["davon Kartenzahlung", fmt(card_tips)],
    ]
    if gift_card_redeemed > 0:
        summary_data.append(["Gutscheineinlösungen (kein neuer Umsatz)", fmt(gift_card_redeemed)])
    if total_exempt > 0:
        summary_data += [
            ["Steuerfreie Umsätze (z.B. Gutscheinverkauf)", fmt(total_exempt)],
            ["davon Barzahlung", fmt(cash_exempt)],
            ["davon Kartenzahlung", fmt(card_exempt)],
        ]

    summary_table = Table(summary_data, colWidths=[11 * cm, 4 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#ecf0f1"), colors.white]),
        ("FONTNAME", (0, 1), (0, 1), "Helvetica-Bold"),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#2c3e50")),
        # Highlight the gift card row in a distinct colour if present
        *([("BACKGROUND", (0, 8), (-1, 8), colors.HexColor("#fdebd0")),
           ("FONTNAME", (0, 8), (-1, 8), "Helvetica-Bold")]
          if gift_card_redeemed > 0 else []),
        ("TOPPADDING", (0, 0), (-1, -1), PAD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), PAD),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)

    # --- Tax breakdown per payment method ---
    story.append(Paragraph("Steueraufschlüsselung", section_style))
    col_widths = [3.0 * cm, 4.0 * cm, 4.0 * cm, 4.0 * cm]
    tax_header = ["Steuersatz", "Brutto (inkl. MwSt.)", "Netto (exkl. MwSt.)", "Steuerbetrag"]

    method_labels = [("CASH", "Barzahlung"), ("CARD", "Kartenzahlung"), ("GIFT_CARD", "Gutscheineinlösungen")]

    for method, label in method_labels:
        rates = tax_totals[method]
        if not rates:
            continue  # skip section entirely if no data for this method
        sorted_rates = sorted(rates.keys(), key=lambda r: int(r.replace("%", "")))

        story.append(Paragraph(label, subsection_style))
        tax_rows = [tax_header]
        total_incl = total_excl = total_tax = Decimal("0")

        for rate in sorted_rates:
            d = rates[rate]
            tax_rows.append([rate, fmt(d["sales_incl"]), fmt(d["sales_excl"]), fmt(d["tax_amount"])])
            total_incl += d["sales_incl"]
            total_excl += d["sales_excl"]
            total_tax += d["tax_amount"]

        tax_rows.append(["Gesamt", fmt(total_incl), fmt(total_excl), fmt(total_tax)])
        tax_table = Table(tax_rows, colWidths=col_widths)
        tax_table.setStyle(tax_table_style())
        story.append(tax_table)

    # Footer
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} | "
        f"Quelldatei: {os.path.basename(zip_file)}",
        note_style,
    ))

    doc.build(story)
    print(f"Report saved to: {output_file}")
    return report_date


def main():
    parser = argparse.ArgumentParser(
        description="Generate a daily revenue PDF report from a GoBD daily zip archive."
    )
    parser.add_argument("zip_file", help="Path to the GoBD daily zip archive")
    parser.add_argument("-o", "--output", default="",
                        help="Output PDF filename. Auto-generated if omitted.")
    args = parser.parse_args()

    if not os.path.isfile(args.zip_file):
        print(f"Error: file not found: {args.zip_file}", file=sys.stderr)
        sys.exit(1)

    output = args.output
    if not output:
        import re
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(args.zip_file))
        date = m.group(1) if m else "unknown"
        try:
            with zipfile.ZipFile(args.zip_file) as zf:
                z_totals = read_csv_from_zip(zf, "daily-totals")
                fiscal = z_totals[0].get("Fiscal Number", "") if z_totals else ""
        except Exception:
            fiscal = ""
        suffix = f"_Z{fiscal}" if fiscal else ""
        output = f"tax_report_{date}{suffix}.pdf"

    build_report(args.zip_file, output)


if __name__ == "__main__":
    main()
