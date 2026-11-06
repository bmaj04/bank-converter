import re
import sys
from pathlib import Path

import pdfplumber
import pandas as pd

# ---------------------------------------------------------------------------
# Part 1: statements whose transactions are in a ruled table (most banks)
# ---------------------------------------------------------------------------

# Column names we recognise (lowercase). Add more here as you meet new banks.
DATE_NAMES = ["transaction date", "trans date", "txn date", "value date", "post date", "date"]
DESC_NAMES = ["transaction description", "description", "narration", "narrative",
              "details", "particulars", "remarks"]
DEBIT_NAMES = ["debit", "debits", "withdrawal", "withdrawals", "money out", "dr"]
CREDIT_NAMES = ["credit", "credits", "deposit", "deposits", "money in", "cr"]
BALANCE_NAMES = ["balance", "running balance", "closing balance"]


class NoTablesFound(Exception):
    """The PDF has no readable table (for example, a scanned image)."""


class UnsupportedLayout(Exception):
    """A table was found, but its columns are not recognised yet."""


def _rewind(source):
    """Make sure a file-like object is read from the start."""
    if hasattr(source, "seek"):
        source.seek(0)


def extract_rows(source):
    """Read every table on every page and return a list of cleaned rows."""
    _rewind(source)
    rows = []
    with pdfplumber.open(source) as pdf:
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


def find_col(df, names):
    """Return the real column name matching any of the given lowercase names."""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name in lookup:
            return lookup[name]
    return None


def to_number(series):
    """Turn text like '12,500.00' or 'NGN 5,000' into a number; blanks become NaN."""
    text = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(text.where(text != ""), errors="coerce")


def _clean_typed_layout(df):
    """Layout A: Transaction Date + Year + one amount column + a Debit/Credit type column."""
    date_c = find_col(df, ["transaction date"])
    year_c = find_col(df, ["year"])
    amt_c = find_col(df, ["transaction amount"])
    type_c = find_col(df, ["transaction type"])
    desc_c = find_col(df, DESC_NAMES)
    if None in (date_c, year_c, amt_c, type_c, desc_c):
        return None

    day_month = df[date_c].str.rsplit("-", n=1).str[0]
    dates = pd.to_datetime(day_month + "-" + df[year_c], format="%d-%b-%Y", errors="coerce")
    amounts = to_number(df[amt_c])
    kind = df[type_c].str.strip().str.lower()

    return pd.DataFrame(
        {
            "Date": dates.dt.strftime("%Y-%m-%d"),
            "Description": df[desc_c],
            "Debit": amounts.where(kind == "debit"),
            "Credit": amounts.where(kind == "credit"),
        }
    )


def _clean_split_layout(df):
    """Layout B: separate Debit and Credit columns (optionally a Balance column)."""
    date_c = find_col(df, DATE_NAMES)
    desc_c = find_col(df, DESC_NAMES)
    debit_c = find_col(df, DEBIT_NAMES)
    credit_c = find_col(df, CREDIT_NAMES)
    bal_c = find_col(df, BALANCE_NAMES)
    if None in (date_c, desc_c, debit_c, credit_c):
        return None

    dates = pd.to_datetime(df[date_c], format="mixed", dayfirst=True, errors="coerce")
    clean = pd.DataFrame(
        {
            "Date": dates.dt.strftime("%Y-%m-%d"),
            "Description": df[desc_c],
            "Debit": to_number(df[debit_c]),
            "Credit": to_number(df[credit_c]),
        }
    )
    if bal_c is not None:
        clean["Balance"] = to_number(df[bal_c])
    return clean


