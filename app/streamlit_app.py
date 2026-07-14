"""Look up your local A&E — engagement app.

Type a town or trust name, get its performance vs the national picture and
its 8-week forecast. Reads only warehouse artefacts (never runs the
pipeline). Run with:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from nhswp import config  # noqa: E402

st.set_page_config(page_title="Look up your local A&E", page_icon="🏥", layout="wide")


@st.cache_resource
def connection():
    return duckdb.connect(str(config.WAREHOUSE_DB), read_only=True)


@st.cache_data
def load_orgs() -> pd.DataFrame:
    return connection().execute(
        """
        SELECT o.org_code, o.org_name, o.icb_name, o.region_name, o.postcode,
               c.catchment_population, c.imd_score
        FROM dim_org o
        LEFT JOIN dim_trust_catchment c USING (org_code)
        WHERE o.is_type1_provider
        ORDER BY o.org_name
        """
    ).df()


@st.cache_data
def national_series() -> pd.DataFrame:
    return connection().execute(
        """
        SELECT month_key, make_date(month_key//100, month_key%100, 1) AS month_start,
               1.0 - SUM(over4hr_type1)::DOUBLE / NULLIF(SUM(att_type1),0) AS performance
        FROM vw_kpi_ae_monthly GROUP BY month_key ORDER BY month_key
        """
    ).df()


@st.cache_data
def trust_series(org_code: str) -> pd.DataFrame:
    return connection().execute(
        """
        SELECT month_key, month_start, att_type1, type1_performance, dta_12hr_plus
        FROM vw_kpi_ae_monthly WHERE org_code = ? ORDER BY month_key
        """,
        [org_code],
    ).df()


@st.cache_data
def trust_forecast(org_code: str) -> pd.DataFrame:
    con = connection()
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "fact_forecast" not in tables:
        return pd.DataFrame()
    return con.execute(
        """
        SELECT target_month_key,
               make_date(target_month_key//100, target_month_key%100, 1) AS month_start,
               metric, point, lo80, hi80, horizon, is_validated_horizon
        FROM fact_forecast WHERE org_code = ? ORDER BY metric, horizon
        """,
        [org_code],
    ).df()


st.title("🏥 Look up your local A&E")
st.caption(
    "Trust-level winter pressure intelligence built on NHS England's monthly "
    "published statistics (A&E, RTT, ambulance) joined to deprivation and weather. "
    "Educational portfolio project — not an official NHS product."
)

orgs = load_orgs()
query = st.text_input("Search by trust name or town", placeholder="e.g. Leeds, Barts, Cornwall…")

if query and len(query) >= 2:
    mask = orgs["org_name"].str.contains(query, case=False, na=False) | orgs[
        "icb_name"
    ].fillna("").str.contains(query, case=False)
    hits = orgs[mask]
    if hits.empty:
        st.warning("No Type-1 acute trust matched. Try part of the trust name (e.g. 'Manchester').")
        st.stop()
    labels = hits["org_name"] + "  (" + hits["org_code"] + ")"
    choice = st.selectbox("Matching trusts", labels.tolist())
    org_code = choice.rsplit("(", 1)[1].rstrip(")")
    org = hits[hits["org_code"] == org_code].iloc[0]

    ts = trust_series(org_code)
    nat = national_series()
    latest = ts.dropna(subset=["type1_performance"]).iloc[-1]
    nat_latest = nat.iloc[-1]

    st.subheader(org["org_name"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Type-1 4-hour performance",
        f"{latest['type1_performance']:.1%}",
        f"{(latest['type1_performance'] - nat_latest['performance']) * 100:+.1f} pp vs England",
    )
    c2.metric("Type-1 attendances (month)", f"{int(latest['att_type1']):,}")
    c3.metric("12-hour DTA waits (month)", f"{int(latest['dta_12hr_plus']):,}")
    rag = ("🟢 GREEN" if latest["type1_performance"] >= 0.78
           else "🟠 AMBER" if latest["type1_performance"] >= 0.70 else "🔴 RED")
    c4.metric("RAG (vs 78% interim ambition)", rag)

    fig = go.Figure()
    fig.add_scatter(x=ts["month_start"], y=ts["type1_performance"],
                    name=org["org_name"], mode="lines", line=dict(width=2.2))
    fig.add_scatter(x=nat["month_start"], y=nat["performance"],
                    name="England", mode="lines", line=dict(width=1.2, dash="dot"))

    fc = trust_forecast(org_code)
    if not fc.empty:
        rate = fc[fc["metric"] == "breach_rate"].copy()
        rate["perf"] = 1 - rate["point"]
        rate["perf_lo"] = 1 - rate["hi80"]
        rate["perf_hi"] = 1 - rate["lo80"]
        validated = rate[rate["is_validated_horizon"]]
        outlook = rate[~rate["is_validated_horizon"]]
        for seg, name, alpha in [(validated, "8-week forecast (validated)", 0.25),
                                 (outlook, "winter outlook (indicative)", 0.12)]:
            if seg.empty:
                continue
            fig.add_scatter(x=seg["month_start"], y=seg["perf"], name=name,
                            mode="lines+markers", line=dict(dash="dash"))
            fig.add_scatter(x=pd.concat([seg["month_start"], seg["month_start"][::-1]]),
                            y=pd.concat([seg["perf_hi"], seg["perf_lo"][::-1]]),
                            fill="toself", fillcolor=f"rgba(31,111,180,{alpha})",
                            line=dict(width=0), name=f"{name} 80% band", showlegend=False)
    fig.add_hline(y=0.95, line_dash="dash", line_color="green",
                  annotation_text="95% standard")
    fig.add_hline(y=0.78, line_dash="dash", line_color="orange",
                  annotation_text="78% interim ambition")
    fig.update_layout(
        yaxis_tickformat=".0%", height=460, margin=dict(t=30, b=10),
        legend=dict(orientation="h", y=-0.15),
        yaxis_title="Type-1 4-hour performance",
    )
    st.plotly_chart(fig, use_container_width=True)

    if fc.empty:
        st.info("Forecast tables not present yet — run the forecast stage, rebuild the "
                "warehouse, and refresh.")
    else:
        st.caption(
            "Bands are honest 80% intervals from backtested residuals (see "
            "reports/forecast-evaluation.md); the winter outlook beyond 2 months is "
            "indicative and deliberately wider."
        )

    with st.expander("About this trust's context"):
        st.write({
            "ICB": org["icb_name"],
            "Region": org["region_name"],
            "Catchment population (OHID 2026 est.)":
                None if pd.isna(org["catchment_population"]) else f"{int(org['catchment_population']):,}",
            "Catchment IMD score (higher = more deprived)":
                None if pd.isna(org["imd_score"]) else round(float(org["imd_score"]), 1),
        })
else:
    st.info("Start typing a town or trust name above — e.g. “Leeds”, “Barts”, “Cornwall”.")
    nat = national_series()
    fig = go.Figure()
    fig.add_scatter(x=nat["month_start"], y=nat["performance"], mode="lines",
                    name="England Type-1 performance")
    fig.add_hline(y=0.95, line_dash="dash", line_color="green")
    fig.add_hline(y=0.78, line_dash="dash", line_color="orange")
    fig.update_layout(yaxis_tickformat=".0%", height=380, margin=dict(t=20, b=10),
                      yaxis_title="Type-1 4-hour performance")
    st.plotly_chart(fig, use_container_width=True)
