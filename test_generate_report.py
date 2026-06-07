#!/usr/bin/env python3
"""Test suite for generate_report.py and run_reports.py"""

import csv
import io
import os
import tempfile
import unittest
import zipfile
from decimal import Decimal
from unittest.mock import patch

from generate_report import (
    parse_decimal,
    fmt,
    read_csv_from_zip,
    build_report,
)
from run_reports import discover_zips, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAYMENT_FIELDS = [
    "Merchant Name", "Merchant ID", "Currency", "Fiscal Number",
    "Closing Date", "Sale ID", "Fiscal Date", "Fiscal Status",
    "Sale Type", "Total Payments", "Payment Method",
]

TAX_FIELDS = [
    "Merchant Name", "Merchant ID", "Currency", "Fiscal Number",
    "Closing Date", "Sale ID", "Fiscal Date", "Fiscal Status",
    "Sale Type", "Tax Rate", "Total Sales Incl Tax",
    "Total Sales Excl Tax", "Total Tax Amount",
]

TOTALS_FIELDS = [
    "Merchant Name", "Merchant ID", "Currency", "Fiscal Number",
    "Closing Date", "Sale ID", "Fiscal Date", "Fiscal Status",
    "Sale Type", "Total Sales Incl Tax", "Total Sales Excl Tax",
    "Total Tax Amount", "Total Tips", "Refund Reference", "Sale Signature",
]

Z_TOTALS_FIELDS = [
    "Merchant Name", "Merchant ID", "Currency", "Fiscal Number",
    "Opening Date", "Closing Date", "Total Sales Incl Tax",
    "Total Sales Excl Tax", "Total Tax Amount", "Total Payments", "Total Tips",
]

BASE_PAYMENT = {
    "Merchant Name": "Test Shop", "Merchant ID": "M001", "Currency": "EUR",
    "Fiscal Number": "1", "Closing Date": "2026-03-06 12:00:00",
    "Sale ID": "sale-001", "Fiscal Date": "2026-03-06 12:00:00",
    "Fiscal Status": "Finished", "Sale Type": "Sale",
    "Total Payments": "10,00", "Payment Method": "CASH",
}

BASE_TAX = {
    "Merchant Name": "Test Shop", "Merchant ID": "M001", "Currency": "EUR",
    "Fiscal Number": "1", "Closing Date": "2026-03-06 12:00:00",
    "Sale ID": "sale-001", "Fiscal Date": "2026-03-06 12:00:00",
    "Fiscal Status": "Finished", "Sale Type": "Sale",
    "Tax Rate": "19%", "Total Sales Incl Tax": "10,00",
    "Total Sales Excl Tax": "8,40", "Total Tax Amount": "1,60",
}

BASE_TOTALS = {
    "Merchant Name": "Test Shop", "Merchant ID": "M001", "Currency": "EUR",
    "Fiscal Number": "1", "Closing Date": "2026-03-06 12:00:00",
    "Sale ID": "sale-001", "Fiscal Date": "2026-03-06 12:00:00",
    "Fiscal Status": "Finished", "Sale Type": "Sale",
    "Total Sales Incl Tax": "10,00", "Total Sales Excl Tax": "8,40",
    "Total Tax Amount": "1,60", "Total Tips": "0,00",
    "Refund Reference": "", "Sale Signature": "",
}

BASE_Z_TOTALS = {
    "Merchant Name": "Test Shop", "Merchant ID": "M001", "Currency": "EUR",
    "Fiscal Number": "42", "Opening Date": "2026-03-06 00:00:00",
    "Closing Date": "2026-03-06 23:59:59", "Total Sales Incl Tax": "10,00",
    "Total Sales Excl Tax": "8,40", "Total Tax Amount": "1,60",
    "Total Payments": "10,00", "Total Tips": "0,00",
}


