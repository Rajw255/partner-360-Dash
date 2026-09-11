"""
CALCULATIONS / BUSINESS LOGIC LAYER
====================================
Pure functions that turn raw fact tables (already filtered to the
selected Partner/RM/Cluster/Region + period) into the metrics, gaps,
growth rates, opportunities and narrative insights the dashboard shows.

Keeping this separate from app.py means these formulas are unit-testable
and reusable across sections (Overview, Target vs Achievement, Gap
Analysis, Insights, etc. all call into here instead of recomputing).
"""

from datetime import date
import calendar

import numpy as np
import pandas as pd

from formatting import format_inr, format_count, status_from_achievement


# ---------------------------------------------------------------------------
# Core metric math
# ---------------------------------------------------------------------------

def achievement_pct(actual: float, target: float):
    if not target:
        return None
    return round((actual / target) * 100, 1)


def gap(actual: float, target: float):
    if target is None or actual is None:
        return None
    return target - actual


def gap_pct(actual: float, target: float):
    if not target:
        return None
    return round(((target - actual) / target) * 100, 1)


def growth_pct(current: float, previous: float):
    if not previous:
        return None
    return round(((current - previous) / previous) * 100, 1)


def run_rate_forecast(actual_mtd: float, as_of: date):
    """Simple linear run-rate forecast for month-end business.

    forecast = actual_mtd / days_elapsed * days_in_month
    """
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    days_elapsed = min(as_of.day, days_in_month)
    if days_elapsed == 0:
        return actual_mtd
    return round(actual_mtd / days_elapsed * days_in_month, 2)


# ---------------------------------------------------------------------------
# Aggregate KPI bundle for a filtered transaction set
# ---------------------------------------------------------------------------

def kpi_bundle(txn_df: pd.DataFrame, client_df: pd.DataFrame, as_of: date = None) -> dict:
    """Headline KPIs for whatever partner/period slice is passed in.

    `as_of` anchors the "new clients" window to the dashboard's simulated
    current date (data_layer.TODAY) rather than the real system clock, so
    results stay consistent with how the dummy data was generated.
    """
    if as_of is None:
        as_of = date.today()

    sales = txn_df.loc[txn_df["transaction_type"] != "Redemption", "amount"].sum()
    sip = txn_df.loc[txn_df["transaction_type"] == "SIP", "amount"].sum()
    aum = txn_df["aum_contribution"].sum()
    revenue = txn_df["revenue"].sum()
    insurance = txn_df.loc[txn_df["product_category"] == "Insurance", "amount"].sum()

    total_clients = client_df["client_id"].nunique()
    active_clients = client_df.loc[client_df["status"] == "Active", "client_id"].nunique()
    inactive_clients = total_clients - active_clients
    cutoff = as_of - pd.Timedelta(days=30)
    new_clients = client_df.loc[client_df["joining_date"] >= cutoff]["client_id"].nunique()

    return {
        "sales": sales,
        "sip": sip,
        "aum": aum,
        "revenue": revenue,
        "insurance": insurance,
        "total_clients": total_clients,
        "active_clients": active_clients,
        "inactive_clients": inactive_clients,
        "new_clients": new_clients,
    }


# ---------------------------------------------------------------------------
# Opportunity detection
# ---------------------------------------------------------------------------

def sip_opportunity(client_df: pd.DataFrame, txn_df: pd.DataFrame) -> pd.DataFrame:
    """Active clients who have transacted but never via SIP."""
    active_ids = set(client_df.loc[client_df["status"] == "Active", "client_id"])
    sip_ids = set(txn_df.loc[txn_df["transaction_type"] == "SIP", "client_id"])
    invested_ids = set(txn_df["client_id"])
    target_ids = (active_ids & invested_ids) - sip_ids
    return client_df[client_df["client_id"].isin(target_ids)]


def cross_sell_opportunity(client_df: pd.DataFrame, txn_df: pd.DataFrame, from_cat: str, to_cat: str) -> pd.DataFrame:
    """Clients who hold `from_cat` but not `to_cat`."""
    from_ids = set(txn_df.loc[txn_df["product_category"] == from_cat, "client_id"])
    to_ids = set(txn_df.loc[txn_df["product_category"] == to_cat, "client_id"])
    target_ids = from_ids - to_ids
    return client_df[client_df["client_id"].isin(target_ids)]


