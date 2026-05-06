#!/usr/bin/env python3
"""
Discovers GoBD daily zip archives and generates missing daily reports.
Reports are organised into per-month subfolders: reports/YYYY-MM/
"""

import os
import re
import argparse
from generate_report import build_report

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

    generated = skipped = 0

    for date in sorted(zips):
        month = date[:7]  # YYYY-MM
        month_dir = os.path.join(reports_dir, month)
        os.makedirs(month_dir, exist_ok=True)

        report_file = os.path.join(month_dir, f"tax_report_{date}.pdf")

        if os.path.isfile(report_file):
            print(f"Skipping {date} – report already exists: {report_file}")
            skipped += 1
            continue

        print(f"Generating report for {date}...")
        build_report(zips[date], report_file)
        generated += 1

    print(f"\nDone. Generated: {generated}, Skipped (already exist): {skipped}.")


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
