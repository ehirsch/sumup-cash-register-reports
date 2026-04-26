# SumUp Tax Report Generator

A small CLI tool that turns the monthly GoBD CSV exports from [SumUp](https://sumup.com) into a clean PDF tax report — one per month, split by payment method (cash vs. card).

The generated reports are used for bookkeeping on the cash register side, giving a clear monthly overview of revenue and the taxes collected at each VAT rate (7% and 19%).

---

## How it works

SumUp generates two CSV files per month under **Reports → GoBD export**:

| File | Content |
|---|---|
| `GoBD-report-sales-payments-YYYY-MM-…csv` | One row per transaction with the payment method (CASH / CARD) and total amount |
| `GoBD-report-sales-taxes-YYYY-MM-…csv` | One or two rows per transaction with the tax breakdown at 7% and 19% |

This tool reads both files, links them via the Sale ID, and produces a PDF with:

- Monthly revenue summary (total, cash, card, number of transactions)
- Tax breakdown per payment method and VAT rate (gross, net, tax amount)

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

Drop the two CSV files for each month into the `data/` folder, keeping the original SumUp filename. Then run:

```bash
./run_report.sh
```

The script scans `data/` for CSV pairs, skips months that already have a report, and writes new PDFs to `reports/`. Running it again is always safe — existing reports are never overwritten.

```
Generating report for 2026-03...
Report saved to: reports/tax_report_2026-03.pdf

Done. Generated: 1, Skipped (already exist): 0.
```

Optional flags:

```bash
./run_report.sh --data-dir path/to/data --reports-dir path/to/reports
```

### Single report

To generate a report for one specific month directly:

```bash
python3 generate_report.py <payments.csv> <taxes.csv> [-o output.pdf]
```

---

## Output

Reports are saved as `tax_report_YYYY-MM.pdf` in the `reports/` folder. The `YYYY-MM` prefix ensures files sort chronologically by filename.

Each PDF contains:

- Heading with merchant name and month (e.g. *Monatsbericht März 2026*)
- Revenue summary table
- Tax breakdown for cash payments (Barzahlung)
- Tax breakdown for card payments (Kartenzahlung)

---

## Project structure

```
.
├── data/                   # Place SumUp CSV exports here (gitignored)
├── reports/                # Generated PDF reports (gitignored)
├── generate_report.py      # Core report generation logic
├── run_reports.py          # CSV discovery and orchestration
├── run_report.sh           # Entry point shell script
├── test_generate_report.py # Test suite
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