def reactivation_opportunity(client_df: pd.DataFrame, min_days: int = 180) -> pd.DataFrame:
    return client_df[(client_df["status"] == "Inactive") & (client_df["last_txn_days_ago"] <= 720)]


def dormant_opportunity(client_df: pd.DataFrame, min_days: int = 365) -> pd.DataFrame:
    return client_df[client_df["last_txn_days_ago"] >= min_days]


def high_value_low_penetration(client_df: pd.DataFrame, txn_df: pd.DataFrame, aum_threshold: float = 1_000_000) -> pd.DataFrame:
    """High AUM clients holding only one product category."""
    aum_by_client = txn_df.groupby("client_id")["aum_contribution"].sum()
    products_by_client = txn_df.groupby("client_id")["product_category"].nunique()
    high_value_ids = aum_by_client[aum_by_client >= aum_threshold].index
    low_pen_ids = products_by_client[products_by_client <= 1].index
    target_ids = set(high_value_ids) & set(low_pen_ids)
    return client_df[client_df["client_id"].isin(target_ids)]


# ---------------------------------------------------------------------------
# Narrative insight generation
# ---------------------------------------------------------------------------

def generate_insights(kpis: dict, target_summary: pd.DataFrame, opportunities: dict, aum_growth_pct=None) -> list:
    """Turn numbers into plain-English insight strings for the Insights panel."""
    insights = []

    sales_row = target_summary[target_summary["Metric"] == "Sales"]
    if not sales_row.empty:
        ach = sales_row["Achievement %"].iloc[0]
        gap_val = sales_row["Gap"].iloc[0]
        if ach is not None:
            if ach >= 90:
                insights.append(("Performance", f"Sales achievement is strong at {ach:.0f}% of target."))
            elif ach >= 70:
                insights.append(("Concern", f"Sales achievement is {ach:.0f}%, leaving a gap of {format_inr(gap_val)}."))
            else:
                insights.append(("Critical", f"Sales achievement is only {ach:.0f}%, a shortfall of {format_inr(gap_val)}. Needs immediate attention."))

    sip_row = target_summary[target_summary["Metric"] == "SIP"]
    if not sip_row.empty and sip_row["Achievement %"].iloc[0] is not None:
        ach = sip_row["Achievement %"].iloc[0]
        gap_val = sip_row["Gap"].iloc[0]
        if ach < 90:
            insights.append(("Concern", f"SIP achievement is below target by {format_inr(gap_val)}."))

    if len(opportunities.get("sip_opp", [])) > 0:
        insights.append(("Opportunity", f"{len(opportunities['sip_opp'])} active clients currently do not have SIPs."))

    if len(opportunities.get("cross_sell", [])) > 0:
        insights.append(("Opportunity", f"{len(opportunities['cross_sell'])} clients hold Mutual Funds but no Insurance product."))

    if len(opportunities.get("dormant", [])) > 0:
        insights.append(("Opportunity", f"{len(opportunities['dormant'])} dormant clients can potentially be reactivated."))

    if len(opportunities.get("high_value", [])) > 0:
        insights.append(("Opportunity", f"{len(opportunities['high_value'])} high-value clients have only one product."))

    if aum_growth_pct is not None:
        direction = "increased" if aum_growth_pct >= 0 else "declined"
        insights.append(("Growth", f"AUM {direction} {abs(aum_growth_pct):.1f}% MoM."))

    # weakest product area
    prod_rows = target_summary[~target_summary["Metric"].isin(["Sales", "SIP", "New Clients"])]
    if not prod_rows.empty and prod_rows["Achievement %"].notna().any():
        weakest = prod_rows.dropna(subset=["Achievement %"]).sort_values("Achievement %").head(1)
        if not weakest.empty:
            row = weakest.iloc[0]
            insights.append(("Focus Area", f"{row['Metric']} has the lowest target achievement at {row['Achievement %']:.0f}%."))

    if not insights:
        insights.append(("Performance", "No significant deviations detected for the selected period."))

    return insights
