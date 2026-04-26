#!/usr/bin/env python3
"""
Monthly Revenue Report Generator
Reads GoBD payment and tax CSV files and produces a PDF summary.
"""

import csv
import sys
import os
import argparse
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT


def parse_decimal(value: str) -> Decimal:
    """Parse German-locale decimal string (comma as separator)."""
    return Decimal(value.strip().replace(",", "."))


def read_payments(filepath: str) -> list[dict]:
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = []
        for row in reader:
            # Strip quotes from keys/values
            clean = {k.strip('"'): v.strip('"') for k, v in row.items()}
            rows.append(clean)
    return rows


def read_taxes(filepath: str) -> list[dict]:
    return read_payments(filepath)  # same structure


def fmt(value: Decimal) -> str:
    """Format decimal as German locale currency string."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def build_report(payments_file: str, taxes_file: str, output_file: str):
    payments = read_payments(payments_file)
    taxes = read_taxes(taxes_file)

    # --- Aggregate payments ---
    total_revenue = Decimal("0")
    cash_revenue = Decimal("0")
    card_revenue = Decimal("0")
    num_sales = len(payments)

    for p in payments:
        amount = parse_decimal(p["Total Payments"])
        method = p["Payment Method"].upper()
        total_revenue += amount
        if method == "CASH":
            cash_revenue += amount
        elif method == "CARD":
            card_revenue += amount

    # Build sale_id -> payment method lookup
    sale_method = {p["Sale ID"]: p["Payment Method"].upper() for p in payments}

    # --- Aggregate taxes per payment method and rate ---
    def empty_tax():
        return {"sales_incl": Decimal("0"), "sales_excl": Decimal("0"), "tax_amount": Decimal("0")}

    tax_totals: dict[str, dict[str, dict]] = {
        "CASH": defaultdict(empty_tax),
        "CARD": defaultdict(empty_tax),
    }

    for t in taxes:
        rate = t["Tax Rate"]
        method = sale_method.get(t["Sale ID"], "")
        if method in tax_totals:
            tax_totals[method][rate]["sales_incl"] += parse_decimal(t["Total Sales Incl Tax"])
            tax_totals[method][rate]["sales_excl"] += parse_decimal(t["Total Sales Excl Tax"])
            tax_totals[method][rate]["tax_amount"] += parse_decimal(t["Total Tax Amount"])

    # --- Determine period and report month from data ---
    dates = [p["Fiscal Date"][:10] for p in payments if p.get("Fiscal Date")]
    period_start = min(dates) if dates else ""
    period_end = max(dates) if dates else ""

    # Derive report month (YYYY-MM) from the majority of dates
    report_month = period_start[:7] if period_start else ""  # e.g. "2026-03"
    report_month_label = ""
    if report_month:
        dt = datetime.strptime(report_month, "%Y-%m")
        # German month names
        month_names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        report_month_label = f"{month_names[dt.month - 1]} {dt.year}"

    merchant = payments[0]["Merchant Name"] if payments else "Unknown"

    # --- Build PDF ---
    doc = SimpleDocTemplate(
        output_file,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, spaceAfter=6)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=11,
                                    textColor=colors.grey, spaceAfter=20, alignment=TA_CENTER)
    section_style = ParagraphStyle("section", parent=styles["Heading2"], fontSize=13,
                                   spaceBefore=16, spaceAfter=8)

    story = []

    # Title
    story.append(Paragraph(f"Monatsbericht {report_month_label} – {merchant}", title_style))
    story.append(Paragraph(f"Zeitraum: {period_start} bis {period_end}", subtitle_style))

    # --- Revenue summary table ---
    story.append(Paragraph("Umsatzübersicht", section_style))

    summary_data = [
        ["", "Betrag"],
        ["Gesamtumsatz", fmt(total_revenue)],
        ["davon Barzahlung", fmt(cash_revenue)],
        ["davon Kartenzahlung", fmt(card_revenue)],
        ["Anzahl Transaktionen", str(num_sales)],
    ]

    summary_table = Table(summary_data, colWidths=[10 * cm, 5 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#ecf0f1"), colors.white]),
        ("FONTNAME", (0, 1), (0, 1), "Helvetica-Bold"),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#2c3e50")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)

    # --- Tax breakdown tables per payment method ---
    story.append(Paragraph("Steueraufschlüsselung", section_style))

    col_widths = [3.5 * cm, 4.5 * cm, 4.5 * cm, 4.5 * cm]
    tax_header = ["Steuersatz", "Brutto (inkl. MwSt.)", "Netto (exkl. MwSt.)", "Steuerbetrag"]

    subsection_style = ParagraphStyle("subsection", parent=styles["Normal"], fontSize=11,
                                      fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=4)

    for method, label in [("CASH", "Barzahlung"), ("CARD", "Kartenzahlung")]:
        story.append(Paragraph(label, subsection_style))

        rates = tax_totals[method]
        sorted_rates = sorted(rates.keys(), key=lambda r: int(r.replace("%", "")))

        tax_rows = [tax_header]
        total_incl = Decimal("0")
        total_excl = Decimal("0")
        total_tax = Decimal("0")

        for rate in sorted_rates:
            d = rates[rate]
            tax_rows.append([rate, fmt(d["sales_incl"]), fmt(d["sales_excl"]), fmt(d["tax_amount"])])
            total_incl += d["sales_incl"]
            total_excl += d["sales_excl"]
            total_tax += d["tax_amount"]

        tax_rows.append(["Gesamt", fmt(total_incl), fmt(total_excl), fmt(total_tax)])

        tax_table = Table(tax_rows, colWidths=col_widths)
        tax_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.HexColor("#ecf0f1"), colors.white]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#d5e8d4")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#2c3e50")),
            ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#2c3e50")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(tax_table)

    # Footer note
    story.append(Spacer(1, 1 * cm))
    note_style = ParagraphStyle("note", parent=styles["Normal"], fontSize=8,
                                textColor=colors.grey)
    story.append(Paragraph(
        f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')} | "
        f"Quelldateien: {os.path.basename(payments_file)}, {os.path.basename(taxes_file)}",
        note_style,
    ))

    doc.build(story)
    print(f"Report saved to: {output_file}")
    return report_month


def main():
    parser = argparse.ArgumentParser(
        description="Generate a monthly revenue PDF report from GoBD CSV exports."
    )
    parser.add_argument("payments_csv", help="Path to the payments CSV file")
    parser.add_argument("taxes_csv", help="Path to the taxes CSV file")
    parser.add_argument(
        "-o", "--output",
        default="monthly_report.pdf",
        help="Output PDF filename (default: monthly_report.pdf)",
    )
    args = parser.parse_args()

    for f in (args.payments_csv, args.taxes_csv):
        if not os.path.isfile(f):
            print(f"Error: file not found: {f}", file=sys.stderr)
            sys.exit(1)

    # Auto-generate sortable filename if not specified
    output = args.output
    if output == "monthly_report.pdf":
        # Peek at the data to get the month before building
        payments = read_payments(args.payments_csv)
        dates = [p["Fiscal Date"][:10] for p in payments if p.get("Fiscal Date")]
        if dates:
            report_month = min(dates)[:7]  # YYYY-MM
            output = f"tax_report_{report_month}.pdf"

    build_report(args.payments_csv, args.taxes_csv, output)


if __name__ == "__main__":
    main()
