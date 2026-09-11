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
import calendar
import os

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from data_layer import get_all_data, TODAY as DEMO_TODAY
from formatting import format_inr, format_count, format_pct, status_from_achievement, STATUS_COLOR
import calculations as calc
import excel_loader
import consolidate
import report_export
from income_projection import ProjectionInputs, CrossSellAssumption, simulate, milestone_years

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
    "Source", [
        "Sample Data (demo)", "Upload Daily Excel", "Auto-load from folder",
        "Load Processed Data (Consolidated)",
    ],
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

elif source_mode == "Auto-load from folder":
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

else:  # Load Processed Data (Consolidated) — for the 120-RM pipeline
    processed_folder = st.sidebar.text_input(
        "Processed data folder", value="./processed_data",
        help="Output of consolidate.py — run that script against your Central Data Folder first.",
    )
    data, run_report, err = consolidate.load_processed(processed_folder)
    if err:
        st.error(err)
        st.caption("Run this from the project folder, on a server that can see your Central Data Folder:\n\n"
                   "`python consolidate.py --raw-folder ./raw_data --out-folder ./processed_data`")
        st.stop()
    TODAY = date.today()
    if run_report:
        st.sidebar.success(f"Consolidated {run_report['row_counts']['transaction_fact']:,} transactions "
                            f"from {len(run_report['files_ok'])} file(s) — {run_report['run_at']}")
        if run_report["files_failed"]:
            with st.sidebar.expander(f"⚠️ {len(run_report['files_failed'])} file(s) skipped"):
                for f in run_report["files_failed"]:
                    st.write(f"**{f['file']}**: {f['error']}")

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
        "9. Review History",
        "10. Income Calculator",
        "11. Target Projection",
        "12. Final Target Submission",
        "13. Action Tracker",
        "14. Download / Reports",
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

    open_reviews = reviews[reviews["status"].isin(["Open", "In Progress"])] if not reviews.empty else reviews
    if open_reviews.empty:
        st.info("No open review items for this selection.")
    else:
        show = open_reviews.merge(partner_master[["partner_id", "partner_name"]], on="partner_id", how="left")
        st.caption(f"{len(show)} open item(s) in scope")
        st.dataframe(
            show[["partner_name", "review_date", "problem_discussed", "approach", "status"]]
            .rename(columns={
                "partner_name": "Partner", "review_date": "Review Date",
                "problem_discussed": "Problem Discussed", "approach": "Approach / Way Forward",
                "status": "Status",
            }),
            use_container_width=True, hide_index=True,
        )
    st.caption("For the full history of past reviews, see the **Review History** section.")

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
# SECTION 9 — REVIEW HISTORY
# ===========================================================================
elif section.startswith("9."):
    st.subheader("Review History")

    if reviews.empty:
        st.info("No review history for this selection.")
    else:
        show = reviews.merge(partner_master[["partner_id", "partner_name"]], on="partner_id", how="left").copy()
        show["review_date"] = pd.to_datetime(show["review_date"])

        colf1, colf2 = st.columns(2)
        status_filter = colf1.multiselect("Filter by status", sorted(show["status"].unique().tolist()))
        date_range = colf2.date_input("Filter by review date range", value=())

        filtered = show.copy()
        if status_filter:
            filtered = filtered[filtered["status"].isin(status_filter)]
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start, end = date_range
            filtered = filtered[(filtered["review_date"].dt.date >= start) & (filtered["review_date"].dt.date <= end)]

        filtered = filtered.sort_values("review_date", ascending=False)
        st.caption(f"{len(filtered)} of {len(show)} review(s) shown, most recent first")

        for _, r in filtered.iterrows():
            with st.expander(f"{r['review_date'].strftime('%d %b %Y')} — {r['partner_name']} — {r['problem_discussed']} ({r['status']})"):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Approach / Way Forward:** {r['approach']}")
                c1.markdown(f"**Action Item:** {r['action_item']}")
                c2.markdown(f"**Owner:** {r['owner']}")
                c2.markdown(f"**Due Date:** {r['due_date']}")
                if r.get("remarks"):
                    st.markdown(f"**Remarks:** {r['remarks']}")


