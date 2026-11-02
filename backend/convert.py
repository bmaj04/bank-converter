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


def clean_statement(df):
    """Turn the raw table into: Date, Description, Debit, Credit (sorted by date)."""
    # 1. Build a real date from "22-Jan-15" plus the Year column
    day_month = df["Transaction Date"].str.rsplit("-", n=1).str[0]
    full_date = day_month + "-" + df["Year"]
    dates = pd.to_datetime(full_date, format="%d-%b-%Y", errors="coerce")

    # 2. Turn the amount text into a real number
    amounts = pd.to_numeric(
        df["Transaction amount"].str.replace(",", "", regex=False),
        errors="coerce",
    )

    # 3. Split into Debit and Credit using the Transaction type
    kind = df["Transaction type"].str.strip().str.lower()
    debit = amounts.where(kind == "debit")
    credit = amounts.where(kind == "credit")

    clean = pd.DataFrame(
        {
            "Date": dates.dt.strftime("%Y-%m-%d"),
            "Description": df["Transaction description"],
            "Debit": debit,
            "Credit": credit,
        }
    )

    bad = clean["Date"].isna() | (debit.isna() & credit.isna())
    if bad.any():
        print(f"Warning: {bad.sum()} row(s) had a bad date or amount. Check them.")

    # 4. Sort oldest to newest (stable, so same-day rows keep their original order)
    clean = clean.sort_values("Date", kind="stable").reset_index(drop=True)
    return clean


def main():
    if len(sys.argv) < 2:
        print("Usage: python convert.py path/to/statement.pdf")
        return

    pdf_path = Path(sys.argv[1])
    rows = extract_rows(pdf_path)

    if not rows:
        print("No tables found. This may be a scanned PDF or a layout without table lines.")
        return

    raw = rows_to_dataframe(rows)
    clean = clean_statement(raw)

    output_path = pdf_path.with_name(pdf_path.stem + "_clean.csv")
    clean.to_csv(output_path, index=False)

    print(f"Converted {len(clean)} transactions -> {output_path}")
    print(clean[["Date", "Debit", "Credit"]].head(10))
    print("Total debits: ", clean["Debit"].sum())
    print("Total credits:", clean["Credit"].sum())


if __name__ == "__main__":
    main()