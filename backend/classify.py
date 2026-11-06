import pandas as pd

# Descriptions that mean "money moved between my own accounts" (OPay wording).
INTERNAL_PREFIXES = ("OWealth Withdrawal", "Auto-save to OWealth", "OWealth Deposit")
FEE_PREFIXES = ("Stamp Duty", "USSD Charge", "Outstanding USSD Charge", "VAT on Transfer Fee")
INTERNAL = "Internal transfer"


def add_type(df):
    """Add a Type column to wallet-style statements (the ones that have an Account column)."""
    if "Account" not in df.columns or "Type" in df.columns:
        return df

    kinds = []
    for desc, credit in zip(df["Description"].fillna(""), df["Credit"]):
        if desc.startswith(INTERNAL_PREFIXES):
            kinds.append(INTERNAL)
        elif desc.startswith("OWealth Interest"):
            kinds.append("Interest")
        elif desc.startswith(FEE_PREFIXES):
            kinds.append("Fee")
        elif desc.startswith("Reversal"):
            kinds.append("Reversal")
        elif pd.notna(credit):
            kinds.append("Receipt")
        else:
            kinds.append("Payment")

    df = df.copy()
    df.insert(list(df.columns).index("Description") + 1, "Type", kinds)
    return df


def drop_internal(df):
    """Remove transfers between the user's own accounts (if the statement has any)."""
    if "Type" not in df.columns:
        return df
    return df[df["Type"] != INTERNAL].reset_index(drop=True)


def summarize(df):
    """Totals that leave out transfers between the user's own accounts."""
    has_types = "Type" in df.columns
    real = df[df["Type"] != INTERNAL] if has_types else df
    return {
        "has_types": has_types,
        "internal_count": int((df["Type"] == INTERNAL).sum()) if has_types else 0,
        "money_in": round(float(real["Credit"].sum()), 2),
        "money_out": round(float(real["Debit"].sum()), 2),
    }