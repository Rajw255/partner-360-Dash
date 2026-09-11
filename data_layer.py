"""
DATA LAYER
==========
This module is the ONLY place that knows where data comes from.

Right now every function below generates realistic dummy data (Phase 1).
In Phase 2 you replace the body of each function with a SQL query against
the company database (e.g. via SQLAlchemy / pyodbc / snowflake-connector)
that returns a pandas DataFrame with the SAME column names used here.
Nothing in app.py, calculations.py, or the UI needs to change when you do
that swap -- that is the whole point of isolating this layer.

Tables produced (matching the spec's data model):
  - partner_master
  - client_master
  - transaction_fact
  - partner_target
  - partner_review

All functions are cached with st.cache_data so the dashboard stays fast;
when you wire up real SQL, keep the @st.cache_data decorator (with a
sensible ttl, e.g. ttl=3600) so you don't hit the database on every click.
"""

import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

RNG_SEED = 42

REGIONS = ["North", "South", "East", "West"]
CLUSTERS = {
    "North": ["Delhi", "Chandigarh"],
    "South": ["Bengaluru", "Chennai"],
    "East": ["Kolkata", "Patna"],
    "West": ["Mumbai", "Pune"],
}
RMS = ["Rahul Mehta", "Sneha Iyer", "Arjun Nair", "Priya Kapoor", "Karan Shah"]
PARTNER_TYPES = ["MFD", "IFA", "RIA-Referral"]
PRODUCT_CATEGORIES = {
    "Mutual Funds": ["Equity MF", "Debt MF", "Hybrid MF"],
    "Insurance": ["Life Insurance", "Health Insurance", "General Insurance"],
    "Fixed Income": ["FD", "Bonds", "NCD", "MLD"],
    "Alternatives": ["PMS", "AIF", "SIF", "Unlisted"],
    "Equity": ["Direct Equity"],
}
FLAT_PRODUCTS = [p for cat in PRODUCT_CATEGORIES.values() for p in cat]
TRANSACTION_TYPES = ["Purchase", "SIP", "Redemption", "Renewal"]

TODAY = date(2026, 9, 10)  # dashboard "as of" date


def _month_range(n_months: int = 18):
    """Last n_months month-start dates ending with the current month."""
    months = []
    y, m = TODAY.year, TODAY.month
    for _ in range(n_months):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))


@st.cache_data(ttl=3600)
def load_partner_master(n_partners: int = 24) -> pd.DataFrame:
    rng = random.Random(RNG_SEED)
    rows = []
    for i in range(1, n_partners + 1):
        region = rng.choice(REGIONS)
        cluster = rng.choice(CLUSTERS[region])
        joining = TODAY - timedelta(days=rng.randint(200, 2200))
        rows.append({
            "partner_id": f"P{i:04d}",
            "partner_name": f"{rng.choice(['ABC','Sunrise','Prime','Zenith','Capital','Wealth','Nova','Horizon','Elite','Trust'])} "
                             f"{rng.choice(['Wealth','Advisors','Investments','Financial','Capital','Partners'])} #{i}",
            "rm": rng.choice(RMS),
            "cluster": cluster,
            "region": region,
            "location": cluster,
            "partner_type": rng.choice(PARTNER_TYPES),
            "arn": f"ARN-{100000+i}",
            "arn_status": rng.choices(["Active", "On Hold", "Expired"], weights=[85, 10, 5])[0],
            "joining_date": joining,
            "status": rng.choices(["Active", "Inactive"], weights=[90, 10])[0],
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_client_master(n_partners: int = 24) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 1)
    partners = load_partner_master(n_partners)
    rows = []
    client_seq = 1
    for _, p in partners.iterrows():
        n_clients = rng.randint(35, 140)
        for _ in range(n_clients):
            joining = TODAY - timedelta(days=rng.randint(15, 2000))
            last_txn_gap = rng.choices(
                [rng.randint(0, 60), rng.randint(61, 180), rng.randint(181, 720)],
                weights=[65, 20, 15],
            )[0]
            rows.append({
                "client_id": f"C{client_seq:06d}",
                "partner_id": p["partner_id"],
                "client_name": f"Client {client_seq}",
                "joining_date": joining,
                "location": p["location"],
                "last_txn_days_ago": last_txn_gap,
                "status": "Active" if last_txn_gap <= 180 else "Inactive",
            })
            client_seq += 1
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_transaction_fact(n_partners: int = 24) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 2)
    np.random.seed(RNG_SEED + 2)
    clients = load_client_master(n_partners)
    months = _month_range(18)
    rows = []
    txn_seq = 1
    for _, c in clients.iterrows():
        # each client transacts a handful of times over the window,
        # more recently active clients transact more often / recently
        n_txns = rng.randint(1, 10) if c["status"] == "Active" else rng.randint(0, 3)
        for _ in range(n_txns):
            m = rng.choice(months)
            txn_date = m + timedelta(days=rng.randint(0, 27))
            if txn_date > TODAY:
                continue
            category = rng.choices(
                list(PRODUCT_CATEGORIES.keys()), weights=[40, 20, 15, 15, 10]
            )[0]
            product = rng.choice(PRODUCT_CATEGORIES[category])
            txn_type = "SIP" if category == "Mutual Funds" and rng.random() < 0.35 else rng.choice(TRANSACTION_TYPES)
            base = {
                "Mutual Funds": 250000, "Insurance": 60000, "Fixed Income": 400000,
                "Alternatives": 1500000, "Equity": 150000,
            }[category]
            amount = max(5000, np.random.lognormal(mean=np.log(base), sigma=0.6))
            revenue = amount * rng.uniform(0.005, 0.02)
            aum_contribution = amount if txn_type != "Redemption" else -amount
            rows.append({
                "transaction_id": f"T{txn_seq:07d}",
                "client_id": c["client_id"],
                "partner_id": c["partner_id"],
                "transaction_date": txn_date,
                "product": product,
                "product_category": category,
                "transaction_type": txn_type,
                "amount": round(amount, 2),
                "revenue": round(revenue, 2),
                "aum_contribution": round(aum_contribution, 2),
            })
            txn_seq += 1
    df = pd.DataFrame(rows)
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["month"] = df["transaction_date"].values.astype("datetime64[M]")
    return df


