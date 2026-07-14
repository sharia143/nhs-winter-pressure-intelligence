"""Forecast model families.

Three tiers, all reported side-by-side (honesty over sophistication):

1. seasonal_naive — forecast(m) = actual(m-12). The mandatory baseline; NHS
   monthly series are seasonality-dominated and this is genuinely hard to
   beat at h<=2 with ~60 observations.
2. per-trust ETS — damped additive Holt-Winters via statsmodels. Estimating
   12 seasonal states per trust from ~5 cycles is marginal; included as a
   comparator precisely to show that.
3. cluster-pooled (headline) — pooled cluster seasonal index (12 medians,
   estimated across 20-60 similar trusts) + per-trust damped Holt on the
   deseasonalised series. Pooling stabilises the seasonal shape a single
   trust cannot estimate; level/trend stay trust-specific.

SARIMA deliberately absent: with 5 seasonal cycles the seasonal AR/MA terms
are unidentifiable in practice, and order selection across ~130 short,
break-ridden series is the sophistication trap the build spec warns about.

All models operate on a transformed scale (logit for breach rates, log for
attendance counts) supplied by the caller; back-transforms guarantee sane
ranges (rates in [0,1], counts >= 0).

Month arithmetic uses yyyymm integer keys throughout.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

EPS = 1e-4


def logit(p: pd.Series | np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def inv_logit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def log_tf(y: pd.Series | np.ndarray) -> np.ndarray:
    return np.log(np.clip(y, 1.0, None))


def inv_log(x: np.ndarray) -> np.ndarray:
    return np.exp(x)


def add_months(month_key: int, n: int) -> int:
    y, m = divmod(month_key, 100)
    total = y * 12 + (m - 1) + n
    return (total // 12) * 100 + (total % 12) + 1


def months_between(a: int, b: int) -> int:
    """Whole months from a to b (b later -> positive)."""
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def seasonal_naive(series: pd.Series, origin: int, horizon: int) -> float | None:
    """series indexed by month_key (transformed scale); train data <= origin."""
    target = add_months(origin, horizon)
    source = add_months(target, -12)
    if source in series.index and pd.notna(series.loc[source]) and source <= origin:
        return float(series.loc[source])
    return None


def _to_period_series(series: pd.Series) -> pd.Series:
    """month_key index -> monthly PeriodIndex for statsmodels."""
    idx = pd.PeriodIndex(
        [pd.Period(f"{mk // 100}-{mk % 100:02d}", freq="M") for mk in series.index],
        freq="M",
    )
    out = pd.Series(series.to_numpy(), index=idx).sort_index()
    full = pd.period_range(out.index.min(), out.index.max(), freq="M")
    return out.reindex(full)


def ets_forecast(series: pd.Series, origin: int, horizons: list[int]) -> dict[int, float] | None:
    """Damped additive Holt-Winters on the transformed scale."""
    train = series[[mk for mk in series.index if mk <= origin]]
    ps = _to_period_series(train).interpolate(limit=2)
    if ps.isna().any() or len(ps) < 30:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                ps.to_numpy(), trend="add", damped_trend=True,
                seasonal="add", seasonal_periods=12,
            ).fit(optimized=True)
        fc = fit.forecast(max(horizons))
        return {h: float(fc[h - 1]) for h in horizons}
    except Exception:
        return None


def holt_level_forecast(deseasonalised: pd.Series, origin: int, horizons: list[int]) -> dict[int, float] | None:
    """Damped Holt (no seasonal term) on a deseasonalised transformed series."""
    train = deseasonalised[[mk for mk in deseasonalised.index if mk <= origin]]
    ps = _to_period_series(train).interpolate(limit=2)
    ps = ps.dropna() if ps.isna().sum() <= 2 else ps
    if ps.isna().any() or len(ps) < 18:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                ps.to_numpy(), trend="add", damped_trend=True, seasonal=None
            ).fit(optimized=True)
        fc = fit.forecast(max(horizons))
        return {h: float(fc[h - 1]) for h in horizons}
    except Exception:
        return None


def cluster_model_forecast(
    series: pd.Series,
    seasonal_index: pd.Series,
    origin: int,
    horizons: list[int],
) -> dict[int, float] | None:
    """Headline model: remove cluster seasonal index, damped Holt on level,
    re-add the index at the target months."""
    moy = pd.Series(series.index % 100, index=series.index)
    deseason = series - moy.map(seasonal_index)
    level_fc = holt_level_forecast(deseason, origin, horizons)
    if level_fc is None:
        return None
    out = {}
    for h in horizons:
        target = add_months(origin, h)
        out[h] = level_fc[h] + float(seasonal_index.loc[target % 100])
    return out


def relevel_history_for_break(
    series: pd.Series, break_month_key: int, min_post: int = 3
) -> tuple[pd.Series, bool]:
    """If >= min_post observations exist at/after a methodology break, shift
    pre-break history onto the post-break level using the median year-on-year
    change at post-break months (transformed scale). With fewer post-break
    points the shift is unidentifiable — rely on the damped level adapting
    and let the backtest quantify the cost (reported per winter).
    """
    def yoy_deltas(months) -> list[float]:
        out = []
        for mk in months:
            prev = add_months(mk, -12)
            if prev in series.index and pd.notna(series.loc[prev]) and pd.notna(series.loc[mk]):
                out.append(float(series.loc[mk] - series.loc[prev]))
        return out

    post = [mk for mk in series.index if mk >= break_month_key]
    pre = [mk for mk in series.index if mk < break_month_key]
    post_deltas = yoy_deltas(post)
    pre_deltas = yoy_deltas(pre)
    if len(post_deltas) < min_post or len(pre_deltas) < 6:
        return series, False
    # Break shift = post-break YoY change net of the series' usual YoY drift
    shift = float(np.median(post_deltas)) - float(np.median(pre_deltas))
    adjusted = series.copy()
    pre_mask = adjusted.index < break_month_key
    adjusted.loc[pre_mask] = adjusted.loc[pre_mask] + shift
    return adjusted, True