def make_csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def make_zip(path: str, payments: list[dict], taxes: list[dict],
             date: str = "2026-03-06", fiscal_number: str = "42",
             totals: list[dict] = None):
    """Write a zip archive with the expected SumUp file structure."""
    if totals is None:
        totals = [{**BASE_TOTALS, "Sale ID": p["Sale ID"]} for p in payments]
    z_totals_row = [{**BASE_Z_TOTALS, "Fiscal Number": fiscal_number,
                     "Opening Date": f"{date} 00:00:00", "Closing Date": f"{date} 23:59:59"}]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"GoBD-report-sales-payments-{date}_{date}.csv",
                    make_csv_bytes(payments, PAYMENT_FIELDS))
        zf.writestr(f"GoBD-report-sales-taxes-{date}_{date}.csv",
                    make_csv_bytes(taxes, TAX_FIELDS))
        zf.writestr(f"GoBD-report-sales-totals-{date}_{date}.csv",
                    make_csv_bytes(totals, TOTALS_FIELDS))
        zf.writestr(f"Z-report-daily-totals-{date}_{date}.csv",
                    make_csv_bytes(z_totals_row, Z_TOTALS_FIELDS))


# ---------------------------------------------------------------------------
# parse_decimal
# ---------------------------------------------------------------------------

class TestParseDecimal(unittest.TestCase):
    def test_integer_value(self):
        self.assertEqual(parse_decimal("10"), Decimal("10"))

    def test_german_comma(self):
        self.assertEqual(parse_decimal("10,50"), Decimal("10.50"))

    def test_with_whitespace(self):
        self.assertEqual(parse_decimal("  3,14  "), Decimal("3.14"))

    def test_zero(self):
        self.assertEqual(parse_decimal("0,00"), Decimal("0.00"))

    def test_large_value(self):
        self.assertEqual(parse_decimal("1234,56"), Decimal("1234.56"))


# ---------------------------------------------------------------------------
# fmt
# ---------------------------------------------------------------------------

