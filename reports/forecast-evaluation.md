# Forecast evaluation — honest scorecard

Backtest: rolling origin, held-out winters 2024-25 and 2025-26 (Dec/Jan/Feb), horizons 1-2 months; every artefact (clusters, pooled seasonal indices, model fits) re-estimated at each origin from data available then. Final forecasts trained through 2026-06.

The seasonal-naive row is the bar. If a model does not beat it, that is shown, not hidden.

## breach_rate (percentage points)

| winter | h | model | MAE | skill vs naive | % trusts beating naive | n |
|---|---|---|---|---|---|---|
| 2024-25 | 1 | cluster_pooled | 2.95 | 41.8% | 70% | 360 |
| 2024-25 | 1 | ets | 3.27 | 35.5% | 66% | 360 |
| 2024-25 | 1 | seasonal_naive | 5.07 | — | — | 360 |
| 2024-25 | 2 | cluster_pooled | 4.06 | 19.9% | 59% | 360 |
| 2024-25 | 2 | ets | 4.42 | 12.9% | 54% | 360 |
| 2024-25 | 2 | seasonal_naive | 5.07 | — | — | 360 |
| 2025-26 | 1 | cluster_pooled | 3.44 | 32.5% | 62% | 360 |
| 2025-26 | 1 | ets | 3.81 | 25.1% | 59% | 360 |
| 2025-26 | 1 | seasonal_naive | 5.09 | — | — | 360 |
| 2025-26 | 2 | cluster_pooled | 4.15 | 17.5% | 53% | 360 |
| 2025-26 | 2 | ets | 4.76 | 5.4% | 50% | 360 |
| 2025-26 | 2 | seasonal_naive | 5.03 | — | — | 360 |

**80% interval coverage (cluster_pooled):**

- winter 2025-26, h=1: 68% (calibrated on 2024-25, measured on 2025-26)
- winter 2025-26, h=2: 69% (calibrated on 2024-25, measured on 2025-26)
- winter 2024-25, h=1: 84% (pooled (in-sample))
- winter 2024-25, h=2: 83% (pooled (in-sample))
- winter 2025-26, h=1: 76% (pooled (in-sample))
- winter 2025-26, h=2: 76% (pooled (in-sample))

## att_per_day (attendances/day)

| winter | h | model | MAE | skill vs naive | % trusts beating naive | n |
|---|---|---|---|---|---|---|
| 2024-25 | 1 | cluster_pooled | 12.02 | 50.0% | 69% | 360 |
| 2024-25 | 1 | ets | 11.96 | 50.3% | 72% | 360 |
| 2024-25 | 1 | seasonal_naive | 24.05 | — | — | 360 |
| 2024-25 | 2 | cluster_pooled | 16.03 | 33.4% | 62% | 360 |
| 2024-25 | 2 | ets | 15.45 | 35.8% | 66% | 360 |
| 2024-25 | 2 | seasonal_naive | 24.05 | — | — | 360 |
| 2025-26 | 1 | cluster_pooled | 15.34 | 29.3% | 62% | 360 |
| 2025-26 | 1 | ets | 14.04 | 35.2% | 63% | 360 |
| 2025-26 | 1 | seasonal_naive | 21.68 | — | — | 360 |
| 2025-26 | 2 | cluster_pooled | 14.57 | 35.3% | 66% | 360 |
| 2025-26 | 2 | ets | 14.61 | 35.1% | 67% | 360 |
| 2025-26 | 2 | seasonal_naive | 22.51 | — | — | 360 |

**80% interval coverage (cluster_pooled):**

- winter 2025-26, h=1: 66% (calibrated on 2024-25, measured on 2025-26)
- winter 2025-26, h=2: 80% (calibrated on 2024-25, measured on 2025-26)
- winter 2024-25, h=1: 83% (pooled (in-sample))
- winter 2024-25, h=2: 78% (pooled (in-sample))
- winter 2025-26, h=1: 76% (pooled (in-sample))
- winter 2025-26, h=2: 81% (pooled (in-sample))

## Reading this honestly

- Winter 2025-26 sits just after the November-2025 ECDS methodology change; origins that winter had at most three post-change observations, so its rows quantify what a publication discontinuity costs a forecaster. That cost is reported, not smoothed over.
- Coverage below nominal 80% is printed as measured. Users of the fan chart should treat the bands as *at least* this uncertain.
- 12-hour DTA breaches are not forecast (spiky, zero-inflated small counts); they appear descriptively in the dashboard instead.
- '8-week' horizon = 2 months at the publication's monthly grain. The extended winter outlook (h>2) is indicative only and its intervals are inflated sqrt(h/2) beyond the validated range.
