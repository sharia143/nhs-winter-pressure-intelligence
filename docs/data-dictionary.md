# Data dictionary

Grain, keys and semantics for every warehouse table and export. Raw source
files are pinned (URL + sha256 + retrieval date) in `data/raw/manifest.json`;
NHS England revises published files, so the manifest is the version of record.

## Conventions

- `month_key` — integer `yyyymm`, the universal time key.
- `org_code_published` — ODS code exactly as printed in the source file.
- `org_code` — analysis key: the transitively-resolved ultimate successor of
  the published code (`bridge_org_succession`), so merged trusts' history
  rolls up to today's organisations. KPI views group on this.
- Counts are stored; **rates live only in views** and are always recomputed
  from summed counts.
- Suppressed/redacted source cells are NULL; imputation never occurs in
  KPI-facing tables. NULL means "unknown", never zero.
- "Type 1" = major consultant-led 24-hour A&E. "Other A&E Department" in the
  source is Type 3 in all but name. 12-hour measure = **from decision to
  admit (DTA)**, not from arrival.

## Dimensions

### dim_date (month grain)
| column | meaning |
|---|---|
| month_key | yyyymm |
| month_start, days_in_month, month_name, fy, fy_start | calendar helpers; fy = NHS financial year label ("2024-25") |
| is_winter | Dec-Feb |
| winter_label | "2024-25" for Dec-24, Jan-25, Feb-25 (spans year boundary) |
| is_summer | Jun-Aug (the baseline window for winter deltas) |
| methodology_break | TRUE from 2025-11 (ECDS publication change) |

### dim_org (analysis organisation)
One row per analysis org appearing in A&E or RTT. `org_type` from ODS
(NHS Trust / Care Trust / Other provider — the A&E files also contain GP
practices, UTCs and WICs). `is_type1_provider` = recorded Type-1 attendances
in ≥24 window months (the league-table population). `icb_code/icb_name` =
post-April-2026 footprints (System-Mapping, 16 Apr 2026);
`icb_code_2022/icb_name_2022` = original July-2022 ICB attribution.
`region_name` from ODS national grouping, ICB mapping, or the publication's
Parent Org, in that order.

### dim_icb
All ICB codes ever registered (from ODS strategic-partnership file),
including the 12 closed and 6 created in the April-2026 mergers;
`is_current` distinguishes them.

### dim_trust_catchment
OHID April-2026 catchment estimates (latest catchment year, all admissions):
`catchment_population`; `imd_score` = catchment-weighted IMD score (higher =
more deprived catchment); `deprivation_quintile` (1 = most deprived fifth of
trusts); `core20_proxy` = quintile 1 — an explicit **proxy**: true Core20
shares need LSOA-level catchment flows that are not published at trust level.
Catchment vintage (HES 2021/22-2024/25 admissions, IMD 2019-based scoring by
OHID) predates IMD 2025; treated as slowly-moving context, not exact.

### bridge_org_succession
`predecessor_code → ultimate_successor_code` with `chain_depth` and
`ambiguous_split` (TRUE where ODS records >1 successor at the same depth —
e.g. demerger/split cases; these trusts are excluded from headline backtest
MAE and listed separately).

## Facts

### fact_ae (org-month, published grain + rollup key)
Counts from the monthly A&E publication: `att_type1/2/other`,
`att_booked_*` (booked-appointment subset, kept but not added to totals),
`over4hr_*`, `dta_4to12hr`, `dta_12hr_plus`, `emadm_type1/2/other`,
`emadm_not_ae`. The publisher's TOTAL row is excluded and used as a load
validation instead (`data/state/ae_validations.json`).

### fact_rtt (org-month-treatment function)
Incomplete pathways (Part_2): `total_incomplete` (explicit Total column, or
weeks-band sum where that column is blank — known clock starts),
`total_incl_unknown_start`, `unknown_clock_start`, `within_18wk`,
`over_52wk/65wk/78wk/104wk`. Publisher rollup rows (`C_999`) retained,
flagged by their code, excluded from KPI sums.

### fact_rtt_bands (org-month-weeks band)
Long weeks-waited distribution summed over treatment functions (rollup rows
excluded). `band_weeks_high` NULL = open-ended 104+ band.

### fact_ambulance (ambulance service-month)
AmbSYS metrics in seconds: `cat1/2/3/4_mean_sec`, `cat1/2/3/4_90th_sec`,
incident counts, `call_answer_90th_sec`. England rows flagged
`is_england`. **No join to acute trusts is fabricated** — ~11 services cover
whole regions; regional views are the honest grain.

### fact_vacancy (region-month-staff group)
ESR-derived vacancy **WTE counts** (no denominators are published, so no
rates); Experimental Statistics. Views derive a pressure index vs each
region's own window mean.

### fact_weather (England-month)
HadUK-Grid areal mean temperature; `tmean_anomaly` vs 1991-2020 monthly
normals.

### fact_forecast (org-month-metric-horizon) *(after forecast stage)*
`metric` ∈ {breach_rate, att_per_day}; `point`, `lo80`, `hi80` (empirical
80% intervals from backtest residuals pooled by cluster × horizon);
`is_validated_horizon` TRUE for h ≤ 2 ("8 weeks"); h 3-8 is the indicative
winter outlook with intervals inflated √(h/2).

## KPI views

`vw_kpi_ae_monthly` (performance recomputed from sums; both Type-1 and
all-types), `vw_kpi_rtt_monthly` (18-week % on known-clock-start totals;
waiting per 10k catchment), `vw_kpi_winter_delta` (winter vs *preceding*
Jun-Aug summer, defined in dim_date), `vw_equity`, `vw_trust_latest` (RAG:
GREEN ≥78% interim ambition, AMBER 70-78%, RED <70%; the 95% constitutional
standard is a separate flag), `vw_ambulance_regional` (incident-weighted
means), `vw_vacancy_regional`, `vw_ae_period_on_period` (window-function
showcase).

## Thresholds cited

- A&E 4-hour: 95% constitutional standard; **78%** 2025/26 planning
  ambition (interim). RAG keys off the interim ambition because that is what
  boards are performance-managed against this year; both lines appear on
  every chart.
- RTT: 92% within 18 weeks (constitutional standard).
- Ambulance: Cat1 mean 7 min / Cat2 mean 18 min (shown as reference lines).
