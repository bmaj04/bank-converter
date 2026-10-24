import sys
from pathlib import Path

import pdfplumber
import pandas as pd


def extract_rows(pdf_path):
    """Read every table on every page and return a list of cleaned rows."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cleaned = [(cell or "").replace("\n", " ").strip() for cell in row]
                    if any(cleaned):
                        rows.append(cleaned)
    return rows


def rows_to_dataframe(rows):
    """Use the first row as the header and drop repeated headers from later pages."""
    if not rows:
        return pd.DataFrame()
    header = rows[0]
    data = [r for r in rows[1:] if r != header and len(r) == len(header)]
    return pd.DataFrame(data, columns=header)


def main():
    if len(sys.argv) < 2:
        print("Usage: python convert.py path/to/statement.pdf")
        return

    pdf_path = Path(sys.argv[1])
    rows = extract_rows(pdf_path)

    if not rows:
        print("No tables found. This may be a scanned PDF or a layout without table lines.")
        return

    df = rows_to_dataframe(rows)
    output_path = pdf_path.with_suffix(".csv")
    df.to_csv(output_path, index=False)

    print(f"Extracted {len(df)} rows -> {output_path}")
    print(df.head())


if __name__ == "__main__":
    main()