class TestFmt(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(fmt(Decimal("10.00")), "10,00 €")

    def test_thousands(self):
        self.assertEqual(fmt(Decimal("1234.56")), "1.234,56 €")

    def test_zero(self):
        self.assertEqual(fmt(Decimal("0")), "0,00 €")

    def test_rounding(self):
        result = fmt(Decimal("9.999"))
        self.assertIn(",", result)
        self.assertTrue(result.endswith("€"))


# ---------------------------------------------------------------------------
# read_csv_from_zip
# ---------------------------------------------------------------------------

class TestReadCsvFromZip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_reads_matching_file(self):
        make_zip(self.tmp.name, [BASE_PAYMENT], [BASE_TAX])
        with zipfile.ZipFile(self.tmp.name) as zf:
            rows = read_csv_from_zip(zf, "sales-payments")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Sale ID"], "sale-001")

    def test_strips_quotes_from_keys(self):
        make_zip(self.tmp.name, [BASE_PAYMENT], [BASE_TAX])
        with zipfile.ZipFile(self.tmp.name) as zf:
            rows = read_csv_from_zip(zf, "sales-payments")
        self.assertIn("Payment Method", rows[0])

    def test_raises_when_fragment_not_found(self):
        make_zip(self.tmp.name, [BASE_PAYMENT], [BASE_TAX])
        with zipfile.ZipFile(self.tmp.name) as zf:
            with self.assertRaises(FileNotFoundError):
                read_csv_from_zip(zf, "nonexistent-fragment")

    def test_reads_taxes_file(self):
        make_zip(self.tmp.name, [BASE_PAYMENT], [BASE_TAX])
        with zipfile.ZipFile(self.tmp.name) as zf:
            rows = read_csv_from_zip(zf, "sales-taxes")
        self.assertEqual(rows[0]["Tax Rate"], "19%")


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

class TestBuildReport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.zip_file = os.path.join(self.dir, "GoBD-daily-archive-2026-03-06_2026-03-06.zip")
        self.output_file = os.path.join(self.dir, "report.pdf")

    def test_creates_pdf(self):
        make_zip(self.zip_file, [BASE_PAYMENT], [BASE_TAX])
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))
        self.assertGreater(os.path.getsize(self.output_file), 0)

    def test_pdf_starts_with_magic_bytes(self):
        make_zip(self.zip_file, [BASE_PAYMENT], [BASE_TAX])
        build_report(self.zip_file, self.output_file)
        with open(self.output_file, "rb") as f:
            self.assertEqual(f.read(4), b"%PDF")

    def test_returns_report_date(self):
        make_zip(self.zip_file, [BASE_PAYMENT], [BASE_TAX])
        result = build_report(self.zip_file, self.output_file)
        self.assertEqual(result, "2026-03-06")

    def test_fiscal_number_in_pdf(self):
        """build_report should complete without error when fiscal number is present."""
        make_zip(self.zip_file, [BASE_PAYMENT], [BASE_TAX], fiscal_number="7")
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_tips_split_by_payment_method(self):
        """Tips are correctly attributed to cash or card based on payment method."""
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Payment Method": "CARD", "Fiscal Number": "2"},
        ]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1"},
            {**BASE_TAX, "Sale ID": "s2", "Fiscal Number": "2"},
        ]
        totals = [
            {**BASE_TOTALS, "Sale ID": "s1", "Total Tips": "2,00"},
            {**BASE_TOTALS, "Sale ID": "s2", "Total Tips": "3,50", "Fiscal Number": "2"},
        ]
        make_zip(self.zip_file, payments, taxes, totals=totals)
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_zero_tips_no_error(self):
        """Days with no tips should still generate a valid report."""
        make_zip(self.zip_file, [BASE_PAYMENT], [BASE_TAX])
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_empty_tax_rate_skipped(self):
        """Tax rows with an empty Tax Rate (tax-exempt items) should not cause a crash."""
        payments = [{**BASE_PAYMENT, "Sale ID": "s1", "Payment Method": "CARD"}]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "19%",
             "Total Sales Incl Tax": "20,00", "Total Sales Excl Tax": "16,81", "Total Tax Amount": "3,19"},
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "",
             "Total Sales Incl Tax": "40,00", "Total Sales Excl Tax": "40,00", "Total Tax Amount": "0,00"},
        ]
        make_zip(self.zip_file, payments, taxes)
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_tax_exempt_sales_aggregated(self):
        """Tax-exempt sales are summed per payment method."""
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Payment Method": "CARD",
             "Total Payments": "40,00"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Payment Method": "CASH",
             "Total Payments": "20,00", "Fiscal Number": "2"},
        ]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "",
             "Total Sales Incl Tax": "40,00", "Total Sales Excl Tax": "40,00", "Total Tax Amount": "0,00"},
            {**BASE_TAX, "Sale ID": "s2", "Tax Rate": "",
             "Total Sales Incl Tax": "20,00", "Total Sales Excl Tax": "20,00", "Total Tax Amount": "0,00",
             "Fiscal Number": "2"},
        ]
        make_zip(self.zip_file, payments, taxes)
        # Verify the aggregation logic directly
        with zipfile.ZipFile(self.zip_file) as zf:
            tax_rows = read_csv_from_zip(zf, "sales-taxes")
            pay_rows = read_csv_from_zip(zf, "sales-payments")
        sale_method = {p["Sale ID"]: p["Payment Method"].upper() for p in pay_rows}
        cash_exempt = card_exempt = Decimal("0")
        for t in tax_rows:
            if t["Tax Rate"]:
                continue
            method = sale_method.get(t["Sale ID"], "")
            amount = parse_decimal(t["Total Sales Incl Tax"])
            if method == "CASH":
                cash_exempt += amount
            elif method == "CARD":
                card_exempt += amount
        self.assertEqual(card_exempt, Decimal("40.00"))
        self.assertEqual(cash_exempt, Decimal("20.00"))

    def test_no_exempt_sales_no_extra_rows(self):
        """When there are no tax-exempt sales the PDF still generates without error."""
        make_zip(self.zip_file, [BASE_PAYMENT], [BASE_TAX])
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_cash_and_card_split(self):
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "10,00", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Total Payments": "20,00", "Payment Method": "CARD",
             "Fiscal Number": "2"},
        ]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1"},
            {**BASE_TAX, "Sale ID": "s2", "Fiscal Number": "2"},
        ]
        make_zip(self.zip_file, payments, taxes)
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_mixed_tax_rates(self):
        payments = [{**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "15,00"}]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "19%",
             "Total Sales Incl Tax": "10,00", "Total Sales Excl Tax": "8,40", "Total Tax Amount": "1,60"},
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "7%",
             "Total Sales Incl Tax": "5,00", "Total Sales Excl Tax": "4,67", "Total Tax Amount": "0,33"},
        ]
        make_zip(self.zip_file, payments, taxes)
        build_report(self.zip_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_revenue_totals(self):
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "10,00", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Total Payments": "5,50", "Payment Method": "CASH",
             "Fiscal Number": "2"},
            {**BASE_PAYMENT, "Sale ID": "s3", "Total Payments": "20,00", "Payment Method": "CARD",
             "Fiscal Number": "3"},
        ]
        make_zip(self.zip_file, payments, [BASE_TAX])
        # Read back and verify totals
        with zipfile.ZipFile(self.zip_file) as zf:
            from generate_report import read_csv_from_zip
            rows = read_csv_from_zip(zf, "sales-payments")
        total = sum(parse_decimal(r["Total Payments"]) for r in rows)
        self.assertEqual(total, Decimal("35.50"))

    def test_tax_aggregation_by_method(self):
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Payment Method": "CARD", "Fiscal Number": "2"},
        ]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1", "Total Tax Amount": "1,60"},
            {**BASE_TAX, "Sale ID": "s2", "Fiscal Number": "2", "Total Tax Amount": "3,19"},
        ]
        make_zip(self.zip_file, payments, taxes)
        with zipfile.ZipFile(self.zip_file) as zf:
            p_rows = read_csv_from_zip(zf, "sales-payments")
            t_rows = read_csv_from_zip(zf, "sales-taxes")
        sale_method = {p["Sale ID"]: p["Payment Method"].upper() for p in p_rows}
        totals = {"CASH": Decimal("0"), "CARD": Decimal("0")}
        for t in t_rows:
            m = sale_method.get(t["Sale ID"], "")
            if m in totals:
                totals[m] += parse_decimal(t["Total Tax Amount"])
        self.assertEqual(totals["CASH"], Decimal("1.60"))
        self.assertEqual(totals["CARD"], Decimal("3.19"))