def clean_statement(df):
    """Turn a raw table into Date, Description, Debit, Credit (sorted by date)."""
    clean = _clean_typed_layout(df)
    if clean is None:
        clean = _clean_split_layout(df)
    if clean is None:
        raise UnsupportedLayout(f"Columns found: {list(df.columns)}")

    bad = clean["Date"].isna() | (clean["Debit"].isna() & clean["Credit"].isna())
    if bad.any():
        print(f"Warning: {bad.sum()} row(s) had a bad date or amount. Check them.")

    return clean.sort_values("Date", kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Part 2: wallet-style statements (OPay and similar) where the table has no
# ruled lines. We read the words on each page and use their positions.
# ---------------------------------------------------------------------------

TIME_RE = re.compile(r"^\d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2}$")
AMOUNT_RE = re.compile(r"^(\d[\d,]*\.\d{2}|--)$")
MAX_GAP_INSIDE = 34  # points: furthest a wrapped line may sit from its row, between rows
MAX_GAP_EDGE = 16  # points: same, at the very top or bottom of a page
PAGE_KEY = 1000.0  # lets us sort lines across pages with one number


def _num(text):
    return None if text == "--" else float(text.replace(",", ""))


def _group_lines(words, tol=2.5):
    """Group words that sit on the same visual line."""
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1]["top"] - w["top"]) <= tol:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
    return lines


def is_wallet_layout(source):
    """True if the first page looks like a 'Trans. Time / Balance After' statement."""
    _rewind(source)
    with pdfplumber.open(source) as pdf:
        text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    return "Trans. Time" in text and "Balance After" in text


def parse_wallet_statement(source):
    """Parse a wallet-style statement into a clean DataFrame (or None if nothing found)."""
    _rewind(source)
    anchors, extras, sections, heights = [], [], [], {}

    with pdfplumber.open(source) as pdf:
        for pn, page in enumerate(pdf.pages):
            heights[pn] = float(page.height)
            for line in _group_lines(page.extract_words()):
                ws = line["words"]

                # A section title such as "Wallet Account  Period: 04 Sep ..."
                if any(w["text"] == "Period:" for w in ws):
                    name = " ".join(w["text"] for w in ws if w["x0"] < 224)
                    sections.append((pn * PAGE_KEY + line["top"], name))
                    continue

                # The main line of a transaction starts with its date and time.
                left = " ".join(w["text"] for w in ws if w["x0"] < 128)
                if TIME_RE.match(left):
                    texts = [w["text"] for w in ws if w["x0"] >= 128]
                    i = 3  # skip the value date (three words)
                    desc = []
                    while i < len(texts) and not AMOUNT_RE.match(texts[i]):
                        desc.append(texts[i])
                        i += 1
                    amounts, tail = texts[i:i + 3], texts[i + 3:]
                    if len(amounts) == 3:
                        anchors.append(
                            {
                                "pn": pn,
                                "top": line["top"],
                                "key": pn * PAGE_KEY + line["top"],
                                "time": left,
                                "desc": desc,
                                "debit": _num(amounts[0]),
                                "credit": _num(amounts[1]),
                                "balance": _num(amounts[2]),
                                "channel": tail[0] if tail else "",
                                "ref": "".join(tail[1:]),
                                "before": [],
                                "after": [],
                                "ref_before": [],
                                "ref_after": [],
                            }
                        )
                    continue

                # Anything else is a wrapped description or reference fragment.
                if any(w["text"] in ("Description", "Debit(₦)") for w in ws):
                    continue  # table header row
                if any(
                    w["text"] in ("Opening", "Closing", "Count") or w["text"].startswith("₦")
                    for w in ws
                ):
                    continue  # account summary box
                for w in ws:
                    if 170 <= w["x0"] < 300:
                        extras.append((pn, line["top"], w["x0"], "d", w["text"]))
                    elif w["x0"] >= 450:
                        extras.append((pn, line["top"], w["x0"], "r", w["text"]))

    if not anchors:
        return None

    anchors.sort(key=lambda a: a["key"])
    by_page = {}
    for idx, a in enumerate(anchors):
        by_page.setdefault(a["pn"], []).append(idx)

    # Attach each fragment to the transaction it belongs to: the closest transaction
    # line on the same page. Text is centred in its row, so the closest one is the owner.
    span = {}
    for pn, idxs in by_page.items():
        span[pn] = (anchors[idxs[0]]["top"], anchors[idxs[-1]]["top"])

    for pn, top, x0, kind, text in extras:
        target = None
        same = by_page.get(pn, [])
        if same:
            nearest = min(same, key=lambda j: abs(anchors[j]["top"] - top))
            gap = abs(anchors[nearest]["top"] - top)
            inside = span[pn][0] <= top <= span[pn][1]
            if gap <= (MAX_GAP_INSIDE if inside else MAX_GAP_EDGE):
                target = nearest
        if target is None:  # a row that was split across a page break
            height = heights[pn]
            if top > height * 0.7 and (pn + 1) in by_page:
                first = by_page[pn + 1][0]
                if anchors[first]["top"] < 100:
                    target = first
            elif top < 100 and (pn - 1) in by_page:
                last = by_page[pn - 1][-1]
                if anchors[last]["top"] > heights[pn - 1] * 0.6:
                    target = last
        if target is None:
            continue  # page header, summary box or footer
        a = anchors[target]
        key = pn * PAGE_KEY + top
        above = key < a["key"] - 2.5
        if kind == "d":
            (a["before"] if above else a["after"]).append((key, x0, text))
        else:
            (a["ref_before"] if above else a["ref_after"]).append((key, x0, text))

    rows = []
    for a in anchors:
        words = (
            [t for _, _, t in sorted(a["before"])]
            + a["desc"]
            + [t for _, _, t in sorted(a["after"])]
        )
        reference = (
            "".join(t for _, _, t in sorted(a["ref_before"]))
            + a["ref"]
            + "".join(t for _, _, t in sorted(a["ref_after"]))
        )
        if words and reference and words[-1] == reference:
            words = words[:-1]  # some transfers repeat their reference inside the description
        account = ""
        for key, name in sections:
            if key <= a["key"]:
                account = name
        when = pd.to_datetime(a["time"], format="%d %b %Y %H:%M:%S", errors="coerce")
        rows.append(
            {
                "Date": when.strftime("%Y-%m-%d") if pd.notna(when) else None,
                "Time": when.strftime("%H:%M:%S") if pd.notna(when) else None,
                "Description": " ".join(words),
                "Debit": a["debit"],
                "Credit": a["credit"],
                "Balance": a["balance"],
                "Account": account,
                "Channel": a["channel"],
                "Reference": reference,
            }
        )

    clean = pd.DataFrame(rows)
    # Keep accounts together (in the order they appear), oldest transaction first.
    order = {name: i for i, name in enumerate(dict.fromkeys(clean["Account"]))}
    clean["_acc"] = clean["Account"].map(order)
    clean = clean.sort_values(["_acc", "Date", "Time"], kind="stable")
    return clean.drop(columns="_acc").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Entry point used by both the command line and the API
