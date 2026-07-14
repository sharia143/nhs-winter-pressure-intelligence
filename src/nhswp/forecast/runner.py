"""Forecast stage orchestration.

Targets (Type-1 acute providers only):
- breach_rate — Type-1 4-hour breach rate, modelled on the logit scale
  (headline; guarantees forecasts stay in [0,1])
- att_per_day — Type-1 attendances per day, modelled on the log scale
  (days-in-month normalised so February's -10% day count doesn't pollute
  the seasonal shape)

12-hour DTA waits are deliberately NOT forecast: spiky, zero-inflated small
counts for which any interval would be dishonest. They are reported
descriptively in the KPI layer instead.

Outputs: outputs/model/{org_clusters,fact_forecast,backtest_metrics,
backtest_detail,interval_coverage}.parquet + reports/forecast-evaluation.md.
"""
from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd

from .. import config
from . import backtest, features, model

MIN_MONTHS = 36
MIN_MEAN_ATT = 1000.0  # attendances/month floor — excludes tiny/specialist units
VALIDATED_H = 2        # horizons backtested; beyond this intervals are indicative
OUTLOOK_H = 8          # extended winter outlook horizon


def _load_series() -> tuple[dict, dict, dict, int]:
    con = duckdb.connect(str(config.WAREHOUSE_DB), read_only=True)
    try:
        df = con.execute(
            """
            SELECT k.org_code, k.month_key, k.att_type1, k.over4hr_type1, k.days_in_month
            FROM vw_kpi_ae_monthly k
            JOIN dim_org o USING (org_code)
            WHERE o.is_type1_provider
            ORDER BY k.org_code, k.month_key
            """
        ).df()
        latest = int(con.execute("SELECT max(month_key) FROM vw_kpi_ae_monthly").fetchone()[0])
    finally:
        con.close()

    rate_series, count_series, volumes = {}, {}, {}
    for org, grp in df.groupby("org_code"):
        grp = grp.set_index("month_key").sort_index()
        att = grp["att_type1"].astype(float)
        if att.notna().sum() < MIN_MONTHS or att.mean() < MIN_MEAN_ATT:
            continue
        rate = (grp["over4hr_type1"] / att.replace(0, np.nan)).astype(float)
        per_day = (att / grp["days_in_month"]).astype(float)
        rate_series[org] = pd.Series(model.logit(rate.to_numpy()), index=grp.index)
        count_series[org] = pd.Series(model.log_tf(per_day.to_numpy()), index=grp.index)
        # Mask months where the underlying value was missing
        rate_series[org][rate.isna()] = np.nan
        count_series[org][per_day.isna()] = np.nan
        volumes[org] = float(att.mean())
    return rate_series, count_series, volumes, latest