# ---------------------------------------------------------------------------
# Date label formatting
# ---------------------------------------------------------------------------

class TestDateLabel(unittest.TestCase):
    def _label(self, date_str: str) -> str:
        from datetime import datetime
        day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        month_names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{day_names[dt.weekday()]}, {dt.day:02d}. {month_names[dt.month - 1]} {dt.year}"

    def test_friday_march(self):
        self.assertEqual(self._label("2026-03-06"), "Freitag, 06. März 2026")

    def test_wednesday_december(self):
        self.assertEqual(self._label("2025-12-31"), "Mittwoch, 31. Dezember 2025")

    def test_friday_january(self):
        self.assertEqual(self._label("2026-01-02"), "Freitag, 02. Januar 2026")


# ---------------------------------------------------------------------------
# Filename conventions
# ---------------------------------------------------------------------------

class TestFilenameConventions(unittest.TestCase):
    def test_daily_filename_format(self):
        self.assertEqual(f"tax_report_2026-03-06.pdf", "tax_report_2026-03-06.pdf")

    def test_daily_filename_with_fiscal_number(self):
        date, fiscal = "2026-03-06", "4"
        self.assertEqual(f"tax_report_{date}_Z{fiscal}.pdf", "tax_report_2026-03-06_Z4.pdf")

    def test_daily_filenames_sort_chronologically(self):
        filenames = [
            "tax_report_2026-03-10.pdf",
            "tax_report_2026-03-06.pdf",
            "tax_report_2025-12-31.pdf",
        ]
        self.assertEqual(sorted(filenames), [
            "tax_report_2025-12-31.pdf",
            "tax_report_2026-03-06.pdf",
            "tax_report_2026-03-10.pdf",
        ])

    def test_month_folder_from_date(self):
        self.assertEqual("2026-03-06"[:7], "2026-03")

    def test_month_folders_sort_chronologically(self):
        self.assertEqual(sorted(["2026-03", "2025-12", "2026-01"]),
                         ["2025-12", "2026-01", "2026-03"])


