"""Analysis stage: league table, funnel plot, equity view, winter deltas,
national trend. Reads the warehouse, writes outputs/ + figures/.

The funnel plot is the deliberate answer to "is a raw ranking fair to a major
trauma centre?" — a raw league table is shipped, but next to a Spiegelhalter
funnel with 95% and 99.8% binomial control limits, and comparisons default to
within-cluster peers. True case-mix adjustment is impossible from public
aggregates; that limitation is stated rather than faked.
"""
from __future__ import annotations

import json

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .. import config


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(config.WAREHOUSE_DB), read_only=True)


def league_table(con) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT org_code, org_name, icb_name, region_name, month_key,
               att_type1, type1_performance, alltype_performance,
               dta_12hr_plus, momentum_3m_pp, rag,
               type1_meets_95, type1_meets_interim
        FROM vw_trust_latest
        ORDER BY type1_performance ASC
        """
    ).df()
    df.to_csv(config.OUTPUTS_DIR / "league_table.csv", index=False)
    return df


def funnel_plot(con) -> None:
    df = con.execute(
        """
        SELECT org_code, org_name, att_type1_12m AS n,
               1.0 - type1_performance_12m AS breach_rate
        FROM vw_equity WHERE att_type1_12m > 0
        """
    ).df()
    p_bar = (df["breach_rate"] * df["n"]).sum() / df["n"].sum()

    fig, ax = plt.subplots(figsize=(10, 6.5))
    ns = np.linspace(df["n"].min() * 0.9, df["n"].max() * 1.05, 400)
    for z, style, label in [(1.96, "--", "95% limits"), (3.09, ":", "99.8% limits")]:
        se = np.sqrt(p_bar * (1 - p_bar) / ns)
        ax.plot(ns, p_bar + z * se, style, color="grey", lw=1, label=label)
        ax.plot(ns, np.clip(p_bar - z * se, 0, None), style, color="grey", lw=1)
    ax.axhline(p_bar, color="black", lw=1, label=f"national mean ({p_bar:.1%})")
    ax.scatter(df["n"], df["breach_rate"], s=18, alpha=0.6, color="#1f6fb4")
    ax.set_xlabel("Type-1 attendances (last 12 months)")
    ax.set_ylabel("4-hour breach rate")
    ax.set_title("Funnel plot: breach rate vs volume — a fair alternative to a raw ranking")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(config.FIGURES_DIR / "funnel_plot.png", dpi=150)
    plt.close(fig)


def equity_scatter(con) -> dict:
    df = con.execute(
        """
        SELECT org_code, org_name, imd_score, deprivation_quintile, core20_proxy,
               type1_performance_12m
        FROM vw_equity
        WHERE imd_score IS NOT NULL AND type1_performance_12m IS NOT NULL
        """
    ).df()
    r = float(np.corrcoef(df["imd_score"], df["type1_performance_12m"])[0, 1])
    n = len(df)
    z = np.arctanh(r)
    se = 1 / np.sqrt(n - 3)
    ci = (float(np.tanh(z - 1.96 * se)), float(np.tanh(z + 1.96 * se)))

    fig, ax = plt.subplots(figsize=(10, 6.5))
    colors = np.where(df["core20_proxy"], "#c23b22", "#1f6fb4")
    ax.scatter(df["imd_score"], df["type1_performance_12m"], s=22, alpha=0.7, c=colors)
    coef = np.polyfit(df["imd_score"], df["type1_performance_12m"], 1)
    xs = np.linspace(df["imd_score"].min(), df["imd_score"].max(), 50)
    ax.plot(xs, np.polyval(coef, xs), color="black", lw=1)
    ax.set_xlabel("Catchment-weighted IMD score (higher = more deprived catchment)")
    ax.set_ylabel("Type-1 4-hour performance (last 12 months)")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title(
        f"Deprivation vs performance — r = {r:.2f} (95% CI {ci[0]:.2f} to {ci[1]:.2f})\n"
        "red = most-deprived quintile of catchments (Core20 proxy); "
        "ecological association, not a causal claim"
    )
    fig.tight_layout()
    fig.savefig(config.FIGURES_DIR / "equity_scatter.png", dpi=150)
    plt.close(fig)
    return {"pearson_r": r, "ci95": ci, "n_trusts": n}


def winter_delta_chart(con) -> pd.DataFrame:
    df = con.execute(
        """
        SELECT winter_label, winter_delta_pp
        FROM vw_kpi_winter_delta
        WHERE winter_delta_pp IS NOT NULL AND abs(winter_delta_pp) < 0.5
        """
    ).df()
    order = sorted(df["winter_label"].unique())
    fig, ax = plt.subplots(figsize=(10, 6))
    data = [df.loc[df["winter_label"] == w, "winter_delta_pp"] * 100 for w in order]
    ax.boxplot(data, tick_labels=order, showfliers=False)
    ax.axhline(0, color="grey", lw=1)
    ax.set_ylabel("Winter minus preceding summer, Type-1 performance (pp)")
    ax.set_title("Winter penalty by trust and winter (Dec-Feb vs preceding Jun-Aug)")
    fig.tight_layout()
    fig.savefig(config.FIGURES_DIR / "winter_delta.png", dpi=150)
    plt.close(fig)
    summary = df.groupby("winter_label")["winter_delta_pp"].describe()
    summary.to_csv(config.OUTPUTS_DIR / "winter_delta_summary.csv")
    return df


def national_trend(con) -> dict:
    df = con.execute(
        """
        SELECT month_key, make_date(month_key//100, month_key%100, 1) AS month_start,
               SUM(over4hr_type1)::DOUBLE / NULLIF(SUM(att_type1),0) AS breach_rate,
               SUM(att_type1) AS att
        FROM vw_kpi_ae_monthly
        GROUP BY month_key ORDER BY month_key
        """
    ).df()
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(df["month_start"], 1 - df["breach_rate"], color="#1f6fb4", lw=1.8)
    ax.axhline(0.95, color="green", ls="--", lw=1, label="95% constitutional standard")
    ax.axhline(0.78, color="orange", ls="--", lw=1, label="78% interim ambition (2025/26)")
    break_date = pd.Timestamp(f"{config.ECDS_BREAK_MONTH}-01")
    ax.axvline(break_date, color="red", ls=":", lw=1.2)
    ax.annotate("ECDS methodology change", xy=(break_date, ax.get_ylim()[0]),
                xytext=(5, 12), textcoords="offset points", fontsize=8, color="red")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("England Type-1 A&E 4-hour performance (trust-sum national series)")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(config.FIGURES_DIR / "national_trend.png", dpi=150)
    plt.close(fig)
    latest = df.iloc[-1]
    return {
        "latest_month": int(latest["month_key"]),
        "latest_type1_performance": float(1 - latest["breach_rate"]),
        "latest_att_type1": int(latest["att"]),
    }


def rtt_position(con) -> dict:
    df = con.execute(
        """
        SELECT month_key,
               SUM(total_incomplete) AS waiting,
               SUM(within_18wk)::DOUBLE / NULLIF(SUM(total_incomplete),0) AS pct18
        FROM vw_kpi_rtt_monthly GROUP BY month_key ORDER BY month_key
        """
    ).df()
    latest = df.iloc[-1]
    return {
        "rtt_latest_month": int(latest["month_key"]),
        "rtt_waiting_list": float(latest["waiting"]),
        "rtt_pct_within_18wk": float(latest["pct18"]),
    }


def run() -> str:
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    con = _con()
    try:
        league = league_table(con)
        funnel_plot(con)
        equity = equity_scatter(con)
        winter_delta_chart(con)
        national = national_trend(con)
        rtt = rtt_position(con)
    finally:
        con.close()

    summary = {**national, **rtt, "equity": equity,
               "n_type1_trusts_ranked": int(len(league))}
    (config.OUTPUTS_DIR / "kpi_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return (
        f"league table {len(league)} trusts; national Type-1 perf "
        f"{national['latest_type1_performance']:.1%} ({national['latest_month']}); "
        f"equity r={equity['pearson_r']:.2f}"
    )
