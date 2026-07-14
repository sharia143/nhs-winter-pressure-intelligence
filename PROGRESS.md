# PROGRESS — NHS Winter Pressure Intelligence

Resume tracker. Machine state: `data/state/stage_status.json`. Re-run any stage with `python scripts/run_pipeline.py <stage>`; every stage is idempotent and self-skips when its outputs are current.

_Last updated: 2026-07-12 12:18 UTC_

## Stage status

| Stage | Status | Last run | Rows | Note |
|---|---|---|---|---|
| download | ok | 2026-07-12 11:25 UTC | — | A&E 63 months, RTT 62 months, 138 files in manifest; 1 warnings |
| ingest | ok | 2026-07-12 11:58 UTC | — | ods: current (skipped); ae: current (skipped); rtt: 3239798 rows across 2 tables; ambsys: 1284 rows across 1 tables; imd: current (skipped); catchment: current (skipped); weather: current (skipped); vacancy: current (skipped) |
| warehouse | ok | 2026-07-12 12:11 UTC | — | backtest_metrics=24, bridge_org_succession=11165, dim_date=119, dim_icb=48, dim_org=671, dim_trust_catchment=133, fact_ae=12701, fact_ambulance=1284, fact_forecast=1920, fact_rtt=256958, fact_rtt_bands=2982840, fact_vacancy=7373, fact_weather=1712, interval_coverage=12, org_clusters=120, org_icb=208, org_map=692, org_succession_raw=11538 |
| analyse | ok | 2026-07-12 12:02 UTC | — | league table 120 trusts; national Type-1 perf 61.0% (202606); equity r=0.13 |
| forecast | ok | 2026-07-12 12:07 UTC | — | 120 trusts forecast to 202702; h=2 breach-rate MAE by winter (pp): [4.06, 4.15] |
| export | ok | 2026-07-12 12:11 UTC | — | 16 CSVs -> powerbi/data |
| fusion | ok | 2026-07-12 12:18 UTC | — | two-way demeaned vacancy analysis; honest null at regional grain |

## How to resume

1. `python scripts/run_pipeline.py all` — runs every stage; completed stages skip themselves.
2. Check the table above for the first stage that is not `ok`, and re-run just that stage.
3. Manual/user steps live in `docs/MANUAL_STEPS.docx` (and `powerbi/BUILD_GUIDE.md`).

## Run log (most recent last)

- 2026-07-12 11:23 UTC — **download** → ok — A&E 62 months, RTT 38 months, 111 files in manifest; 1 warnings
- 2026-07-12 11:25 UTC — **download** → ok — A&E 63 months, RTT 62 months, 138 files in manifest; 1 warnings
- 2026-07-12 11:35 UTC — **ingest** → FAILED — ValueError: unparseable Period value 'TOTAL' in 2021-04.csv
- 2026-07-12 11:37 UTC — **ingest** → FAILED — ValueError: A&E format drift: unmapped column 'Unnamed: 22' (normalised: 'unnamed 22') in 2024-09.csv
- 2026-07-12 11:39 UTC — **ingest** → FAILED — ValueError: A&E format drift: unmapped column 'a' (normalised: 'a') in 2024-09.csv
- 2026-07-12 11:51 UTC — **ingest** → ok — ods: current (skipped); ae: 12701 rows across 1 tables; rtt: 3239798 rows across 2 tables; ambsys: 1284 rows across 1 tables; imd: 33755 rows across 1 tables; catchment: 134 rows across 1 tables; weather: 1712 rows across 1 tables; vacancy: 7373 rows across 1 tables
- 2026-07-12 11:58 UTC — **ingest** → ok — ods: current (skipped); ae: current (skipped); rtt: 3239798 rows across 2 tables; ambsys: 1284 rows across 1 tables; imd: current (skipped); catchment: current (skipped); weather: current (skipped); vacancy: current (skipped)
- 2026-07-12 11:59 UTC — **warehouse** → FAILED — BinderException: Binder Error: Cannot mix aggregates with non-aggregated columns!
- 2026-07-12 11:59 UTC — **warehouse** → FAILED — BinderException: Binder Error: Cannot mix aggregates with non-aggregated columns!
- 2026-07-12 12:00 UTC — **warehouse** → FAILED — BinderException: Binder Error: Cannot mix aggregates with non-aggregated columns!
- 2026-07-12 12:01 UTC — **warehouse** → ok — bridge_org_succession=11165, dim_date=1712, dim_icb=48, dim_org=671, dim_trust_catchment=133, fact_ae=12701, fact_ambulance=1284, fact_rtt=256958, fact_rtt_bands=2982840, fact_vacancy=7373, fact_weather=1712, org_icb=208, org_map=692, org_succession_raw=11538
- 2026-07-12 12:02 UTC — **warehouse** → ok — bridge_org_succession=11165, dim_date=119, dim_icb=48, dim_org=671, dim_trust_catchment=133, fact_ae=12701, fact_ambulance=1284, fact_rtt=256958, fact_rtt_bands=2982840, fact_vacancy=7373, fact_weather=1712, org_icb=208, org_map=692, org_succession_raw=11538
- 2026-07-12 12:02 UTC — **analyse** → ok — league table 120 trusts; national Type-1 perf 61.0% (202606); equity r=0.13
- 2026-07-12 12:07 UTC — **forecast** → ok — 120 trusts forecast to 202702; h=2 breach-rate MAE by winter (pp): [4.06, 4.15]
- 2026-07-12 12:08 UTC — **warehouse** → ok — backtest_metrics=24, bridge_org_succession=11165, dim_date=119, dim_icb=48, dim_org=671, dim_trust_catchment=133, fact_ae=12701, fact_ambulance=1284, fact_forecast=1920, fact_rtt=256958, fact_rtt_bands=2982840, fact_vacancy=7373, fact_weather=1712, interval_coverage=12, org_clusters=120, org_icb=208, org_map=692, org_succession_raw=11538
- 2026-07-12 12:08 UTC — **export** → ok — 16 CSVs -> powerbi/data
- 2026-07-12 12:08 UTC — **fusion** → ok — fusion: r(now)=-0.37, r(lag3)=-0.30 over 420 region-months
- 2026-07-12 12:08 UTC — **fusion** → ok — fusion: r(now)=-0.17, r(lag3)=-0.12 over 420 region-months
- 2026-07-12 12:11 UTC — **warehouse** → ok — backtest_metrics=24, bridge_org_succession=11165, dim_date=119, dim_icb=48, dim_org=671, dim_trust_catchment=133, fact_ae=12701, fact_ambulance=1284, fact_forecast=1920, fact_rtt=256958, fact_rtt_bands=2982840, fact_vacancy=7373, fact_weather=1712, interval_coverage=12, org_clusters=120, org_icb=208, org_map=692, org_succession_raw=11538
- 2026-07-12 12:11 UTC — **export** → ok — 16 CSVs -> powerbi/data
- 2026-07-12 12:18 UTC — **fusion** → ok — two-way demeaned vacancy analysis; honest null at regional grain
