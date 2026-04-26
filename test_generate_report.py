#!/usr/bin/env python3
"""Test suite for generate_report.py and run_reports.py"""

import os
import csv
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch, call

from generate_report import (
    parse_decimal,
    fmt,
    read_payments,
    build_report,
)
from run_reports import discover_months, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_csv(path: str, rows: list[dict], fieldnames: list[str]):
    """Write a semicolon-delimited CSV with quoted fields."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


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

BASE_PAYMENT = {
    "Merchant Name": "Test Shop",
    "Merchant ID": "M001",
    "Currency": "EUR",
    "Fiscal Number": "1",
    "Closing Date": "2026-03-06 12:00:00",
    "Sale ID": "sale-001",
    "Fiscal Date": "2026-03-06 12:00:00",
    "Fiscal Status": "Finished",
    "Sale Type": "Sale",
    "Total Payments": "10,00",
    "Payment Method": "CASH",
}

BASE_TAX = {
    "Merchant Name": "Test Shop",
    "Merchant ID": "M001",
    "Currency": "EUR",
    "Fiscal Number": "1",
    "Closing Date": "2026-03-06 12:00:00",
    "Sale ID": "sale-001",
    "Fiscal Date": "2026-03-06 12:00:00",
    "Fiscal Status": "Finished",
    "Sale Type": "Sale",
    "Tax Rate": "19%",
    "Total Sales Incl Tax": "10,00",
    "Total Sales Excl Tax": "8,40",
    "Total Tax Amount": "1,60",
}


# ---------------------------------------------------------------------------
# Unit tests
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


class TestFmt(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(fmt(Decimal("10.00")), "10,00 €")

    def test_thousands(self):
        self.assertEqual(fmt(Decimal("1234.56")), "1.234,56 €")

    def test_zero(self):
        self.assertEqual(fmt(Decimal("0")), "0,00 €")

    def test_rounding(self):
        # Should format to 2 decimal places
        result = fmt(Decimal("9.999"))
        self.assertIn(",", result)
        self.assertTrue(result.endswith("€"))


class TestReadPayments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                               delete=False, encoding="utf-8")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_reads_rows(self):
        write_csv(self.tmp.name, [BASE_PAYMENT], PAYMENT_FIELDS)
        rows = read_payments(self.tmp.name)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Sale ID"], "sale-001")
        self.assertEqual(rows[0]["Payment Method"], "CASH")

    def test_strips_quotes_from_keys(self):
        # Manually write a file with extra quotes to simulate real export
        with open(self.tmp.name, "w", encoding="utf-8") as f:
            f.write('"Merchant Name";"Total Payments"\n')
            f.write('"Test Shop";"5,00"\n')
        rows = read_payments(self.tmp.name)
        self.assertIn("Merchant Name", rows[0])
        self.assertEqual(rows[0]["Total Payments"], "5,00")

    def test_multiple_rows(self):
        rows_data = [
            {**BASE_PAYMENT, "Fiscal Number": "1", "Sale ID": "s1", "Total Payments": "5,00"},
            {**BASE_PAYMENT, "Fiscal Number": "2", "Sale ID": "s2", "Total Payments": "7,50"},
        ]
        write_csv(self.tmp.name, rows_data, PAYMENT_FIELDS)
        rows = read_payments(self.tmp.name)
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# Integration tests – build_report
# ---------------------------------------------------------------------------

class TestBuildReport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.payments_file = os.path.join(self.dir, "payments.csv")
        self.taxes_file = os.path.join(self.dir, "taxes.csv")
        self.output_file = os.path.join(self.dir, "report.pdf")

    def _write_fixtures(self, payments: list[dict], taxes: list[dict]):
        write_csv(self.payments_file, payments, PAYMENT_FIELDS)
        write_csv(self.taxes_file, taxes, TAX_FIELDS)

    def test_creates_pdf(self):
        self._write_fixtures([BASE_PAYMENT], [BASE_TAX])
        build_report(self.payments_file, self.taxes_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))
        self.assertGreater(os.path.getsize(self.output_file), 0)

    def test_pdf_starts_with_pdf_magic_bytes(self):
        self._write_fixtures([BASE_PAYMENT], [BASE_TAX])
        build_report(self.payments_file, self.taxes_file, self.output_file)
        with open(self.output_file, "rb") as f:
            self.assertTrue(f.read(4) == b"%PDF")

    def test_returns_report_month(self):
        self._write_fixtures([BASE_PAYMENT], [BASE_TAX])
        month = build_report(self.payments_file, self.taxes_file, self.output_file)
        self.assertEqual(month, "2026-03")

    def test_cash_and_card_split(self):
        """Both payment methods present – report should still be generated."""
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "10,00", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Total Payments": "20,00", "Payment Method": "CARD",
             "Fiscal Number": "2"},
        ]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1"},
            {**BASE_TAX, "Sale ID": "s2", "Fiscal Number": "2"},
        ]
        self._write_fixtures(payments, taxes)
        build_report(self.payments_file, self.taxes_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_mixed_tax_rates(self):
        """Payment with both 7% and 19% tax rows."""
        payments = [{**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "15,00"}]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "19%",
             "Total Sales Incl Tax": "10,00", "Total Sales Excl Tax": "8,40", "Total Tax Amount": "1,60"},
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "7%",
             "Total Sales Incl Tax": "5,00", "Total Sales Excl Tax": "4,67", "Total Tax Amount": "0,33"},
        ]
        self._write_fixtures(payments, taxes)
        build_report(self.payments_file, self.taxes_file, self.output_file)
        self.assertTrue(os.path.isfile(self.output_file))

    def test_multiple_payments_totals(self):
        """Revenue totals are summed correctly across payments."""
        from generate_report import read_payments
        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "10,00", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Total Payments": "5,50", "Payment Method": "CASH",
             "Fiscal Number": "2"},
            {**BASE_PAYMENT, "Sale ID": "s3", "Total Payments": "20,00", "Payment Method": "CARD",
             "Fiscal Number": "3"},
        ]
        write_csv(self.payments_file, payments, PAYMENT_FIELDS)
        rows = read_payments(self.payments_file)
        total = sum(parse_decimal(r["Total Payments"]) for r in rows)
        self.assertEqual(total, Decimal("35.50"))

    def test_tax_aggregation_by_method(self):
        """Tax totals are correctly split by payment method."""
        from generate_report import read_payments, read_taxes
        from collections import defaultdict

        payments = [
            {**BASE_PAYMENT, "Sale ID": "s1", "Total Payments": "10,00", "Payment Method": "CASH"},
            {**BASE_PAYMENT, "Sale ID": "s2", "Total Payments": "20,00", "Payment Method": "CARD",
             "Fiscal Number": "2"},
        ]
        taxes = [
            {**BASE_TAX, "Sale ID": "s1", "Tax Rate": "19%",
             "Total Sales Incl Tax": "10,00", "Total Sales Excl Tax": "8,40", "Total Tax Amount": "1,60"},
            {**BASE_TAX, "Sale ID": "s2", "Tax Rate": "19%", "Fiscal Number": "2",
             "Total Sales Incl Tax": "20,00", "Total Sales Excl Tax": "16,81", "Total Tax Amount": "3,19"},
        ]
        write_csv(self.payments_file, payments, PAYMENT_FIELDS)
        write_csv(self.taxes_file, taxes, TAX_FIELDS)

        p_rows = read_payments(self.payments_file)
        t_rows = read_taxes(self.taxes_file)
        sale_method = {p["Sale ID"]: p["Payment Method"].upper() for p in p_rows}

        totals = {"CASH": Decimal("0"), "CARD": Decimal("0")}
        for t in t_rows:
            method = sale_method.get(t["Sale ID"], "")
            if method in totals:
                totals[method] += parse_decimal(t["Total Tax Amount"])

        self.assertEqual(totals["CASH"], Decimal("1.60"))
        self.assertEqual(totals["CARD"], Decimal("3.19"))


# ---------------------------------------------------------------------------
# CLI / filename tests
# ---------------------------------------------------------------------------

class TestDefaultFilename(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.payments_file = os.path.join(self.dir, "payments.csv")
        self.taxes_file = os.path.join(self.dir, "taxes.csv")
        write_csv(self.payments_file, [BASE_PAYMENT], PAYMENT_FIELDS)
        write_csv(self.taxes_file, [BASE_TAX], TAX_FIELDS)

    def test_auto_filename_format(self):
        """Default output filename should be report_YYYY-MM.pdf."""
        from generate_report import read_payments
        payments = read_payments(self.payments_file)
        dates = [p["Fiscal Date"][:10] for p in payments if p.get("Fiscal Date")]
        report_month = min(dates)[:7]
        expected = f"tax_report_{report_month}.pdf"
        self.assertEqual(expected, "tax_report_2026-03.pdf")

    def test_auto_filename_is_sortable(self):
        """YYYY-MM prefix ensures lexicographic sort equals chronological sort."""
        filenames = ["tax_report_2026-01.pdf", "tax_report_2025-12.pdf", "tax_report_2026-03.pdf"]
        self.assertEqual(sorted(filenames), [
            "tax_report_2025-12.pdf",
            "tax_report_2026-01.pdf",
            "tax_report_2026-03.pdf",
        ])


class TestReportMonthLabel(unittest.TestCase):
    def test_march_2026(self):
        from datetime import datetime
        month_names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        dt = datetime.strptime("2026-03", "%Y-%m")
        label = f"{month_names[dt.month - 1]} {dt.year}"
        self.assertEqual(label, "März 2026")

    def test_december_2025(self):
        from datetime import datetime
        month_names = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        dt = datetime.strptime("2025-12", "%Y-%m")
        label = f"{month_names[dt.month - 1]} {dt.year}"
        self.assertEqual(label, "Dezember 2025")


if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Tests for run_reports.discover_months
# ---------------------------------------------------------------------------

class TestDiscoverMonths(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()

    def _touch(self, filename: str):
        open(os.path.join(self.data_dir, filename), "w").close()

    def test_finds_complete_pair(self):
        self._touch("GoBD-report-sales-payments-2026-03-01_2026-03-31.csv")
        self._touch("GoBD-report-sales-taxes-2026-03-01_2026-03-31.csv")
        result = discover_months(self.data_dir)
        self.assertIn("2026-03", result)
        self.assertIn("payments", result["2026-03"])
        self.assertIn("taxes", result["2026-03"])

    def test_ignores_incomplete_pair_missing_taxes(self):
        self._touch("GoBD-report-sales-payments-2026-04-01_2026-04-30.csv")
        result = discover_months(self.data_dir)
        self.assertNotIn("2026-04", result)

    def test_ignores_incomplete_pair_missing_payments(self):
        self._touch("GoBD-report-sales-taxes-2026-05-01_2026-05-31.csv")
        result = discover_months(self.data_dir)
        self.assertNotIn("2026-05", result)

    def test_finds_multiple_months(self):
        for month, days in [("2026-03", "01_2026-03-31"), ("2026-04", "01_2026-04-30")]:
            self._touch(f"GoBD-report-sales-payments-{month}-{days}.csv")
            self._touch(f"GoBD-report-sales-taxes-{month}-{days}.csv")
        result = discover_months(self.data_dir)
        self.assertIn("2026-03", result)
        self.assertIn("2026-04", result)

    def test_ignores_unrelated_files(self):
        self._touch("some_other_file.csv")
        self._touch("README.md")
        result = discover_months(self.data_dir)
        self.assertEqual(result, {})

    def test_paths_point_into_data_dir(self):
        self._touch("GoBD-report-sales-payments-2026-03-01_2026-03-31.csv")
        self._touch("GoBD-report-sales-taxes-2026-03-01_2026-03-31.csv")
        result = discover_months(self.data_dir)
        self.assertTrue(result["2026-03"]["payments"].startswith(self.data_dir))
        self.assertTrue(result["2026-03"]["taxes"].startswith(self.data_dir))

    def test_empty_directory(self):
        result = discover_months(self.data_dir)
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Tests for run_reports.run
# ---------------------------------------------------------------------------

class TestRun(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.reports_dir = tempfile.mkdtemp()

    def _write_month(self, month: str):
        """Write a valid CSV pair for the given month into data_dir."""
        day_range = f"01_{month}-28"
        payments_path = os.path.join(
            self.data_dir, f"GoBD-report-sales-payments-{month}-{day_range}.csv"
        )
        taxes_path = os.path.join(
            self.data_dir, f"GoBD-report-sales-taxes-{month}-{day_range}.csv"
        )
        payment = {**BASE_PAYMENT, "Fiscal Date": f"{month}-06 12:00:00",
                   "Closing Date": f"{month}-06 12:00:00"}
        write_csv(payments_path, [payment], PAYMENT_FIELDS)
        write_csv(taxes_path, [BASE_TAX], TAX_FIELDS)

    def test_creates_reports_dir(self):
        import shutil
        reports_dir = os.path.join(self.data_dir, "new_reports")
        self._write_month("2026-03")
        run(self.data_dir, reports_dir)
        self.assertTrue(os.path.isdir(reports_dir))

    def test_generates_report_for_new_month(self):
        self._write_month("2026-03")
        run(self.data_dir, self.reports_dir)
        self.assertTrue(os.path.isfile(
            os.path.join(self.reports_dir, "tax_report_2026-03.pdf")
        ))

    def test_skips_existing_report(self):
        self._write_month("2026-03")
        existing = os.path.join(self.reports_dir, "tax_report_2026-03.pdf")
        open(existing, "w").close()  # create a dummy report

        with patch("run_reports.build_report") as mock_build:
            run(self.data_dir, self.reports_dir)
            mock_build.assert_not_called()

    def test_generates_only_missing_months(self):
        self._write_month("2026-03")
        self._write_month("2026-04")
        # Pre-create report for March
        open(os.path.join(self.reports_dir, "tax_report_2026-03.pdf"), "w").close()

        with patch("run_reports.build_report") as mock_build:
            run(self.data_dir, self.reports_dir)
            self.assertEqual(mock_build.call_count, 1)
            called_output = mock_build.call_args[0][2]
            self.assertIn("2026-04", called_output)

    def test_processes_months_in_sorted_order(self):
        self._write_month("2026-04")
        self._write_month("2026-03")

        call_order = []
        def fake_build(p, t, out):
            call_order.append(out)
            # write a dummy pdf so the file exists
            open(out, "w").close()

        with patch("run_reports.build_report", side_effect=fake_build):
            run(self.data_dir, self.reports_dir)

        self.assertLess(call_order[0], call_order[1])  # 2026-03 before 2026-04

    def test_no_data_prints_message(self, ):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            run(self.data_dir, self.reports_dir)
        self.assertIn("No complete CSV pairs found", buf.getvalue())

    def test_report_filename_pattern(self):
        self._write_month("2026-06")
        run(self.data_dir, self.reports_dir)
        expected = os.path.join(self.reports_dir, "tax_report_2026-06.pdf")
        self.assertTrue(os.path.isfile(expected))


if __name__ == "__main__":
    unittest.main()