def _final_forecast(
    series_by_org: dict[str, pd.Series],
    volumes: dict[str, float],
    latest: int,
    intervals: pd.DataFrame,
    metric: str,
    back_transform,
    break_key: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit on everything and forecast h=1..OUTLOOK_H. Returns (forecasts, clusters)."""
    adjusted = {
        o: model.relevel_history_for_break(s, break_key)[0] for o, s in series_by_org.items()
    }
    profiles = {o: features.seasonal_profile(s) for o, s in adjusted.items()}
    usable = {o for o, p in profiles.items() if p is not None}
    clusters, k = features.cluster_trusts(
        {o: profiles[o] for o in usable}, {o: volumes[o] for o in usable}
    )
    indices = features.pooled_seasonal_index({o: adjusted[o] for o in usable}, clusters)
    cluster_of = dict(zip(clusters["org_code"], clusters["cluster_id"]))
    iv = intervals.set_index(["cluster_id", "horizon"])

    rows = []
    horizons = list(range(1, OUTLOOK_H + 1))
    for org in sorted(usable):
        cid = cluster_of[org]
        fc = model.cluster_model_forecast(adjusted[org], indices[cid], latest, horizons)
        if fc is None:
            continue
        for h in horizons:
            raw_point = float(back_transform(np.array([fc[h]]))[0])
            iv_h = min(h, VALIDATED_H)  # residual pools exist for h<=2
            try:
                lo_off = iv.loc[(cid, iv_h), "lo"]
                med_off = iv.loc[(cid, iv_h), "med"]
                hi_off = iv.loc[(cid, iv_h), "hi"]
            except KeyError:
                lo_off, med_off, hi_off = np.nan, 0.0, np.nan
            inflate = np.sqrt(h / VALIDATED_H) if h > VALIDATED_H else 1.0
            # Debias the point by the cluster-median backtest residual (standard
            # empirical recalibration; keeps the point inside its own band since
            # lo <= med <= hi by construction).
            point = raw_point + (med_off if pd.notna(med_off) else 0.0)
            rows.append({
                "org_code": org,
                "metric": metric,
                "model": "cluster_pooled",
                "origin_month_key": latest,
                "horizon": h,
                "target_month_key": model.add_months(latest, h),
                "point": point,
                "point_raw": raw_point,
                "lo80": raw_point + (lo_off * inflate if pd.notna(lo_off) else np.nan),
                "hi80": raw_point + (hi_off * inflate if pd.notna(hi_off) else np.nan),
                "is_validated_horizon": h <= VALIDATED_H,
                "cluster_id": cid,
            })
    fdf = pd.DataFrame(rows)
    if metric == "breach_rate":  # keep rates in [0,1]
        for col in ("lo80", "hi80"):
            fdf[col] = fdf[col].clip(0.0, 1.0)
    else:  # counts >= 0
        for col in ("lo80", "hi80"):
            fdf[col] = fdf[col].clip(lower=0.0)
    return fdf, clusters


def run() -> str:
    np.random.seed(features.RANDOM_STATE)
    break_key = int(config.ECDS_BREAK_MONTH.replace("-", ""))
    rate_series, count_series, volumes, latest = _load_series()

    out_dir = config.OUTPUTS_DIR / "model"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_metrics, all_details, all_forecasts, all_coverage = [], [], [], []
    clusters_final = None

    for metric, series_by_org, back in [
        ("breach_rate", rate_series, model.inv_logit),
        ("att_per_day", count_series, model.inv_log),
    ]:
        print(f"[forecast] backtesting {metric} over {len(series_by_org)} trusts…")
        bt = backtest.run_backtest(
            series_by_org, volumes, config.HOLDOUT_WINTERS,
            horizons=[1, 2], break_month_key=break_key,
        )
        bt["metric"] = metric
        scores = backtest.score_backtest(bt, back)
        scores["metric"] = metric

        # Intervals calibrated on the first holdout winter, coverage measured
        # out-of-sample on the second; shipped intervals use both pooled.
        first, second = config.HOLDOUT_WINTERS
        iv_first = backtest.empirical_intervals(bt[bt["winter"] == first], back)
        cov_second = backtest.measure_coverage(bt[bt["winter"] == second], iv_first, back)
        cov_second["calibration"] = f"calibrated on {first}, measured on {second}"
        iv_pooled = backtest.empirical_intervals(bt, back)
        cov_pooled = backtest.measure_coverage(bt, iv_pooled, back)
        cov_pooled["calibration"] = "pooled (in-sample)"
        coverage = pd.concat([cov_second, cov_pooled], ignore_index=True)
        coverage["metric"] = metric

        print(f"[forecast] final {metric} forecast…")
        fdf, clusters = _final_forecast(
            series_by_org, volumes, latest, iv_pooled, metric, back, break_key
        )
        clusters_final = clusters  # same features both metrics; keep last
        all_metrics.append(scores)
        all_details.append(bt)
        all_forecasts.append(fdf)
        all_coverage.append(coverage)

    metrics = pd.concat(all_metrics, ignore_index=True)
    detail = pd.concat(all_details, ignore_index=True)
    forecasts = pd.concat(all_forecasts, ignore_index=True)
    coverage = pd.concat(all_coverage, ignore_index=True)

    clusters_final.to_parquet(out_dir / "org_clusters.parquet", index=False)
    forecasts.to_parquet(out_dir / "fact_forecast.parquet", index=False)
    metrics.to_parquet(out_dir / "backtest_metrics.parquet", index=False)
    detail.to_parquet(out_dir / "backtest_detail.parquet", index=False)
    coverage.to_parquet(out_dir / "interval_coverage.parquet", index=False)

    _write_evaluation_report(metrics, coverage, detail, latest)

    headline = metrics[
        (metrics["metric"] == "breach_rate")
        & (metrics["model"] == "cluster_pooled")
        & (metrics["horizon"] == 2)
    ]
    mae_pp = (headline["mae"] * 100).round(2).tolist()
    return (
        f"{len(forecasts['org_code'].unique())} trusts forecast to "
        f"{forecasts['target_month_key'].max()}; h=2 breach-rate MAE by winter (pp): {mae_pp}"
    )


def _write_evaluation_report(metrics, coverage, detail, latest) -> None:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Forecast evaluation — honest scorecard",
        "",
        f"Backtest: rolling origin, held-out winters {' and '.join(config.HOLDOUT_WINTERS)} "
        "(Dec/Jan/Feb), horizons 1-2 months; every artefact (clusters, pooled seasonal "
        "indices, model fits) re-estimated at each origin from data available then. "
        f"Final forecasts trained through {latest // 100}-{latest % 100:02d}.",
        "",
        "The seasonal-naive row is the bar. If a model does not beat it, that is shown, "
        "not hidden.",
        "",
    ]
    for metric, unit, scale in [
        ("breach_rate", "percentage points", 100),
        ("att_per_day", "attendances/day", 1),
    ]:
        lines += [f"## {metric} ({unit})", ""]
        sub = metrics[metrics["metric"] == metric].copy()
        sub["mae_u"] = (sub["mae"] * scale).round(2)
        sub["skill"] = (sub["skill_vs_naive"] * 100).round(1)
        sub["beat"] = (sub["pct_beat_naive"] * 100).round(0)
        lines += [
            "| winter | h | model | MAE | skill vs naive | % trusts beating naive | n |",
            "|---|---|---|---|---|---|---|",
        ]
        for _, r in sub.sort_values(["winter", "horizon", "model"]).iterrows():
            skill = "—" if r["model"] == "seasonal_naive" else f"{r['skill']}%"
            beat = "—" if r["model"] == "seasonal_naive" else f"{r['beat']:.0f}%"
            lines.append(
                f"| {r['winter']} | {r['horizon']} | {r['model']} | {r['mae_u']} "
                f"| {skill} | {beat} | {r['n']} |"
            )
        lines.append("")
        cov = coverage[coverage["metric"] == metric]
        lines += ["**80% interval coverage (cluster_pooled):**", ""]
        for _, r in cov.iterrows():
            lines.append(
                f"- winter {r['winter']}, h={r['horizon']}: {r['coverage'] * 100:.0f}% "
                f"({r['calibration']})"
            )
        lines.append("")

    lines += [
        "## Reading this honestly",
        "",
        "- Winter 2025-26 sits just after the November-2025 ECDS methodology change; "
        "origins that winter had at most three post-change observations, so its rows "
        "quantify what a publication discontinuity costs a forecaster. That cost is "
        "reported, not smoothed over.",
        "- Coverage below nominal 80% is printed as measured. Users of the fan chart "
        "should treat the bands as *at least* this uncertain.",
        "- 12-hour DTA breaches are not forecast (spiky, zero-inflated small counts); "
        "they appear descriptively in the dashboard instead.",
        "- '8-week' horizon = 2 months at the publication's monthly grain. The extended "
        "winter outlook (h>2) is indicative only and its intervals are inflated "
        "sqrt(h/2) beyond the validated range.",
    ]
    (config.REPORTS_DIR / "forecast-evaluation.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