@st.cache_data(ttl=3600)
def load_partner_target(n_partners: int = 24) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 3)
    partners = load_partner_master(n_partners)
    months = _month_range(18)
    target_types = {
        "Sales": (600000, 15000000),
        "SIP": (100000, 2000000),
        "Insurance": (50000, 1200000),
        "New Clients": (5, 40),
    }
    rows = []
    for _, p in partners.iterrows():
        scale = rng.uniform(0.6, 1.8)
        for m in months:
            for ttype, (lo, hi) in target_types.items():
                rows.append({
                    "partner_id": p["partner_id"],
                    "period": m,
                    "target_type": ttype,
                    "target_value": round(rng.uniform(lo, hi) * scale, 2),
                    "frequency": "Monthly",
                    "created_by": "Cluster Manager",
                    "last_updated": m,
                })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_partner_review(n_partners: int = 24) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 4)
    partners = load_partner_master(n_partners)
    problems = [
        "Low recruitment", "SIP below potential", "Low partner activation",
        "Declining branch performance", "Product concentration", "Low client engagement",
    ]
    approaches = [
        "Conduct partner meets", "Increase SIP campaigns", "Run PMS/AIF/SIF training",
        "Activate dormant partners", "Conduct seminars", "Focus on high-value clients",
    ]
    actions = [
        "Partner Meet", "SIP Campaign", "PMS Training", "Client Reactivation Drive",
        "Insurance Cross-sell Push", "Quarterly Business Review",
    ]
    owners = ["RM", "Partner", "Cluster Manager"]
    statuses = ["Open", "In Progress", "Completed", "Delayed"]
    rows = []
    for _, p in partners.sample(frac=0.7, random_state=4).iterrows():
        review_date = TODAY - timedelta(days=rng.randint(1, 60))
        due_date = review_date + timedelta(days=rng.randint(7, 30))
        rows.append({
            "partner_id": p["partner_id"],
            "review_date": review_date,
            "problem_discussed": rng.choice(problems),
            "approach": rng.choice(approaches),
            "action_item": rng.choice(actions),
            "owner": rng.choice(owners),
            "due_date": due_date,
            "status": rng.choices(statuses, weights=[25, 30, 35, 10])[0],
            "remarks": "",
        })
    return pd.DataFrame(rows)


def get_all_data():
    """Convenience loader used by app.py to pull the full dataset once."""
    return {
        "partner_master": load_partner_master(),
        "client_master": load_client_master(),
        "transaction_fact": load_transaction_fact(),
        "partner_target": load_partner_target(),
        "partner_review": load_partner_review(),
    }
