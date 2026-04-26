#!/usr/bin/env python3
"""
Discovers CSV pairs in the data folder and generates missing monthly reports.
"""

import os
import re
import sys
import argparse
from generate_report import build_report

PAYMENTS_PATTERN = re.compile(r"GoBD-report-sales-payments-(\d{4}-\d{2})-\d{2}_.*\.csv")
TAXES_PATTERN = re.compile(r"GoBD-report-sales-taxes-(\d{4}-\d{2})-\d{2}_.*\.csv")


def discover_months(data_dir: str) -> dict[str, dict[str, str]]:
    """Return {month: {payments: path, taxes: path}} for complete CSV pairs."""
    months: dict[str, dict[str, str]] = {}

    for filename in os.listdir(data_dir):
        path = os.path.join(data_dir, filename)
        m = PAYMENTS_PATTERN.match(filename)
        if m:
            month = m.group(1)
            months.setdefault(month, {})["payments"] = path
            continue
        m = TAXES_PATTERN.match(filename)
        if m:
            month = m.group(1)
            months.setdefault(month, {})["taxes"] = path

    # Only return months where both files are present
    return {k: v for k, v in months.items() if "payments" in v and "taxes" in v}


def run(data_dir: str, reports_dir: str):
    os.makedirs(reports_dir, exist_ok=True)

    pairs = discover_months(data_dir)
    if not pairs:
        print(f"No complete CSV pairs found in '{data_dir}'.")
        return

    generated = skipped = 0

    for month in sorted(pairs):
        report_file = os.path.join(reports_dir, f"tax_report_{month}.pdf")

        if os.path.isfile(report_file):
            print(f"Skipping {month} – report already exists: {report_file}")
            skipped += 1
            continue

        print(f"Generating report for {month}...")
        files = pairs[month]
        build_report(files["payments"], files["taxes"], report_file)
        generated += 1

    print(f"\nDone. Generated: {generated}, Skipped (already exist): {skipped}.")


def main():
    parser = argparse.ArgumentParser(description="Generate missing monthly tax reports.")
    parser.add_argument("--data-dir", default="data", help="Folder containing CSV files (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Output folder for PDFs (default: reports)")
    args = parser.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
