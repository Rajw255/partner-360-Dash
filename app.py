"""
Partner 360 / Partner Tracker Dashboard
========================================
Phase 1 prototype (dummy data). See README.md for the phase roadmap and
for how to swap data_layer.py over to real SQL later.

Run locally:   streamlit run app.py
Deploy free:   push this folder to GitHub, then deploy on
               https://share.streamlit.io (Streamlit Community Cloud)
"""

from datetime import date
import os

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from data_layer import get_all_data, TODAY as DEMO_TODAY
from formatting import format_inr, format_count, format_pct, status_from_achievement, STATUS_COLOR
import calculations as calc
import excel_loader

# ---------------------------------------------------------------------------
# Page config & light theming
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Partner 360 | Wealth Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

PRIMARY = "#0B3D66"   # deep navy - financial services feel
ACCENT = "#C89B3C"    # muted gold accent
BG = "#F5F7FA"

st.markdown(f"""
<style>
.block-container {{ padding-top: 1.5rem; }}
div[data-testid="stMetric"] {{
    background: white; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 14px 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}}
h1, h2, h3 {{ color: {PRIMARY}; }}
.status-pill {{
    display:inline-block; padding: 2px 10px; border-radius: 999px;
    color:white; font-size: 0.78rem; font-weight:600;
}}
.insight-card {{
    background:white; border-left: 4px solid {ACCENT}; border-radius:6px;
    padding:10px 14px; margin-bottom:8px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data source: dummy sample data, a daily Excel upload, or an auto-detected
# file in a watched folder (for on-prem/scheduled setups). See README for
# which mode fits your setup and how to move from manual to automated.
# ---------------------------------------------------------------------------
st.sidebar.markdown(f"## 📊 Partner 360")
st.sidebar.caption("Wealth Management Partner Tracker — Prototype")

st.sidebar.markdown("---")
st.sidebar.markdown("**Data Source**")
source_mode = st.sidebar.radio(
    "Source", ["Sample Data (demo)", "Upload Daily Excel", "Auto-load from folder"],
    label_visibility="collapsed",
)

data = None
if source_mode == "Sample Data (demo)":
    data = get_all_data()
    TODAY = DEMO_TODAY
    st.sidebar.caption("Showing randomly generated dummy data.")

elif source_mode == "Upload Daily Excel":
    uploaded = st.sidebar.file_uploader(
        "Upload today's workbook", type=["xlsx"],
        help="Use the partner360_data_template.xlsx format — one sheet per table.",
    )
    if uploaded is None:
        st.info("👈 Upload today's Excel workbook in the sidebar to load the dashboard "
                 "(use the `partner360_data_template.xlsx` format — one sheet per table).")
        st.stop()
    data, messages = excel_loader.load_excel_workbook(uploaded)
    for level, msg in messages:
        getattr(st.sidebar, level if level in ("error", "warning", "success") else "info")(msg)
    if data is None:
        st.error("The uploaded file has errors — fix them (see sidebar) and re-upload.")
        st.stop()
    TODAY = date.today()

else:  # Auto-load from folder
    folder = st.sidebar.text_input("Folder path", value="/data", help="A location this server can read — see README.")
    latest = excel_loader.find_latest_file(folder)
    if latest is None:
        st.warning(f"No file matching `partner360_data_*.xlsx` found in `{folder}`. "
                    "This mode needs a server that has access to that folder (won't work on "
                    "Streamlit Community Cloud) — see README for automation options.")
        st.stop()
    data, messages = excel_loader.load_excel_workbook(latest)
    for level, msg in messages:
        getattr(st.sidebar, level if level in ("error", "warning", "success") else "info")(msg)
    if data is None:
        st.error(f"`{os.path.basename(latest)}` has errors — fix it and it will be picked up on next refresh.")
        st.stop()
    TODAY = date.today()
    st.sidebar.caption(f"Auto-loaded: {os.path.basename(latest)}")

partner_master = data["partner_master"]
client_master = data["client_master"]
transaction_fact = data["transaction_fact"]
partner_target = data["partner_target"]
partner_review = data["partner_review"]


# ---------------------------------------------------------------------------
# Sidebar: identity / access simulation + filters (Section 6, 19)
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.markdown("**View as** *(simulates login/access — Phase 5 replaces this with real auth)*")
role = st.sidebar.selectbox("Role", ["Admin", "Cluster Manager", "RM", "Partner"])

filtered_partners = partner_master.copy()

region_sel = st.sidebar.selectbox("Region", ["All"] + sorted(partner_master["region"].unique().tolist()))
if region_sel != "All":
    filtered_partners = filtered_partners[filtered_partners["region"] == region_sel]

cluster_sel = st.sidebar.selectbox("Cluster", ["All"] + sorted(filtered_partners["cluster"].unique().tolist()))
if cluster_sel != "All":
    filtered_partners = filtered_partners[filtered_partners["cluster"] == cluster_sel]

rm_sel = st.sidebar.selectbox("RM", ["All"] + sorted(filtered_partners["rm"].unique().tolist()))
if rm_sel != "All":
    filtered_partners = filtered_partners[filtered_partners["rm"] == rm_sel]

partner_options = ["All Partners (Roll-up)"] + filtered_partners["partner_name"].tolist()
partner_sel = st.sidebar.selectbox("Partner", partner_options)

st.sidebar.markdown("---")
years = sorted({d.year for d in partner_target["period"]})
year_sel = st.sidebar.selectbox("Year", years, index=len(years) - 1)
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
month_sel = st.sidebar.selectbox("Month", month_names, index=TODAY.month - 1)
month_num = month_names.index(month_sel) + 1
period_start = date(year_sel, month_num, 1)

st.sidebar.caption(f"Period selected: **{month_sel} {year_sel}** · As of {TODAY.strftime('%d %b %Y')}")

st.sidebar.markdown("---")
section = st.sidebar.radio(
    "Navigate",
    [
        "1. Partner Overview",
        "2. Business Performance",
        "3. Client Analytics",
        "4. Product Performance",
        "5. Target vs Achievement",
        "6. Growth & Trends",
        "7. Opportunity / Gap Analysis",
        "8. Partner Review",
        "9. Action Tracker",
        "10. Download / Reports",
    ],
)

# ---------------------------------------------------------------------------
# Resolve the active partner-id set for every section below.
# "All Partners (Roll-up)" aggregates every partner in the current
# region/cluster/RM filter -- this is how an RM or Cluster Manager gets a
# rolled-up view instead of a single partner's numbers.
# ---------------------------------------------------------------------------
if partner_sel == "All Partners (Roll-up)":
    active_partner_ids = filtered_partners["partner_id"].tolist()
    header_name = f"{rm_sel if rm_sel != 'All' else cluster_sel if cluster_sel != 'All' else region_sel if region_sel != 'All' else 'All Partners'} (Roll-up)"
else:
    active_partner_ids = filtered_partners.loc[filtered_partners["partner_name"] == partner_sel, "partner_id"].tolist()
    header_name = partner_sel

if not active_partner_ids:
    st.warning("No partners match the current filter selection.")
    st.stop()

clients = client_master[client_master["partner_id"].isin(active_partner_ids)]
txns_all_time = transaction_fact[transaction_fact["partner_id"].isin(active_partner_ids)]
targets_all = partner_target[partner_target["partner_id"].isin(active_partner_ids)]
reviews = partner_review[partner_review["partner_id"].isin(active_partner_ids)]

period_ts = pd.Timestamp(period_start)
txns_month = txns_all_time[txns_all_time["month"] == period_ts]
prev_period_ts = (period_ts - pd.DateOffset(months=1))
txns_prev_month = txns_all_time[txns_all_time["month"] == prev_period_ts]
targets_month = targets_all[targets_all["period"] == period_start]

kpis = calc.kpi_bundle(txns_month, clients, as_of=TODAY)
kpis_prev = calc.kpi_bundle(txns_prev_month, clients, as_of=TODAY)

st.title(header_name)
st.caption(f"{'Partner' if partner_sel != 'All Partners (Roll-up)' else 'Roll-up view'} · {month_sel} {year_sel} · {len(active_partner_ids)} partner(s) in scope")


# ---------------------------------------------------------------------------
# Shared: target-vs-actual summary table (used by several sections)
# ---------------------------------------------------------------------------
def build_target_summary():
    rows = []
    metric_to_target_type = {
        "Sales": "Sales", "SIP": "SIP", "Insurance": "Insurance", "New Clients": "New Clients",
    }
    actual_map = {
        "Sales": kpis["sales"], "SIP": kpis["sip"], "Insurance": kpis["insurance"],
        "New Clients": kpis["new_clients"],
    }
    for metric, ttype in metric_to_target_type.items():
        target_val = targets_month.loc[targets_month["target_type"] == ttype, "target_value"].sum()
        actual_val = actual_map[metric]
        rows.append({
            "Metric": metric,
            "Target": target_val,
            "Actual": actual_val,
            "Achievement %": calc.achievement_pct(actual_val, target_val),
            "Gap": calc.gap(actual_val, target_val),
        })
    return pd.DataFrame(rows)


target_summary = build_target_summary()


# ===========================================================================
# SECTION 1 — PARTNER OVERVIEW
# ===========================================================================
if section.startswith("1."):
    st.subheader("Key Performance Indicators")

    sales_target = target_summary.loc[target_summary["Metric"] == "Sales", "Target"].iloc[0]
    sales_ach = target_summary.loc[target_summary["Metric"] == "Sales", "Achievement %"].iloc[0]
    sales_gap = target_summary.loc[target_summary["Metric"] == "Sales", "Gap"].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Sales", format_inr(kpis["sales"]), f"{calc.growth_pct(kpis['sales'], kpis_prev['sales']) or 0:.1f}% MoM")
    c2.metric("Sales Target", format_inr(sales_target))
    c3.metric("Achievement %", format_pct(sales_ach) if sales_ach is not None else "-")
    c4.metric("Target Gap", format_inr(sales_gap) if sales_gap is not None else "-")
    c5.metric("Revenue", format_inr(kpis["revenue"]))

    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("SIP", format_inr(kpis["sip"]))
    c7.metric("AUM (net flow)", format_inr(kpis["aum"]))
    c8.metric("Total Clients", format_count(kpis["total_clients"]))
    c9.metric("Active Clients", format_count(kpis["active_clients"]))
    c10.metric("New Clients", format_count(kpis["new_clients"]))

    st.markdown("---")
    st.subheader("Business Insights")
    opps = {
        "sip_opp": calc.sip_opportunity(clients, txns_all_time),
        "cross_sell": calc.cross_sell_opportunity(clients, txns_all_time, "Mutual Funds", "Insurance"),
        "dormant": calc.dormant_opportunity(clients),
        "high_value": calc.high_value_low_penetration(clients, txns_all_time),
    }
    insights = calc.generate_insights(kpis, target_summary, opps, calc.growth_pct(kpis["aum"], kpis_prev["aum"]))
    for tag, text in insights:
        st.markdown(f"<div class='insight-card'><b>{tag}:</b> {text}</div>", unsafe_allow_html=True)


# ===========================================================================
# SECTION 2 — BUSINESS PERFORMANCE
# ===========================================================================
elif section.startswith("2."):
    st.subheader("Business Trends")

    monthly = txns_all_time.groupby("month").agg(
        sales=("amount", lambda s: s[txns_all_time.loc[s.index, "transaction_type"] != "Redemption"].sum()),
        sip=("amount", lambda s: s[txns_all_time.loc[s.index, "transaction_type"] == "SIP"].sum()),
        aum=("aum_contribution", "sum"),
    ).reset_index().sort_values("month").tail(12)
    monthly["aum_cum"] = monthly["aum"].cumsum()

    tabs = st.tabs(["Sales Trend", "SIP Trend", "AUM Trend", "Target vs Actual"])
    with tabs[0]:
        fig = px.bar(monthly, x="month", y="sales", title="Monthly Sales Trend")
        fig.update_traces(marker_color=PRIMARY)
        st.plotly_chart(fig, use_container_width=True)
    with tabs[1]:
        fig = px.line(monthly, x="month", y="sip", markers=True, title="Monthly SIP Trend")
        fig.update_traces(line_color=ACCENT)
        st.plotly_chart(fig, use_container_width=True)
    with tabs[2]:
        fig = px.area(monthly, x="month", y="aum_cum", title="Cumulative AUM Trend")
        fig.update_traces(line_color=PRIMARY)
        st.plotly_chart(fig, use_container_width=True)
    with tabs[3]:
        sales_target_trend = targets_all[targets_all["target_type"] == "Sales"].groupby("period")["target_value"].sum().reset_index()
        sales_target_trend = sales_target_trend.rename(columns={"period": "month", "target_value": "target"})
        merged = pd.merge(monthly[["month", "sales"]], sales_target_trend, on="month", how="left")
        fig = go.Figure()
        fig.add_bar(x=merged["month"], y=merged["sales"], name="Actual", marker_color=PRIMARY)
        fig.add_scatter(x=merged["month"], y=merged["target"], name="Target", mode="lines+markers", line_color=ACCENT)
        fig.update_layout(title="Sales — Target vs Actual")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    mom = calc.growth_pct(kpis["sales"], kpis_prev["sales"])
    forecast = calc.run_rate_forecast(kpis["sales"], TODAY if period_start.month == TODAY.month and period_start.year == TODAY.year else date(period_start.year, period_start.month, 28))
    col1.metric("MoM Growth (Sales)", format_pct(mom) if mom is not None else "-")
    col2.metric("Run-Rate Forecast (Month-End Sales)", format_inr(forecast))
    col3.metric("YTD Sales", format_inr(txns_all_time[txns_all_time["month"].dt.year == year_sel]["amount"].sum()))


# ===========================================================================
# SECTION 3 — CLIENT ANALYTICS
# ===========================================================================
elif section.startswith("3."):
    st.subheader("Client Analytics")

    total = kpis["total_clients"] or 1
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Clients", format_count(kpis["total_clients"]))
    c2.metric("Active Clients", format_count(kpis["active_clients"]))
    c3.metric("Inactive Clients", format_count(kpis["inactive_clients"]))
    c4.metric("New Clients (30d)", format_count(kpis["new_clients"]))

    c5, c6, c7, c8 = st.columns(4)
    avg_aum = txns_all_time.groupby("client_id")["aum_contribution"].sum().mean() if not txns_all_time.empty else 0
    sales_per_client = kpis["sales"] / total
    txns_per_client = len(txns_month) / total if total else 0
    retention = 100 * kpis["active_clients"] / total
    c5.metric("Avg AUM / Client", format_inr(avg_aum))
    c6.metric("Sales / Client (month)", format_inr(sales_per_client))
    c7.metric("Transactions / Client (month)", f"{txns_per_client:.2f}")
    c8.metric("Retention %", format_pct(retention))

    st.markdown("---")
    colA, colB = st.columns(2)
    with colA:
        fig = px.pie(
            values=[kpis["active_clients"], kpis["inactive_clients"]],
            names=["Active", "Inactive"], title="Active vs Inactive Clients",
            color_discrete_sequence=[PRIMARY, "#cbd5e1"],
        )
        st.plotly_chart(fig, use_container_width=True)
    with colB:
        products_per_client = txns_all_time.groupby("client_id")["product_category"].nunique()
        seg = pd.cut(products_per_client, bins=[0, 1, 2, 10], labels=["1 product", "2 products", "3+ products"])
        seg_counts = seg.value_counts().reindex(["1 product", "2 products", "3+ products"]).fillna(0)
        fig = px.bar(x=seg_counts.index, y=seg_counts.values, title="Product Penetration (Clients)",
                     labels={"x": "", "y": "Clients"})
        fig.update_traces(marker_color=ACCENT)
        st.plotly_chart(fig, use_container_width=True)

    new_trend = clients.groupby(clients["joining_date"].apply(lambda d: date(d.year, d.month, 1))).size().reset_index()
    new_trend.columns = ["month", "new_clients"]
    new_trend = new_trend.sort_values("month").tail(12)
    fig = px.line(new_trend, x="month", y="new_clients", markers=True, title="New Client Trend")
    fig.update_traces(line_color=PRIMARY)
    st.plotly_chart(fig, use_container_width=True)


# ===========================================================================
# SECTION 4 — PRODUCT PERFORMANCE
# ===========================================================================
elif section.startswith("4."):
    st.subheader("Product Performance")

    prod_actual = txns_month.groupby("product_category")["amount"].sum().reset_index()
    prod_actual.columns = ["Category", "Actual"]
    cat_target_map = {"Mutual Funds": "Sales", "Insurance": "Insurance"}
    rows = []
    for cat in ["Mutual Funds", "Insurance", "Fixed Income", "Alternatives", "Equity"]:
        actual = prod_actual.loc[prod_actual["Category"] == cat, "Actual"].sum()
        ttype = cat_target_map.get(cat)
        target = targets_month.loc[targets_month["target_type"] == ttype, "target_value"].sum() if ttype else None
        rows.append({
            "Category": cat, "Target": target, "Actual": actual,
            "Achievement %": calc.achievement_pct(actual, target) if target else None,
            "Contribution %": None,
        })
    prod_df = pd.DataFrame(rows)
    total_actual = prod_df["Actual"].sum() or 1
    prod_df["Contribution %"] = (prod_df["Actual"] / total_actual * 100).round(1)

    display_df = prod_df.copy()
    display_df["Target"] = display_df["Target"].apply(lambda v: format_inr(v) if pd.notna(v) else "—")
    display_df["Actual"] = display_df["Actual"].apply(format_inr)
    display_df["Achievement %"] = display_df["Achievement %"].apply(lambda v: format_pct(v) if pd.notna(v) else "—")
    display_df["Contribution %"] = display_df["Contribution %"].apply(lambda v: format_pct(v))
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    colA, colB = st.columns(2)
    with colA:
        fig = px.pie(prod_df, values="Actual", names="Category", title="Product Contribution",
                     color_discrete_sequence=px.colors.sequential.Blues_r)
        st.plotly_chart(fig, use_container_width=True)
    with colB:
        fig = px.bar(prod_df.dropna(subset=["Achievement %"]), x="Category", y="Achievement %",
                     title="Target Achievement by Product", color_discrete_sequence=[ACCENT])
        fig.add_hline(y=100, line_dash="dot", line_color="#999")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Sub-Product Breakdown")
    sub = txns_month.groupby(["product_category", "product"])["amount"].sum().reset_index()
    sub.columns = ["Category", "Product", "Actual"]
    sub["Actual"] = sub["Actual"].apply(format_inr)
    st.dataframe(sub, use_container_width=True, hide_index=True)


# ===========================================================================
# SECTION 5 — TARGET VS ACHIEVEMENT
# ===========================================================================
elif section.startswith("5."):
    st.subheader(f"Target vs Achievement — {month_sel} {year_sel}")

    disp = target_summary.copy()
    disp["Status"] = disp["Achievement %"].apply(status_from_achievement)
    disp["Target"] = disp["Target"].apply(format_inr) if "Target" in disp else disp["Target"]

    # keep New Clients as a count, everything else as currency
    def fmt_row(row, col):
        raw = target_summary.loc[target_summary["Metric"] == row["Metric"], col].iloc[0]
        if row["Metric"] == "New Clients":
            return format_count(raw)
        return format_inr(raw)

    disp["Target"] = disp.apply(lambda r: fmt_row(r, "Target"), axis=1)
    disp["Actual"] = disp.apply(lambda r: fmt_row(r, "Actual"), axis=1)
    disp["Gap"] = disp.apply(lambda r: fmt_row(r, "Gap"), axis=1)
    disp["Achievement %"] = target_summary["Achievement %"].apply(lambda v: format_pct(v) if pd.notna(v) else "—")

    def pill(status):
        color = STATUS_COLOR.get(status, "#6b7280")
        return f"<span class='status-pill' style='background:{color}'>{status}</span>"

    disp["Status"] = disp["Status"].apply(pill)
    st.write(disp[["Metric", "Target", "Actual", "Achievement %", "Gap", "Status"]].to_html(escape=False, index=False), unsafe_allow_html=True)

    st.markdown("---")
    fig = go.Figure()
    fig.add_bar(x=target_summary["Metric"], y=target_summary["Target"], name="Target", marker_color="#cbd5e1")
    fig.add_bar(x=target_summary["Metric"], y=target_summary["Actual"], name="Actual", marker_color=PRIMARY)
    fig.update_layout(barmode="group", title="Target vs Actual by Metric")
    st.plotly_chart(fig, use_container_width=True)


# ===========================================================================
# SECTION 6 — GROWTH & TRENDS
# ===========================================================================
elif section.startswith("6."):
    st.subheader("Growth Analysis")

    monthly = txns_all_time.groupby("month").agg(
        sales=("amount", lambda s: s[txns_all_time.loc[s.index, "transaction_type"] != "Redemption"].sum()),
        sip=("amount", lambda s: s[txns_all_time.loc[s.index, "transaction_type"] == "SIP"].sum()),
        aum=("aum_contribution", "sum"),
    ).reset_index().sort_values("month")
    monthly["mom_growth"] = monthly["sales"].pct_change() * 100
    yoy_curr = monthly[monthly["month"] == period_ts]["sales"].sum()
    yoy_prev = monthly[monthly["month"] == (period_ts - pd.DateOffset(years=1))]["sales"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("MoM Growth", format_pct(calc.growth_pct(kpis["sales"], kpis_prev["sales"]) or 0))
    c2.metric("YoY Growth", format_pct(calc.growth_pct(yoy_curr, yoy_prev)) if yoy_prev else "—")
    ytd = txns_all_time[(txns_all_time["month"].dt.year == year_sel) & (txns_all_time["month"] <= period_ts)]["amount"].sum()
    c3.metric("YTD Sales", format_inr(ytd))

    fig = px.line(monthly.tail(12), x="month", y="mom_growth", markers=True, title="MoM Growth % Trend")
    fig.add_hline(y=0, line_color="#999")
    fig.update_traces(line_color=PRIMARY)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Area classification** *(based on last-3-month sales trend)*")
    recent = monthly.tail(3)["sales"]
    if len(recent) == 3:
        trend = recent.iloc[-1] - recent.iloc[0]
        label = "🟢 Fast-growing" if trend > 0.1 * recent.iloc[0] else ("🔴 Declining" if trend < -0.1 * recent.iloc[0] else "🟡 Stable")
        st.info(f"Sales trend over the last 3 months: **{label}**")


# ===========================================================================
# SECTION 7 — OPPORTUNITY / GAP ANALYSIS
# ===========================================================================
elif section.startswith("7."):
    st.subheader("Gap Analysis")

    gap_cols = st.columns(4)
    for i, row in target_summary.iterrows():
        with gap_cols[i % 4]:
            ach = row["Achievement %"]
            st.metric(
                f"{row['Metric']} Gap",
                format_count(row["Gap"]) if row["Metric"] == "New Clients" else format_inr(row["Gap"]),
                f"{ach:.0f}% achieved" if ach is not None else "no target",
            )

    st.markdown("---")
    st.subheader("Client Opportunities")

    sip_opp = calc.sip_opportunity(clients, txns_all_time)
    cross_opp = calc.cross_sell_opportunity(clients, txns_all_time, "Mutual Funds", "Insurance")
    react_opp = calc.reactivation_opportunity(clients)
    dormant_opp = calc.dormant_opportunity(clients)
    hv_opp = calc.high_value_low_penetration(clients, txns_all_time)

    oc1, oc2, oc3, oc4, oc5 = st.columns(5)
    oc1.metric("SIP Opportunity", format_count(len(sip_opp)))
    oc2.metric("Cross-sell (MF→Insurance)", format_count(len(cross_opp)))
    oc3.metric("Reactivation Candidates", format_count(len(react_opp)))
    oc4.metric("Dormant Clients", format_count(len(dormant_opp)))
    oc5.metric("High-Value, Low Penetration", format_count(len(hv_opp)))

    st.markdown(f"""
    <div class='insight-card'>📌 <b>{len(sip_opp)}</b> active clients have no SIP.</div>
    <div class='insight-card'>📌 <b>{len(hv_opp)}</b> high-value clients have only one product.</div>
    <div class='insight-card'>📌 <b>{len(dormant_opp)}</b> dormant clients can potentially be reactivated.</div>
    <div class='insight-card'>📌 <b>{len(cross_opp)}</b> Mutual Fund clients have no Insurance relationship.</div>
    """, unsafe_allow_html=True)

    with st.expander("View SIP Opportunity client list"):
        st.dataframe(sip_opp[["client_id", "client_name", "location", "status"]], use_container_width=True, hide_index=True)
    with st.expander("View Dormant client list"):
        st.dataframe(dormant_opp[["client_id", "client_name", "last_txn_days_ago"]], use_container_width=True, hide_index=True)


# ===========================================================================
# SECTION 8 — PARTNER REVIEW
# ===========================================================================
elif section.startswith("8."):
    st.subheader("Partner Review")

    if reviews.empty:
        st.info("No review entries logged for this selection yet.")
    else:
        show = reviews.merge(partner_master[["partner_id", "partner_name"]], on="partner_id", how="left")
        st.dataframe(
            show[["partner_name", "review_date", "problem_discussed", "approach", "status"]]
            .rename(columns={
                "partner_name": "Partner", "review_date": "Review Date",
                "problem_discussed": "Problem Discussed", "approach": "Approach / Way Forward",
                "status": "Status",
            }),
            use_container_width=True, hide_index=True,
        )

    st.markdown("---")
    st.subheader("Log a New Review")
    with st.form("review_form"):
        colf1, colf2 = st.columns(2)
        problem = colf1.selectbox("Problem Discussed", [
            "Low recruitment", "SIP below potential", "Low partner activation",
            "Declining branch performance", "Product concentration", "Low client engagement",
        ])
        approach = colf2.selectbox("Approach / Way Forward", [
            "Conduct partner meets", "Increase SIP campaigns", "Run PMS/AIF/SIF training",
            "Activate dormant partners", "Conduct seminars", "Focus on high-value clients",
        ])
        next_review = st.date_input("Next Review Date")
        remarks = st.text_area("Remarks")
        submitted = st.form_submit_button("Save Review")
        if submitted:
            st.success("Review captured for this session. Wire this form to your Partner Review table (Phase 3) to persist it.")


# ===========================================================================
# SECTION 9 — ACTION TRACKER
# ===========================================================================
elif section.startswith("9."):
    st.subheader("Action Tracker")

    if reviews.empty:
        st.info("No action items for this selection.")
    else:
        show = reviews.merge(partner_master[["partner_id", "partner_name"]], on="partner_id", how="left").copy()
        show["overdue"] = (pd.to_datetime(show["due_date"]) < pd.Timestamp(TODAY)) & (show["status"] != "Completed")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Open", int((show["status"] == "Open").sum()))
        c2.metric("In Progress", int((show["status"] == "In Progress").sum()))
        c3.metric("Completed", int((show["status"] == "Completed").sum()))
        c4.metric("Overdue", int(show["overdue"].sum()))

        def style_status(row):
            if row["overdue"]:
                return ["background-color:#fde2e2"] * len(row)
            if row["status"] == "Completed":
                return ["background-color:#e3f5e6"] * len(row)
            return [""] * len(row)

        table = show[["partner_name", "action_item", "owner", "due_date", "status", "remarks"]].rename(columns={
            "partner_name": "Partner", "action_item": "Action", "owner": "Owner",
            "due_date": "Due Date", "status": "Status", "remarks": "Remarks",
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
        if show["overdue"].any():
            st.error(f"⚠️ {int(show['overdue'].sum())} action item(s) are overdue.")


# ===========================================================================
# SECTION 10 — DOWNLOAD / REPORTS
# ===========================================================================
elif section.startswith("10."):
    st.subheader("Download / Reports")
    st.caption("Export the current filtered view (Partner/RM/Cluster/Region + Period) as CSV.")

    exports = {
        "Partner Summary (KPIs)": pd.DataFrame([kpis]),
        "Target vs Achievement": target_summary,
        "Product Performance": txns_month.groupby("product_category")["amount"].sum().reset_index(),
        "Client List": clients,
        "Client Opportunities (SIP)": calc.sip_opportunity(clients, txns_all_time),
        "Review Summary": reviews,
    }

    for label, df in exports.items():
        col1, col2 = st.columns([3, 1])
        col1.write(f"**{label}** — {len(df)} rows")
        col2.download_button(
            "Download CSV", df.to_csv(index=False).encode("utf-8"),
            file_name=f"{label.lower().replace(' ', '_').replace('(', '').replace(')', '')}.csv",
            mime="text/csv", key=label,
        )

    st.info("Excel (multi-sheet) and PDF export can be added with openpyxl / xlsxwriter and reportlab once "
            "the report layouts are finalized with the business team — see README Phase 3+.")


st.markdown("---")
st.caption("Partner 360 Dashboard · Phase 1 Prototype · Data shown is randomly generated dummy data, not real business figures.")
