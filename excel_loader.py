"""
EXCEL INGESTION LAYER
======================
Reads a daily Excel workbook that matches the Partner 360 data model and
turns it into the same five DataFrames that data_layer.py's dummy
generator produces (partner_master, client_master, transaction_fact,
partner_target, partner_review) -- so nothing in app.py or calculations.py
needs to know or care whether the data came from dummy data, this Excel
importer, or a future SQL connection.

Use the companion `partner360_data_template.xlsx` as the file your ops
team fills in and re-uploads each day (or drops into a watched folder --
see find_latest_file below).
"""

import glob
import os
from datetime import date, datetime

import pandas as pd

# Required columns per sheet. Anything beyond these is ignored (harmless
# to leave extra notes columns in the workbook). Missing columns => error.
REQUIRED_COLUMNS = {
    "Partner Master": [
        "partner_id", "partner_name", "rm", "cluster", "region", "location",
        "partner_type", "arn", "arn_status", "joining_date", "status",
    ],
    "Client Master": [
        "client_id", "partner_id", "client_name", "joining_date", "location",
    ],
    "Transaction Fact": [
        "transaction_id", "client_id", "partner_id", "transaction_date",
        "product", "product_category", "transaction_type", "amount", "revenue",
    ],
    "Partner Target": [
        "partner_id", "period", "target_type", "target_value", "frequency",
    ],
    "Partner Review": [
        "partner_id", "review_date", "problem_discussed", "approach",
        "action_item", "owner", "due_date", "status",
    ],
}

DATE_COLUMNS = {
    "Partner Master": ["joining_date"],
    "Client Master": ["joining_date"],
    "Transaction Fact": ["transaction_date"],
    "Partner Target": ["period", "last_updated"],
    "Partner Review": ["review_date", "due_date"],
}

NUMERIC_COLUMNS = {
    "Transaction Fact": ["amount", "revenue"],
    "Partner Target": ["target_value"],
}


def _coerce(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    for col in DATE_COLUMNS.get(sheet_name, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    for col in NUMERIC_COLUMNS.get(sheet_name, []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_excel_workbook(file) -> tuple:
    """Read the uploaded workbook (path or file-like object from
    st.file_uploader) and return (data_dict, messages).

    data_dict is None if there were fatal errors (a required sheet or
    column is missing) -- the caller should show `messages` and stop.
    Otherwise data_dict has the same 5 keys/columns as
    data_layer.get_all_data(), with 'aum_contribution' and 'month' on
    transaction_fact, and 'last_txn_days_ago'/'status' on client_master
    computed automatically rather than requiring manual entry.
    """
    messages = []
    try:
        xls = pd.ExcelFile(file)
    except Exception as e:
        return None, [("error", f"Could not open workbook: {e}")]

    sheets = {}
    fatal = False
    for sheet_name, required_cols in REQUIRED_COLUMNS.items():
        match = next((s for s in xls.sheet_names if s.strip().lower() == sheet_name.lower()), None)
        if match is None:
            messages.append(("error", f"Missing required sheet: '{sheet_name}'."))
            fatal = True
            continue
        df = xls.parse(match)
        df.columns = [str(c).strip() for c in df.columns]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            messages.append(("error", f"Sheet '{sheet_name}' is missing column(s): {', '.join(missing)}."))
            fatal = True
            continue
        # drop fully-blank rows and any row missing its primary key column
        # (guards against stray notes/blank rows left below the data table)
        df = df.dropna(subset=[required_cols[0]]).reset_index(drop=True)
        df = _coerce(df, sheet_name)
        sheets[sheet_name] = df

    if fatal:
        return None, messages

    partner_master = sheets["Partner Master"].copy()
    client_master = sheets["Client Master"].copy()
    transaction_fact = sheets["Transaction Fact"].copy()
    partner_target = sheets["Partner Target"].copy()
    partner_review = sheets["Partner Review"].copy()

    # --- derive fields that should never be manually entered ---
    if "product_category" not in transaction_fact.columns:
        messages.append(("error", "Transaction Fact needs a 'product_category' column."))
        return None, messages

    transaction_fact["aum_contribution"] = transaction_fact.apply(
        lambda r: -abs(r["amount"]) if str(r.get("transaction_type", "")).strip().lower() == "redemption" else r["amount"],
        axis=1,
    )
    transaction_fact["transaction_date"] = pd.to_datetime(transaction_fact["transaction_date"], errors="coerce")
    transaction_fact["month"] = transaction_fact["transaction_date"].values.astype("datetime64[M]")
    bad_dates = transaction_fact["transaction_date"].isna().sum()
    if bad_dates:
        messages.append(("warning", f"{bad_dates} transaction row(s) had an unreadable date and were dropped."))
        transaction_fact = transaction_fact.dropna(subset=["transaction_date"])

    # last transaction recency + active/inactive status, computed from
    # Transaction Fact rather than typed in by hand each day
    last_txn = transaction_fact.groupby("client_id")["transaction_date"].max()
    today_ts = pd.Timestamp(date.today())
    client_master = client_master.set_index("client_id")
    client_master["last_txn_days_ago"] = (today_ts - last_txn).dt.days
    client_master["last_txn_days_ago"] = client_master["last_txn_days_ago"].fillna(9999).astype(int)
    client_master["status"] = client_master["last_txn_days_ago"].apply(lambda d: "Active" if d <= 180 else "Inactive")
    client_master = client_master.reset_index()

    partner_target["period"] = pd.to_datetime(partner_target["period"], errors="coerce").dt.date.apply(
        lambda d: date(d.year, d.month, 1) if pd.notna(d) else d
    )

    data = {
        "partner_master": partner_master,
        "client_master": client_master,
        "transaction_fact": transaction_fact,
        "partner_target": partner_target,
        "partner_review": partner_review,
    }

    # light referential-integrity warnings (non-fatal)
    known_partners = set(partner_master["partner_id"])
    orphan_clients = set(client_master["partner_id"]) - known_partners
    if orphan_clients:
        messages.append(("warning", f"{len(orphan_clients)} partner_id(s) in Client Master aren't in Partner Master."))
    orphan_txn_partners = set(transaction_fact["partner_id"]) - known_partners
    if orphan_txn_partners:
        messages.append(("warning", f"{len(orphan_txn_partners)} partner_id(s) in Transaction Fact aren't in Partner Master."))

    if not messages:
        messages.append(("success", f"Loaded {len(transaction_fact):,} transactions across {len(partner_master)} partners."))

    return data, messages


def find_latest_file(folder: str, pattern: str = "partner360_data_*.xlsx"):
    """For the 'automated folder drop' mode: return the most recently
    modified file matching `pattern` in `folder`, or None if none exist.
    Point `folder` at a network share / synced OneDrive-SharePoint folder
    / scheduled-export destination on a host that has access to it (this
    will NOT work on Streamlit Community Cloud, which has no access to
    your internal network -- see README for the automation options that
    do work there).
    """
    matches = glob.glob(os.path.join(folder, pattern))
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)
