"""Fusion extension — "Hospital Under Pressure".

Joins NHS workforce vacancy pressure (regional, ESR-derived WTE counts —
published without denominators, so an index vs each region's own window mean
is used rather than a fake rate) to regional A&E flow deterioration.

Grain honesty: vacancy statistics are region × staff group; no trust-level
join is fabricated. The analysis asks the question boards actually debate —
do months of elevated regional vacancy pressure coincide with (and precede)
worse regional 4-hour performance? Contemporaneous and 3-month-lagged
correlations are reported with the ecological caveat.
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


def run() -> str:
    con = duckdb.connect(str(config.WAREHOUSE_DB), read_only=True)
    try:
        perf = con.execute(
            """
            SELECT o.region_name, k.month_key,
                   SUM(k.over4hr_type1)::DOUBLE / NULLIF(SUM(k.att_type1),0) AS breach_rate
            FROM vw_kpi_ae_monthly k JOIN dim_org o USING (org_code)
            WHERE o.is_type1_provider AND o.region_name IS NOT NULL
            GROUP BY ALL
            """
        ).df()
        vac = con.execute(
            "SELECT region_name, month_key, vacancy_pressure_index, nursing_pressure_index "
            "FROM vw_vacancy_regional"
        ).df()
    finally:
        con.close()

    df = perf.merge(vac, on=["region_name", "month_key"], how="inner")
    if df.empty:
        raise ValueError("fusion join produced no rows — check region name alignment")

    # Two-way (region + month) demeaning: a one-way within-region estimator is
    # confounded by the shared national time path (vacancies fell over the
    # window while breach rates rose, producing a spurious negative sign).
    # Removing month fixed effects isolates region-month deviations from both
    # the region's own level and the national month.
    def two_way_demean(col: str) -> pd.Series:
        region_mean = df.groupby("region_name")[col].transform("mean")
        month_mean = df.groupby("month_key")[col].transform("mean")
        return df[col] - region_mean - month_mean + df[col].mean()

    df["breach_dm"] = two_way_demean("breach_rate")
    df["nurse_dm"] = two_way_demean("nursing_pressure_index")

    r_now = float(np.corrcoef(df["nurse_dm"], df["breach_dm"])[0, 1])

    lag = df.sort_values(["region_name", "month_key"]).copy()
    lag["nurse_dm_lag3"] = lag.groupby("region_name")["nurse_dm"].shift(3)
    lag_valid = lag.dropna(subset=["nurse_dm_lag3"])
    r_lag3 = float(np.corrcoef(lag_valid["nurse_dm_lag3"], lag_valid["breach_dm"])[0, 1])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, (xcol, title, r) in zip(axes, [
        ("nurse_dm", f"Same month (r = {r_now:.2f})", r_now),
        ("nurse_dm_lag3", f"Vacancy 3 months earlier (r = {r_lag3:.2f})", r_lag3),
    ]):
        data = df if xcol == "nurse_dm" else lag_valid
        ax.scatter(data[xcol], data["breach_dm"] * 100, s=10, alpha=0.4, color="#1f6fb4")
        coef = np.polyfit(data[xcol], data["breach_dm"] * 100, 1)
        xs = np.linspace(data[xcol].min(), data[xcol].max(), 50)
        ax.plot(xs, np.polyval(coef, xs), color="black", lw=1)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Nursing vacancy pressure (index, within-region demeaned)")
    axes[0].set_ylabel("Type-1 breach rate deviation (pp)")
    fig.suptitle(
        "Hospital Under Pressure: regional nursing vacancy pressure vs A&E breach rate\n"
        "(two-way demeaned: region + month fixed effects; ecological association; "
        "vacancy WTE counts, not rates)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(config.FIGURES_DIR / "fusion_vacancy_pressure.png", dpi=150)
    plt.close(fig)

    df.to_csv(config.OUTPUTS_DIR / "fusion_region_month.csv", index=False)
    out = {
        "within_region_corr_same_month": r_now,
        "within_region_corr_lag3": r_lag3,
        "n_region_months": int(len(df)),
    }
    (config.OUTPUTS_DIR / "fusion_summary.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    return f"fusion: r(now)={r_now:.2f}, r(lag3)={r_lag3:.2f} over {len(df)} region-months"
