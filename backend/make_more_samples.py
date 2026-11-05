import random
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

random.seed(11)
NAMES = ["ADA OKAFOR LTD", "TEST TRADERS", "SAMPLE STORES", "DEMO SUPPLIES", "JANE DOE"]
AMOUNTS = [2500, 5000, 12500, 20000, 45000, 150000, 400000]


def money(n):
    return f"{n:,.2f}"


def build(filename, header, rows):
    doc = SimpleDocTemplate(filename, pagesize=landscape(A4))
    table = Table([header] + rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    doc.build([table])


# Bank B: Date (dd/mm/yyyy), Narration, Withdrawals, Deposits, Balance
d = date(2026, 3, 1)
balance = 500000.0
rows, debits, credits = [], 0, 0
for _ in range(30):
    d += timedelta(days=random.randint(0, 2))
    amount = random.choice(AMOUNTS)
    narration = f"TRF {random.choice(NAMES)}"
    if random.random() < 0.5:
        balance -= amount
        debits += amount
        rows.append([f"{d:%d/%m/%Y}", narration, money(amount), "", money(balance)])
    else:
        balance += amount
        credits += amount
        rows.append([f"{d:%d/%m/%Y}", narration, "", money(amount), money(balance)])
build("sample_bank_b.pdf", ["Date", "Narration", "Withdrawals", "Deposits", "Balance"], rows)
print(f"sample_bank_b.pdf: 30 rows, debits {debits}, credits {credits}")

# Bank C: Txn Date (dd-Mon-yyyy), Details, Debit, Credit, with "-" for empty cells
d = date(2026, 4, 1)
rows, debits, credits = [], 0, 0
for _ in range(30):
    d += timedelta(days=random.randint(0, 2))
    amount = random.choice(AMOUNTS)
    details = f"POS/NIP {random.choice(NAMES)}"
    if random.random() < 0.5:
        debits += amount
        rows.append([f"{d:%d-%b-%Y}", details, money(amount), "-"])
    else:
        credits += amount
        rows.append([f"{d:%d-%b-%Y}", details, "-", money(amount)])
build("sample_bank_c.pdf", ["Txn Date", "Details", "Debit", "Credit"], rows)
print(f"sample_bank_c.pdf: 30 rows, debits {debits}, credits {credits}")