# ===========================================================================
# SECTION 10 — INCOME CALCULATOR
# ===========================================================================
elif section.startswith("10."):
    st.subheader("Partner Income Calculator")
    st.caption("A long-horizon business-planning tool: project trail income and AUM growth from a client-acquisition "
               "pace and SIP/lumpsum assumptions — independent of actual transaction data. Configure your real "
               "payout/commission structure with Finance before sharing externally; the defaults below are illustrative.")

    if st.button("↺ Reset to defaults", key="income_calc_reset"):
        for k in list(st.session_state.keys()):
            if k.startswith("ic_"):
                del st.session_state[k]
        st.rerun()

    col_inputs, col_results = st.columns([1, 2.6])

    with col_inputs:
        st.markdown("**Your Book**")
        starting_clients = st.number_input("Starting Clients", min_value=0, value=0, step=1, key="ic_start_clients")
        starting_aum_cr = st.number_input("Starting AUM (₹ Cr)", min_value=0.0, value=0.0, step=1.0, key="ic_start_aum")
        new_clients_pm = st.number_input("New Clients / Month", min_value=0, value=5, step=1, key="ic_new_clients")
        sip_per_client = st.number_input("SIP / Client / Month (₹)", min_value=0, value=5000, step=500, key="ic_sip_amt")
        sip_stepup = st.number_input("SIP Step-up % p.a.", min_value=0.0, value=1.0, step=0.5, key="ic_sip_stepup")
        lumpsum_amt = st.number_input("Annual Lumpsum / Client (₹)", min_value=0, value=10000, step=1000, key="ic_lumpsum")
        lumpsum_stepup = st.number_input("Lumpsum Step-up % p.a.", min_value=0.0, value=0.0, step=0.5, key="ic_lumpsum_stepup")
        redemption_pct = st.number_input("Annual Redemption %", min_value=0.0, value=5.0, step=0.5, key="ic_redemption")
        active_years = st.number_input("Active Years (effort)", min_value=1, max_value=40, value=25, step=1, key="ic_years")

        st.markdown("**Assumptions**")
        trail_rate = st.number_input("Trail Rate % p.a.", min_value=0.0, value=0.7, step=0.1, key="ic_trail")
        market_cagr = st.number_input("Market CAGR % p.a.", min_value=0.0, value=12.0, step=0.5, key="ic_cagr")

        st.markdown("**Cross-Sell Income** *(toggle to add)*")
        life_on = st.toggle("Life Insurance — 40% commission", key="ic_life_on")
        health_on = st.toggle("Health Insurance — 30% commission", key="ic_health_on")
        pms_on = st.toggle("PMS — 1% commission", key="ic_pms_on")
        demat_on = st.toggle("Demat & Broking — ₹210/client/mo", key="ic_demat_on")

    inputs = ProjectionInputs(
        starting_clients=starting_clients,
        starting_aum=starting_aum_cr * 1_00_00_000,
        new_clients_per_month=new_clients_pm,
        sip_per_client_month=sip_per_client,
        sip_stepup_pct=sip_stepup,
        annual_lumpsum_per_client=lumpsum_amt,
        lumpsum_stepup_pct=lumpsum_stepup,
        annual_redemption_pct=redemption_pct,
        active_years=int(active_years),
        trail_rate_pct=trail_rate,
        market_cagr_pct=market_cagr,
        life=CrossSellAssumption(enabled=life_on, commission_pct=40, rate=10),
        health=CrossSellAssumption(enabled=health_on, commission_pct=30, rate=15),
        pms=CrossSellAssumption(enabled=pms_on, commission_pct=1, rate=5),
        demat=CrossSellAssumption(enabled=demat_on, rate=210),
    )
    projection = simulate(inputs)
    milestones = milestone_years(int(active_years))

    with col_results:
        highlight_year = st.selectbox("Highlight year", milestones, index=min(3, len(milestones) - 1))
        hy = projection[highlight_year - 1]
        y5 = projection[min(5, len(projection)) - 1]
        y_last = projection[-1]

        st.markdown(f"""
        <div class='insight-card'>🎯 By <b>Year {highlight_year}</b>, projected annual income is
        <b>{format_inr(hy['total_income'])}</b> ({format_inr(hy['total_income']/12)}/mo) —
        roughly a <b>{format_inr(hy['total_income'])} p.a.</b> equivalent.
        <span style='float:right;color:#6b7280'>Year {min(5,len(projection))}: {format_inr(y5['total_income'])}/yr ·
        Year {y_last['year']}: {format_inr(y_last['total_income'])}/yr</span></div>
        """, unsafe_allow_html=True)

        st.markdown(f"**{active_years}-Year Income Projections** — {len(milestones)} milestones")
        table_rows = []
        for y in milestones:
            r = projection[y - 1]
            table_rows.append({
                "Year": y, "Clients": format_count(r["clients"]),
                "SIP Contrib.": format_inr(r["sip_contrib"]),
                "Step-up Inflows": format_inr(r["stepup_inflow"]) if r["stepup_inflow"] else "—",
                "Lumpsum / Yr": format_inr(r["lumpsum"]),
                "Mkt. Gains": format_inr(r["mkt_gains"]),
                "Total AUM": format_inr(r["total_aum"]),
                "SIP Book /Mo": format_inr(r["sip_book_mo"]),
                "Trail / Yr": format_inr(r["trail_yr"]),
                "Cross-sell / Yr": format_inr(r["cross_sell_total"]) if r["cross_sell_total"] else "—",
                "Demat / Yr": format_inr(r["demat_yr"]) if r["demat_yr"] else "—",
                "Total Income": format_inr(r["total_income"]),
                "Uplift": format_pct(r["uplift_pct"]) if r["uplift_pct"] is not None else "—",
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
        st.caption(f"Illustrative projections. Actual returns depend on market conditions and client activity. "
                   f"Trail: {trail_rate}% p.a. · Market CAGR: {market_cagr}% · "
                   f"Cross-sell: Life 40% · Health 30% · PMS 1% (of AUM) · Demat ₹210/active client/mo.")

    st.markdown("---")
    chart_years = [r["year"] for r in projection]
    c1, c2, c3 = st.columns(3)
    with c1:
        fig = go.Figure()
        fig.add_bar(x=chart_years, y=[r["trail_yr"] for r in projection], name="Trail")
        fig.add_bar(x=chart_years, y=[r["cross_sell_total"] for r in projection], name="Cross-Sell")
        fig.add_bar(x=chart_years, y=[r["demat_yr"] for r in projection], name="Demat")
        fig.update_layout(barmode="stack", title="Total Income Growth")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = go.Figure()
        fig.add_bar(x=chart_years, y=[r["fresh_investment_cum"] for r in projection], name="Fresh Investment")
        fig.add_bar(x=chart_years, y=[r["market_gains_cum"] for r in projection], name="Market Appreciation")
        fig.update_layout(barmode="stack", title="AUM Composition")
        st.plotly_chart(fig, use_container_width=True)
    with c3:
        fig = go.Figure()
        totals = [max(r["total_income"], 1) for r in projection]
        fig.add_bar(x=chart_years, y=[100 * r["trail_yr"] / t for r, t in zip(projection, totals)], name="Trail")
        fig.add_bar(x=chart_years, y=[100 * r["cross_sell_total"] / t for r, t in zip(projection, totals)], name="Cross-sell")
        fig.add_bar(x=chart_years, y=[100 * r["demat_yr"] / t for r, t in zip(projection, totals)], name="Demat")
        fig.update_layout(barmode="stack", title="Income Mix %", yaxis_range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)


# ===========================================================================
# SECTION 11 — TARGET PROJECTION (what-if, current period)
# ===========================================================================
elif section.startswith("11."):
    st.subheader("Target Projection")
    st.caption(f"What-if calculator for {month_sel} {year_sel}: enter an assumed run-rate for the rest of the "
               f"period and see the projected achievement — separate from the Income Calculator's long-horizon view.")

    days_in_month = calendar.monthrange(period_start.year, period_start.month)[1]
    as_of_day = TODAY.day if (period_start.year, period_start.month) == (TODAY.year, TODAY.month) else days_in_month
    days_elapsed = min(as_of_day, days_in_month)
    days_remaining = days_in_month - days_elapsed
    st.caption(f"{days_elapsed} day(s) elapsed, {days_remaining} day(s) remaining in the period.")

    for _, row in target_summary.iterrows():
        metric, target_val, actual_val = row["Metric"], row["Target"], row["Actual"]
        current_daily_rate = actual_val / days_elapsed if days_elapsed else 0
        with st.expander(f"{metric} — current MTD: {format_count(actual_val) if metric == 'New Clients' else format_inr(actual_val)}", expanded=(metric == "Sales")):
            c1, c2 = st.columns([1, 2])
            with c1:
                assumed_rate = st.number_input(
                    f"Assumed daily rate for remaining {days_remaining} day(s)",
                    min_value=0.0, value=float(round(current_daily_rate, 2)),
                    key=f"proj_rate_{metric}",
                    help="Defaults to the current run-rate — adjust to model a faster or slower finish.",
                )
            projected_total = actual_val + assumed_rate * days_remaining
            proj_ach = calc.achievement_pct(projected_total, target_val)
            proj_gap = calc.gap(projected_total, target_val)
            fmt = format_count if metric == "New Clients" else format_inr
            with c2:
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Projected Total", fmt(projected_total))
                cc2.metric("Projected Achievement", format_pct(proj_ach) if proj_ach is not None else "—")
                cc3.metric("Projected Gap", fmt(proj_gap) if proj_gap is not None else "—")
                if proj_ach is not None:
                    st.progress(min(int(proj_ach), 100), text=status_from_achievement(proj_ach))


# ===========================================================================
# SECTION 12 — FINAL TARGET SUBMISSION
# ===========================================================================
elif section.startswith("12."):
    st.subheader("Final Target Submission")
    st.caption(f"Submit {month_sel} {year_sel} targets for {header_name}. Submissions save for this session and can "
               f"be edited again later — nothing is locked. Wire this to a persisted store (DB / Google Sheet) in "
               f"Phase 3 so submissions survive across sessions; for now, download the CSV below to hand off.")

    if "submitted_targets" not in st.session_state:
        st.session_state.submitted_targets = {}

    with st.form("final_target_form"):
        cols = st.columns(4)
        sales_t = cols[0].number_input("Sales Target (₹)", min_value=0.0, value=float(
            targets_month.loc[targets_month["target_type"] == "Sales", "target_value"].sum()), step=100000.0)
        sip_t = cols[1].number_input("SIP Target (₹)", min_value=0.0, value=float(
            targets_month.loc[targets_month["target_type"] == "SIP", "target_value"].sum()), step=10000.0)
        insurance_t = cols[2].number_input("Insurance Target (₹)", min_value=0.0, value=float(
            targets_month.loc[targets_month["target_type"] == "Insurance", "target_value"].sum()), step=10000.0)
        new_clients_t = cols[3].number_input("New Clients Target", min_value=0, value=int(
            targets_month.loc[targets_month["target_type"] == "New Clients", "target_value"].sum()), step=1)
        submit = st.form_submit_button("Submit Final Target")
        if submit:
            st.session_state.submitted_targets[(header_name, month_sel, year_sel)] = {
                "Sales": sales_t, "SIP": sip_t, "Insurance": insurance_t, "New Clients": new_clients_t,
                "submitted_at": pd.Timestamp.now(),
            }
            st.success(f"Target submitted for {header_name} — {month_sel} {year_sel}. You can resubmit anytime to update it.")

    key = (header_name, month_sel, year_sel)
    if key in st.session_state.submitted_targets:
        st.markdown("---")
        st.markdown("**Currently submitted (this session)**")
        sub = st.session_state.submitted_targets[key]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sales", format_inr(sub["Sales"]))
        c2.metric("SIP", format_inr(sub["SIP"]))
        c3.metric("Insurance", format_inr(sub["Insurance"]))
        c4.metric("New Clients", format_count(sub["New Clients"]))
        sub_df = pd.DataFrame([{**{k: v for k, v in sub.items() if k != "submitted_at"},
                                 "Partner": header_name, "Period": f"{month_sel} {year_sel}"}])
        st.download_button("Download as CSV", sub_df.to_csv(index=False).encode("utf-8"),
                            file_name="final_target_submission.csv", mime="text/csv")


# ===========================================================================
# SECTION 13 — ACTION TRACKER
# ===========================================================================
elif section.startswith("13."):
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

        table = show[["partner_name", "action_item", "owner", "due_date", "status", "remarks"]].rename(columns={
            "partner_name": "Partner", "action_item": "Action", "owner": "Owner",
            "due_date": "Due Date", "status": "Status", "remarks": "Remarks",
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
        if show["overdue"].any():
            st.error(f"⚠️ {int(show['overdue'].sum())} action item(s) are overdue.")


# ===========================================================================
# SECTION 14 — DOWNLOAD / REPORTS
# ===========================================================================
elif section.startswith("14."):
    st.subheader("Download / Reports")
    st.caption("Export the current filtered view (Partner/RM/Cluster/Region + Period).")

    opps = {
        "SIP Opportunity": calc.sip_opportunity(clients, txns_all_time),
        "Cross-sell Opportunity": calc.cross_sell_opportunity(clients, txns_all_time, "Mutual Funds", "Insurance"),
        "Dormant Clients": calc.dormant_opportunity(clients),
        "High-Value Low-Pen": calc.high_value_low_penetration(clients, txns_all_time),
    }
    insights_for_pdf = calc.generate_insights(kpis, target_summary, {
        "sip_opp": opps["SIP Opportunity"], "cross_sell": opps["Cross-sell Opportunity"],
        "dormant": opps["Dormant Clients"], "high_value": opps["High-Value Low-Pen"],
    }, calc.growth_pct(kpis["aum"], kpis_prev["aum"]))

    st.markdown("**Combined reports**")
    rc1, rc2 = st.columns(2)
    excel_bytes = report_export.build_excel_report(
        header_name, f"{month_sel} {year_sel}", kpis, target_summary,
        txns_month.groupby("product_category")["amount"].sum().reset_index(), clients, opps, reviews,
    )
    rc1.download_button("📊 Download Excel Report (multi-sheet)", excel_bytes,
                         file_name=f"partner360_report_{month_sel}_{year_sel}.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    pdf_bytes = report_export.build_pdf_report(header_name, f"{month_sel} {year_sel}", kpis, target_summary, insights_for_pdf)
    rc2.download_button("📄 Download PDF Summary", pdf_bytes,
                         file_name=f"partner360_summary_{month_sel}_{year_sel}.pdf", mime="application/pdf")

    st.markdown("---")
    st.markdown("**Individual CSVs**")
    exports = {
        "Partner Summary (KPIs)": pd.DataFrame([kpis]),
        "Target vs Achievement": target_summary,
        "Product Performance": txns_month.groupby("product_category")["amount"].sum().reset_index(),
        "Client List": clients,
        **opps,
        "Review History": reviews,
    }
    for label, df in exports.items():
        col1, col2 = st.columns([3, 1])
        col1.write(f"**{label}** — {len(df)} rows")
        col2.download_button(
            "CSV", df.to_csv(index=False).encode("utf-8"),
            file_name=f"{label.lower().replace(' ', '_').replace('(', '').replace(')', '')}.csv",
            mime="text/csv", key=label,
        )
st.markdown("---")
st.caption("Partner 360 Dashboard · Phase 1 Prototype · Data shown is randomly generated dummy data, not real business figures.")
