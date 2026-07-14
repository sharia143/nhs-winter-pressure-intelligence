# Power BI report build guide — click-by-click

Everything data-side is already done: `powerbi/data/` holds the star-schema
CSVs (regenerate any time with `python scripts/run_pipeline.py export`) and
`powerbi/measures.dax` holds every measure ready to paste. This guide takes
you from empty Power BI Desktop to the five report pages. Budget ~2-3 hours
the first time. (The same steps live in `docs/MANUAL_STEPS.docx` with more
hand-holding.)

## 0. Star schema you are building

```
                 dim_date ──────────────┐
                    │                   │
fact_ae_monthly ────┼── fact_rtt_monthly┼── fact_forecast
                    │                   │
                 dim_org ───────────────┘
                    │
        dim_trust_catchment / dim_equity / dim_org_clusters
   (region-grain: fact_ambulance_regional, fact_vacancy_regional)
```

All relationships single-direction, dims filtering facts.

## 1. Load the data

1. Open Power BI Desktop → blank report → **Get data ▸ Text/CSV**.
2. Load, one by one (or Get data ▸ Folder on `powerbi\data` and expand):
   `dim_org.csv`, `dim_date.csv`, `dim_icb.csv`, `dim_trust_catchment.csv`,
   `dim_equity.csv`, `dim_org_clusters.csv`, `fact_ae_monthly.csv`,
   `fact_rtt_monthly.csv`, `fact_winter_delta.csv`, `fact_trust_latest.csv`,
   `fact_ambulance_regional.csv`, `fact_vacancy_regional.csv`,
   `fact_forecast.csv`, `fact_backtest_metrics.csv`.
   For each: **Transform Data** the first time and confirm `month_key` typed
   *Whole Number*, dates typed *Date*, percentages *Decimal Number*.
3. Close & Apply.

## 2. Relationships (Model view)

Drag-and-drop these (all **Many-to-one**, **Single** cross-filter):

| From (many) | column | To (one) | column |
|---|---|---|---|
| fact_ae_monthly | month_key | dim_date | month_key |
| fact_ae_monthly | org_code | dim_org | org_code |
| fact_rtt_monthly | month_key | dim_date | month_key |
| fact_rtt_monthly | org_code | dim_org | org_code |
| fact_forecast | target_month_key | dim_date | month_key |
| fact_forecast | org_code | dim_org | org_code |
| fact_winter_delta | org_code | dim_org | org_code |
| fact_trust_latest | org_code | dim_org | org_code |
| dim_trust_catchment | org_code | dim_org | org_code |
| dim_equity | org_code | dim_org | org_code |
| dim_org_clusters | org_code | dim_org | org_code |
| fact_ambulance_regional | month_key | dim_date | month_key |
| fact_vacancy_regional | month_key | dim_date | month_key |

Mark `dim_date` as the date table: Table tools ▸ **Mark as date table** ▸
`month_start`.

## 3. Measures

Open `powerbi/measures.dax`. For each block: select the table named in the
block header, **Modeling ▸ New measure**, paste one measure, Enter. (Order
matters only in that base measures come before ones that reference them —
the file is already ordered.) Format percentages as % with 1 decimal
(Measure tools ▸ Format), `pp` measures as decimal.

## 4. Pages

### Page 1 — National picture
- **Card row** (4 KPI cards): `4hr Performance Type1`, `12hr DTA Waits`,
  `RTT Waiting List`, `RTT 18wk %`. Add a slicer on `dim_date[fy]`.
- **Line chart**: X = `dim_date[month_start]`, Y = `4hr Performance Type1`.
  Add constant lines (Analytics pane ▸ Y-Axis Constant Line) at **0.95**
  (green, "95% standard") and **0.78** (amber, "interim ambition").
  Add a Date **vertical line / annotation** at 1 Nov 2025 labelled
  "ECDS methodology change".
- **Map/table fallback**: matrix of Region × month heat-mapped by
  `4hr Performance Type1` (Conditional formatting ▸ Background colour ▸
  diverging, centre 0.78). *(A post-April-2026 ICB boundary shapefile may
  not exist yet on the ONS geoportal — the matrix IS the default design,
  not a downgrade.)*

### Page 2 — Trust league & funnel
- **Table**: `dim_org[org_name]`, `4hr Performance Type1`,
  `4hr Performance YoY pp`, `12hr DTA Waits`, `RAG Type1` (conditional
  format background by `RAG Colour Type1` field value). Sort ascending by
  performance. Filter: `dim_org[is_type1_provider]` = True, latest month via
  slicer on `dim_date[month_start]` (dropdown, single select).
- **Scatter (the funnel)**: X = `Attendances Type1` (last-12m — use the
  `dim_equity[att_type1_12m]` column), Y = `1 - dim_equity[type1_performance_12m]`
  (create a column or use the breach measure), Details = org_name.
  Add the pre-computed funnel image `outputs/figures/funnel_plot.png` beside
  it (Insert ▸ Image) — the control limits are statistical, not drawable
  natively in Power BI.
- Text box: "A raw ranking is unfair to high-volume major trauma centres —
  judge position against the funnel limits, not row order."

### Page 3 — Trust drill-down
- Slicer (search enabled): `dim_org[org_name]`.
- KPI cards: `4hr Performance Type1`, `Perf Gap vs National pp`,
  `12hr DTA Waits`, `RTT Waiting per 10k Catchment`.
- Line: trust vs `National 4hr Performance Type1` (both measures on one
  chart, X = month_start).
- Column chart: `RTT 52wk+` by month.
- Table: winter deltas for this trust from fact_winter_delta.

### Page 4 — Forecast fan
- Line chart: X = `dim_date[month_start]`;
  lines = `4hr Performance Type1` (history), `Forecast Performance`,
  plus **stacked area** combo for the band: `Forecast Performance Lo80`
  (fill = transparent) stacked with `Forecast Band Width` (fill = 20% blue).
  Easiest: a combo "Line and stacked column" visual, or overlay two area
  charts.
- Slicer: `dim_org[org_name]` (single select).
- Card: `Forecast Performance` at max horizon + a text box quoting the
  honest caveat from `reports/forecast-evaluation.md` (MAE + coverage).
- Table: `fact_backtest_metrics` (winter × horizon × model MAE) — the
  "we publish our errors" table. Filter metric = breach_rate.

### Page 5 — Equity (Core20 proxy view)
- Scatter: X = `dim_equity[imd_score]`, Y = `type1_performance_12m`,
  legend = `core20_proxy`, details = org_name.
- Cards: `Equity Gap pp`, `Avg Performance Most Deprived Quintile`,
  `Avg Performance Least Deprived Quintile`.
- Text box (verbatim, this is the honest framing): "Deprivation exposure is
  the OHID catchment-weighted IMD score; the red group is the most-deprived
  quintile of trusts — a Core20 *proxy* (true Core20 needs LSOA-level
  catchments not published at trust level). Ecological association, not a
  causal claim."
- Optional: bar of `Nursing Vacancy Pressure` by region alongside regional
  performance ("Hospital Under Pressure" fusion view).

## 5. Finish

- File ▸ Save as `powerbi/WinterPressure.pbix`.
- Screenshot each page (Win+Shift+S) into `powerbi/screenshots/page1.png` …
  `page5.png` — reviewers on GitHub see these without opening Power BI.
- Optional publish: Home ▸ Publish ▸ your workspace (needs a Power BI
  account; the free tier is fine for a personal workspace).
