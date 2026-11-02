import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

random.seed(7)

HEADER = [
    "Account Name", "Account Number", "Transaction Date", "Year",
    "Transaction amount", "Transaction description", "Transaction type",
    "Bank", "Address",
]
NAMES = ["ADA OKAFOR LTD", "TEST TRADERS", "SAMPLE STORES", "DEMO SUPPLIES", "JANE DOE"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]

rows = [HEADER]
for _ in range(40):
    day = random.randint(1, 28)
    month = random.choice(MONTHS)
    kind = random.choice(["Debit", "Credit"])
    amount = random.choice([5000, 12500, 20000, 45000, 150000, 1000000])
    rows.append([
        "DEMO ACCOUNT HOLDER", "0000000000", f"{day:02d}-{month}-26", "2026",
        str(amount), f"NIP/TRANSFER/{random.choice(NAMES)}", kind,
        "Sample Bank", "1 EXAMPLE STREET, LAGOS",
    ])

doc = SimpleDocTemplate("sample_statement.pdf", pagesize=landscape(A4))
table = Table(rows, repeatRows=1)
table.setStyle(TableStyle([
    ("FONTSIZE", (0, 0), (-1, -1), 7),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
]))
doc.build([table])
print("Created sample_statement.pdf with 40 transactions")