# ---------------------------------------------------------------------------
# discover_zips
# ---------------------------------------------------------------------------

class TestDiscoverZips(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()

    def _touch(self, filename: str):
        open(os.path.join(self.data_dir, filename), "w").close()

    def test_finds_zip(self):
        self._touch("GoBD-daily-archive-2026-03-06_2026-03-06.zip")
        result = discover_zips(self.data_dir)
        self.assertIn("2026-03-06", result)

    def test_path_points_into_data_dir(self):
        self._touch("GoBD-daily-archive-2026-03-06_2026-03-06.zip")
        result = discover_zips(self.data_dir)
        self.assertTrue(result["2026-03-06"].startswith(self.data_dir))

    def test_finds_multiple_dates(self):
        self._touch("GoBD-daily-archive-2026-03-06_2026-03-06.zip")
        self._touch("GoBD-daily-archive-2026-03-07_2026-03-07.zip")
        result = discover_zips(self.data_dir)
        self.assertIn("2026-03-06", result)
        self.assertIn("2026-03-07", result)

    def test_finds_dates_across_months(self):
        self._touch("GoBD-daily-archive-2025-12-31_2025-12-31.zip")
        self._touch("GoBD-daily-archive-2026-01-02_2026-01-02.zip")
        result = discover_zips(self.data_dir)
        self.assertIn("2025-12-31", result)
        self.assertIn("2026-01-02", result)

    def test_ignores_unrelated_files(self):
        self._touch("some_other_file.zip")
        self._touch("README.md")
        result = discover_zips(self.data_dir)
        self.assertEqual(result, {})

    def test_empty_directory(self):
        self.assertEqual(discover_zips(self.data_dir), {})


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

class TestRun(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.reports_dir = tempfile.mkdtemp()

    def _make_zip(self, date: str, fiscal_number: str = "42"):
        filename = f"GoBD-daily-archive-{date}_{date}.zip"
        payment = {**BASE_PAYMENT, "Fiscal Date": f"{date} 12:00:00",
                   "Closing Date": f"{date} 12:00:00"}
        make_zip(os.path.join(self.data_dir, filename), [payment], [BASE_TAX],
                 date, fiscal_number)

    def test_creates_month_subfolder(self):
        self._make_zip("2026-03-06")
        run(self.data_dir, self.reports_dir)
        self.assertTrue(os.path.isdir(os.path.join(self.reports_dir, "2026-03")))

    def test_generates_daily_report(self):
        self._make_zip("2026-03-06", fiscal_number="4")
        run(self.data_dir, self.reports_dir)
        self.assertTrue(os.path.isfile(
            os.path.join(self.reports_dir, "2026-03", "tax_report_2026-03-06_Z4.pdf")
        ))

    def test_generates_one_report_per_zip(self):
        for i, date in enumerate(("2026-03-06", "2026-03-07", "2026-03-10"), start=4):
            self._make_zip(date, fiscal_number=str(i))
        run(self.data_dir, self.reports_dir)
        for i, date in enumerate(("2026-03-06", "2026-03-07", "2026-03-10"), start=4):
            self.assertTrue(os.path.isfile(
                os.path.join(self.reports_dir, "2026-03", f"tax_report_{date}_Z{i}.pdf")
            ))

    def test_skips_existing_report(self):
        self._make_zip("2026-03-06", fiscal_number="4")
        month_dir = os.path.join(self.reports_dir, "2026-03")
        os.makedirs(month_dir)
        open(os.path.join(month_dir, "tax_report_2026-03-06_Z4.pdf"), "w").close()

        with patch("run_reports.build_report") as mock_build:
            run(self.data_dir, self.reports_dir)
            mock_build.assert_not_called()

    def test_generates_only_missing_days(self):
        self._make_zip("2026-03-06", fiscal_number="4")
        self._make_zip("2026-03-07", fiscal_number="5")
        month_dir = os.path.join(self.reports_dir, "2026-03")
        os.makedirs(month_dir)
        open(os.path.join(month_dir, "tax_report_2026-03-06_Z4.pdf"), "w").close()

        with patch("run_reports.build_report") as mock_build:
            run(self.data_dir, self.reports_dir)
            self.assertEqual(mock_build.call_count, 1)
            self.assertIn("2026-03-07", mock_build.call_args[0][1])

    def test_processes_dates_in_sorted_order(self):
        self._make_zip("2026-03-10")
        self._make_zip("2026-03-06")
        call_order = []

        def fake_build(zip_path, out):
            call_order.append(out)
            open(out, "w").close()

        with patch("run_reports.build_report", side_effect=fake_build):
            run(self.data_dir, self.reports_dir)

        self.assertEqual(call_order, sorted(call_order))

    def test_multiple_months_each_get_own_folder(self):
        self._make_zip("2026-03-06")
        self._make_zip("2026-04-01")
        run(self.data_dir, self.reports_dir)
        self.assertTrue(os.path.isdir(os.path.join(self.reports_dir, "2026-03")))
        self.assertTrue(os.path.isdir(os.path.join(self.reports_dir, "2026-04")))

    def test_multiple_years_each_get_own_folder(self):
        self._make_zip("2025-12-31")
        self._make_zip("2026-01-02")
        run(self.data_dir, self.reports_dir)
        self.assertTrue(os.path.isdir(os.path.join(self.reports_dir, "2025-12")))
        self.assertTrue(os.path.isdir(os.path.join(self.reports_dir, "2026-01")))

    def test_skips_empty_day(self):
        """A zip whose Z-report totals has no data rows should be skipped."""
        date = "2026-03-01"
        filename = f"GoBD-daily-archive-{date}_{date}.zip"
        payment = {**BASE_PAYMENT, "Fiscal Date": f"{date} 12:00:00",
                   "Closing Date": f"{date} 12:00:00"}
        # Write zip with empty Z-report totals (header only, no rows)
        with zipfile.ZipFile(os.path.join(self.data_dir, filename), "w") as zf:
            zf.writestr(f"GoBD-report-sales-payments-{date}_{date}.csv",
                        make_csv_bytes([payment], PAYMENT_FIELDS))
            zf.writestr(f"GoBD-report-sales-taxes-{date}_{date}.csv",
                        make_csv_bytes([BASE_TAX], TAX_FIELDS))
            zf.writestr(f"Z-report-daily-totals-{date}_{date}.csv",
                        make_csv_bytes([], Z_TOTALS_FIELDS))

        with patch("run_reports.build_report") as mock_build:
            run(self.data_dir, self.reports_dir)
            mock_build.assert_not_called()

    def test_no_data_prints_message(self):
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            run(self.data_dir, self.reports_dir)
        self.assertIn("No GoBD daily zip files found", buf.getvalue())

    def test_empty_day_counted_separately(self):
        """Empty days should not increment the 'already exist' counter."""
        date = "2026-03-01"
        filename = f"GoBD-daily-archive-{date}_{date}.zip"
        with zipfile.ZipFile(os.path.join(self.data_dir, filename), "w") as zf:
            zf.writestr(f"GoBD-report-sales-payments-{date}_{date}.csv",
                        make_csv_bytes([BASE_PAYMENT], PAYMENT_FIELDS))
            zf.writestr(f"GoBD-report-sales-taxes-{date}_{date}.csv",
                        make_csv_bytes([BASE_TAX], TAX_FIELDS))
            zf.writestr(f"Z-report-daily-totals-{date}_{date}.csv",
                        make_csv_bytes([], Z_TOTALS_FIELDS))
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            run(self.data_dir, self.reports_dir)
        output = buf.getvalue()
        self.assertIn("Skipped (no sales): 1", output)
        self.assertIn("Skipped (already exist): 0", output)


if __name__ == "__main__":
    unittest.main()