# ---------------------------------------------------------------------------

def parse_statement(source):
    """Detect the layout and return a clean DataFrame.

    Raises NoTablesFound or UnsupportedLayout when the file cannot be read.
    """
    if is_wallet_layout(source):
        clean = parse_wallet_statement(source)
        if clean is not None and len(clean):
            return clean

    rows = extract_rows(source)
    if not rows:
        raise NoTablesFound()
    return clean_statement(rows_to_dataframe(rows))


def main():
    if len(sys.argv) < 2:
        print("Usage: python convert.py path/to/statement.pdf")
        return

    pdf_path = Path(sys.argv[1])
    try:
        clean = parse_statement(pdf_path)
    except NoTablesFound:
        print("No tables found. This may be a scanned PDF or a layout without table lines.")
        return
    except UnsupportedLayout as problem:
        print("Layout not recognised.", problem)
        return

    output_path = pdf_path.with_name(pdf_path.stem + "_clean.csv")
    clean.to_csv(output_path, index=False)

    print(f"Converted {len(clean)} transactions -> {output_path}")
    show = [c for c in ("Date", "Description", "Debit", "Credit") if c in clean.columns]
    print(clean[show].head(8).to_string())
    if "Account" in clean.columns:
        print()
        print(clean.groupby("Account", sort=False)[["Debit", "Credit"]].sum().round(2))
    else:
        print("Total debits: ", round(clean["Debit"].sum(), 2))
        print("Total credits:", round(clean["Credit"].sum(), 2))


if __name__ == "__main__":
    main()