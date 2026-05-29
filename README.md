# SumUp Tax Report Generator

A small CLI tool that turns the daily GoBD zip archives from [SumUp](https://sumup.com) into daily PDF tax reports — one per trading day, split by payment method (cash vs. card).

The generated reports are used for bookkeeping on the cash register side, giving a clear daily overview of revenue, tips, and the taxes collected at each VAT rate (7% and 19%).

---

## How it works

SumUp generates a zip archive per day under **Reports → GoBD export**:

```
GoBD-daily-archive-YYYY-MM-DD_YYYY-MM-DD.zip
```

Each zip contains several CSV files. This tool uses three of them:

| File inside zip | Content |
|---|---|
| `GoBD-report-sales-payments-*.csv` | One row per transaction with payment method (CASH / CARD) and total amount |
| `GoBD-report-sales-taxes-*.csv` | One or two rows per transaction with the tax breakdown at 7% and 19% |
| `GoBD-report-sales-totals-*.csv` | One row per transaction including tip amount |

The payments and taxes files are joined via Sale ID to produce a tax breakdown split by payment method. Tips are also attributed to cash or card using the same join. Days where the Z-report contains no data (no sales) are skipped automatically.

---

## Requirements

- Python 3.10+
- [reportlab](https://www.reportlab.com/)

Install the dependency:

```bash
pip install -r requirements.txt
```

---

## Usage

### Automatic (recommended)

Drop the daily zip files into the `data/` folder, keeping the original SumUp filename. Then run:

```bash
./run_report.sh
```

The script scans `data/` for zip archives, skips days that already have a report or had no sales, and writes new PDFs into month subfolders under `reports/`. Running it again is always safe — existing reports are never overwritten.

```
Skipping 2026-03-01 – no sales data.
Generating report for 2026-03-06...
Report saved to: reports/2026-03/tax_report_2026-03-06_Z4.pdf
Generating report for 2026-03-07...
Report saved to: reports/2026-03/tax_report_2026-03-07_Z5.pdf
...
Done. Generated: 17, Skipped (already exist): 0, Skipped (no sales): 4.
```

Optional flags:

```bash
./run_report.sh --data-dir path/to/data --reports-dir path/to/reports
```

### Single report

To generate a report for one specific zip directly:

```bash
python3 generate_report.py GoBD-daily-archive-2026-03-06_2026-03-06.zip [-o output.pdf]
```

---

## Output structure

Reports are saved as `tax_report_YYYY-MM-DD_Z{fiscal}.pdf` in a `reports/YYYY-MM/` subfolder. The date prefix ensures files sort chronologically; the fiscal number matches the SumUp Z-Bericht for that day.

```
reports/
├── 2025-12/
│   ├── tax_report_2025-12-15_Z8.pdf
│   └── tax_report_2025-12-22_Z9.pdf
└── 2026-03/
    ├── tax_report_2026-03-06_Z4.pdf
    ├── tax_report_2026-03-07_Z5.pdf
    └── ...
```

Each PDF contains:

- Heading with merchant name (e.g. *Tagesbericht – Mo' Amor*)
- Full date top-left and Z-Bericht fiscal number top-right (e.g. *Freitag, 06. März 2026 · Z-Bericht Nr. 4*)
- Revenue summary table: total, cash, card, number of transactions, tips split by cash/card
- Tax breakdown for cash payments (Barzahlung) at 7% and 19%
- Tax breakdown for card payments (Kartenzahlung) at 7% and 19%

---

## Project structure

```
.
├── data/                   # Place SumUp zip archives here (gitignored)
├── reports/                # Generated PDF reports (gitignored)
├── generate_report.py      # Core report generation logic
├── run_reports.py          # Zip discovery and orchestration
├── run_report.sh           # Entry point shell script
├── test_generate_report.py # Test suite (48 tests)
└── requirements.txt
```

---

## Running the tests

```bash
python3 -m pytest test_generate_report.py -v
```

---

## Data & privacy

The `data/` and `reports/` folders are excluded from version control via `.gitignore`. Never commit your SumUp exports or generated reports to a public repository.
