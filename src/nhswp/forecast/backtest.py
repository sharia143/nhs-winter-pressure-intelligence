"""Rolling-origin backtest over held-out winters + empirical intervals.

For each target month (Dec/Jan/Feb of each holdout winter) and each horizon
h in {1, 2}: train on data through target−h, forecast the target, score on
the natural scale (percentage points for breach rates; attendances/day for
counts). Everything — cluster memberships, pooled seasonal indices, model
fits — is re-estimated at each origin from data available at that origin, so
there is no leakage.

Intervals are empirical: backtest residuals pooled by cluster × horizon give
10th/90th percentiles → 80% intervals. Coverage is then measured on the
holdouts and published even when it misses nominal (that gap, explained, is
the honesty artefact this project exists to demonstrate).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import features, model

WINTER_MONTHS = {"dec": 12, "jan": 1, "feb": 2}


def winter_targets(winter_label: str) -> list[int]:
    start_year = int(winter_label[:4])
    return [start_year * 100 + 12, (start_year + 1) * 100 + 1, (start_year + 1) * 100 + 2]


def run_backtest(
    series_by_org: dict[str, pd.Series],
    volumes: dict[str, float],
    winters: list[str],
    horizons: list[int] = [1, 2],
    break_month_key: int | None = None,
) -> pd.DataFrame:
    """Return one row per org × target × horizon × model with point + actual."""
    rows = []
    origins_done: dict[int, dict] = {}

    all_targets = [(w, t) for w in winters for t in winter_targets(w)]
    for winter, target in all_targets:
        for h in horizons:
            origin = model.add_months(target, -h)
            # Per-origin artefacts (clusters + seasonal indices) are cached per
            # origin, built strictly from data <= origin.
            if origin not in origins_done:
                truncated = {
                    o: s[[mk for mk in s.index if mk <= origin]]
                    for o, s in series_by_org.items()
                }
                if break_month_key:
                    truncated = {
                        o: model.relevel_history_for_break(s, break_month_key)[0]
                        for o, s in truncated.items()
                    }
                profiles = {o: features.seasonal_profile(s) for o, s in truncated.items()}
                usable = {o for o, p in profiles.items() if p is not None}
                clusters, k = features.cluster_trusts(
                    {o: profiles[o] for o in usable}, {o: volumes[o] for o in usable}
                )
                indices = features.pooled_seasonal_index(
                    {o: truncated[o] for o in usable}, clusters
                )
                origins_done[origin] = {
                    "series": truncated,
                    "clusters": dict(zip(clusters["org_code"], clusters["cluster_id"])),
                    "indices": indices,
                    "k": k,
                }
            art = origins_done[origin]

            for org, full_series in series_by_org.items():
                if target not in full_series.index or pd.isna(full_series.loc[target]):
                    continue  # no actual to score against — never impute eval months
                if org not in art["clusters"]:
                    continue
                train = art["series"][org]
                actual_tf = float(full_series.loc[target])
                cid = art["clusters"][org]

                preds = {
                    "seasonal_naive": model.seasonal_naive(train, origin, h),
                }
                ets = model.ets_forecast(train, origin, [h])
                preds["ets"] = None if ets is None else ets.get(h)
                cm = model.cluster_model_forecast(train, art["indices"][cid], origin, [h])
                preds["cluster_pooled"] = None if cm is None else cm.get(h)

                for name, pred_tf in preds.items():
                    if pred_tf is None:
                        continue
                    rows.append({
                        "org_code": org,
                        "winter": winter,
                        "target_month_key": target,
                        "horizon": h,
                        "origin_month_key": origin,
                        "model": name,
                        "cluster_id": cid,
                        "pred_tf": pred_tf,
                        "actual_tf": actual_tf,
                    })
    return pd.DataFrame(rows)


def score_backtest(bt: pd.DataFrame, back_transform) -> pd.DataFrame:
    """Aggregate to winter × horizon × model on the natural scale."""
    df = bt.copy()
    df["pred"] = back_transform(df["pred_tf"].to_numpy())
    df["actual"] = back_transform(df["actual_tf"].to_numpy())
    df["abs_err"] = (df["pred"] - df["actual"]).abs()

    naive = df[df["model"] == "seasonal_naive"][
        ["org_code", "target_month_key", "horizon", "abs_err"]
    ].rename(columns={"abs_err": "naive_abs_err"})
    df = df.merge(naive, on=["org_code", "target_month_key", "horizon"], how="left")

    out = (
        df.groupby(["winter", "horizon", "model"])
        .agg(
            mae=("abs_err", "mean"),
            median_ae=("abs_err", "median"),
            n=("abs_err", "size"),
            naive_mae=("naive_abs_err", "mean"),
            pct_beat_naive=("abs_err", lambda s: np.nan),  # filled below
        )
        .reset_index()
    )
    beat = (
        df[df["naive_abs_err"].notna()]
        .assign(beat=lambda d: d["abs_err"] < d["naive_abs_err"])
        .groupby(["winter", "horizon", "model"])["beat"]
        .mean()
        .reset_index(name="pct_beat_naive_calc")
    )
    out = out.drop(columns=["pct_beat_naive"]).merge(
        beat, on=["winter", "horizon", "model"], how="left"
    ).rename(columns={"pct_beat_naive_calc": "pct_beat_naive"})
    out["skill_vs_naive"] = 1.0 - out["mae"] / out["naive_mae"]
    return out


def empirical_intervals(
    bt: pd.DataFrame, back_transform, model_name: str = "cluster_pooled",
    quantiles: tuple[float, float] = (0.10, 0.90),
) -> pd.DataFrame:
    """Residual quantiles (natural scale) pooled by cluster × horizon."""
    df = bt[bt["model"] == model_name].copy()
    df["resid"] = back_transform(df["actual_tf"].to_numpy()) - back_transform(
        df["pred_tf"].to_numpy()
    )
    grouped = (
        df.groupby(["cluster_id", "horizon"])["resid"]
        .agg(
            lo=lambda s: s.quantile(quantiles[0]),
            med="median",
            hi=lambda s: s.quantile(quantiles[1]),
            n="size",
        )
        .reset_index()
    )
    return grouped


def measure_coverage(
    bt: pd.DataFrame, intervals: pd.DataFrame, back_transform,
    model_name: str = "cluster_pooled",
) -> pd.DataFrame:
    df = bt[bt["model"] == model_name].merge(
        intervals, on=["cluster_id", "horizon"], how="inner"
    )
    pred = back_transform(df["pred_tf"].to_numpy())
    actual = back_transform(df["actual_tf"].to_numpy())
    df["covered"] = (actual >= pred + df["lo"]) & (actual <= pred + df["hi"])
    return (
        df.groupby(["winter", "horizon"])["covered"].mean().reset_index(name="coverage")
    )
