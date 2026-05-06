#!/usr/bin/env python3
"""
Discovers GoBD daily zip archives and generates missing daily reports.
Reports are organised into per-month subfolders: reports/YYYY-MM/
"""

import os
import re
import zipfile
import argparse
from generate_report import build_report, read_csv_from_zip

ZIP_PATTERN = re.compile(r"GoBD-daily-archive-(\d{4}-\d{2})-(\d{2})_\d{4}-\d{2}-\d{2}\.zip")


def discover_zips(data_dir: str) -> dict[str, str]:
    """Return {date: zip_path} for all GoBD daily zip files found in data_dir."""
    result = {}
    for filename in os.listdir(data_dir):
        m = ZIP_PATTERN.match(filename)
        if m:
            date = f"{m.group(1)}-{m.group(2)}"  # YYYY-MM-DD
            result[date] = os.path.join(data_dir, filename)
    return result


def run(data_dir: str, reports_dir: str):
    zips = discover_zips(data_dir)
    if not zips:
        print(f"No GoBD daily zip files found in '{data_dir}'.")
        return

    generated = skipped = empty = 0

    for date in sorted(zips):
        month = date[:7]  # YYYY-MM
        month_dir = os.path.join(reports_dir, month)
        os.makedirs(month_dir, exist_ok=True)

        # Read fiscal number; skip days with no Z-report data (no sales)
        try:
            with zipfile.ZipFile(zips[date]) as zf:
                z_totals = read_csv_from_zip(zf, "daily-totals")
        except Exception:
            z_totals = []

        if not z_totals:
            print(f"Skipping {date} – no sales data.")
            empty += 1
            continue

        fiscal = z_totals[0].get("Fiscal Number", "")
        suffix = f"_Z{fiscal}" if fiscal else ""
        report_file = os.path.join(month_dir, f"tax_report_{date}{suffix}.pdf")

        if os.path.isfile(report_file):
            print(f"Skipping {date} – report already exists: {report_file}")
            skipped += 1
            continue

        print(f"Generating report for {date}...")
        build_report(zips[date], report_file)
        generated += 1

    print(f"\nDone. Generated: {generated}, Skipped (already exist): {skipped}, Skipped (no sales): {empty}.")


def main():
    parser = argparse.ArgumentParser(description="Generate missing daily tax reports.")
    parser.add_argument("--data-dir", default="data",
                        help="Folder containing zip archives (default: data)")
    parser.add_argument("--reports-dir", default="reports",
                        help="Root output folder for PDFs (default: reports)")
    args = parser.parse_args()
    run(args.data_dir, args.reports_dir)


if __name__ == "__main__":
    main()
