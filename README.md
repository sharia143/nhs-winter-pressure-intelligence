# NHS Winter Pressure Intelligence

A trust-level winter-pressure platform built on the **same monthly
publications NHS trust BI teams report to their boards** — A&E 4-hour
performance, RTT waiting lists, ambulance response times — joined to
deprivation and weather, with an 8-week breach-risk forecast (honestly
backtested) and an ICB-style board memo.

> Portfolio project (aggregate public data only — no patient-level access,
> no SUS). It exists to demonstrate the Tuesday-morning reality of NHS
> analysis: statutory publications that arrive as messy Excel, organisations
> that merge under you, methodology that changes mid-series — and the
> discipline of publishing your forecast errors instead of hiding them.

## What's inside

| Layer | Artefact |
|---|---|
| **Data engineering** | Idempotent pipeline (`scripts/run_pipeline.py`): scrapes NHS England archive pages (file URLs are hash-randomised), downloads 130+ files, pins every version by sha256 in `data/raw/manifest.json` |
| **Data quality** | [`docs/defect-log.md`](docs/defect-log.md) — 11 real structural defects in the published files, each with its silent-corruption scenario and the pipeline's defence; parser drift canaries + pytest fixtures per format era |
| **SQL** | DuckDB star schema with a transitive **organisation-succession bridge** (trust mergers roll history to today's orgs; April-2026 ICB mergers handled), suppression-safe KPI views, window-function showcase ([`sql/showcase_queries.sql`](sql/showcase_queries.sql)) |
| **Statistics** | Cluster-pooled seasonal model + damped Holt per trust vs a **seasonal-naive baseline that is never deleted from the table**; rolling-origin backtest on two held-out winters; empirical 80% intervals with measured coverage ([`reports/forecast-evaluation.md`](reports/forecast-evaluation.md)) |
| **Power BI** | Star-schema exports + full DAX measure set ([`powerbi/measures.dax`](powerbi/measures.dax)) + click-by-click build guide ([`powerbi/BUILD_GUIDE.md`](powerbi/BUILD_GUIDE.md)) |
| **Engagement** | Streamlit "**Look up your local A&E**" app — town search → RAG card → forecast fan with honest bands |
| **Communication** | One-page ICB board memo with the three highest-risk trusts and two pre-positioning recommendations ([`docs/memo/ICB_board_memo.md`](docs/memo/ICB_board_memo.md)) |

## Quick start

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py all      # download → ingest → warehouse → analyse → forecast → export → fusion
python -m pytest tests -q               # parser tests on real-file fixtures
streamlit run app/streamlit_app.py      # the engagement app
```

Every stage is idempotent and self-skipping; [`PROGRESS.md`](PROGRESS.md) is
re-rendered after each stage and is the resume point if a run is interrupted.

## Headline numbers (auto-generated from the current data window)

<!-- HEADLINE:START -->
- **England Type-1 4-hour performance 2026-06:** 61.0% across 120 Type-1 providers (1,461,113 Type-1 attendances)
- **RTT incomplete pathways 2026-05:** 7,184,233 waiting, 65.5% within 18 weeks
- **Equity:** deprivation-performance correlation r = 0.13 (95% CI -0.05 to 0.30, n = 120)
- **8-week breach-rate MAE, cluster model:** 4.1pp (2024-25), 4.1pp (2025-26)
- **8-week breach-rate MAE, seasonal-naive baseline:** 5.1pp (2024-25), 5.0pp (2025-26)
- **80% interval coverage (out-of-sample winter, h=2):** 69% — published as measured
- **Hospital Under Pressure:** within-region nursing-vacancy vs breach correlation r = -0.17 (same month), r = -0.12 (3-month lead)
<!-- HEADLINE:END -->

## Data sources (all public aggregates, versions pinned in the manifest)

| Source | Publication |
|---|---|
| A&E monthly (trust) | NHS England A&E Attendances and Emergency Admissions, Apr 2021 → Jun 2026 (63 monthly CSVs; ECDS methodology change Nov 2025 flagged) |
| RTT incomplete pathways | NHS England RTT statistics, monthly Full CSV extracts, Apr 2021 → May 2026 |
| Ambulance | AmbSYS consolidated indicators (Cat 1-4 response times) |
| Organisations | NHS ODS: etr/ect registers, succession file, ICB register; NHS England provider→ICB System Mapping (Apr 2026) |
| Deprivation | English Indices of Deprivation **2025**, File 7 (LSOA) |
| Catchments | OHID NHS Acute Trust Catchment Populations, April 2026 edition |
| Weather | Met Office HadUK-Grid England monthly mean temperature |
| Workforce | NHS Vacancy Statistics (Experimental), ESR series — regional grain, used as a pressure *index*, never presented as a rate |

## Honesty guardrails baked in

- Suppressed small numbers stay suppressed (NULL + flag; never reconstructed
  by differencing totals).
- 12-hour waits are **decision-to-admit**, labelled as such everywhere; they
  are deliberately *not* forecast (spiky small counts).
- The league table ships next to a **funnel plot** — a raw ranking is unfair
  to a major trauma centre, and the equity view says "Core20 **proxy**"
  because true Core20 shares aren't derivable from published aggregates.
- Both 4-hour reference lines shown: 95% constitutional standard and the 78%
  2025/26 interim ambition (RAG keys off the interim ambition, and says so).
- Winter 2025-26 backtest results are reported separately — they quantify
  what the ECDS publication change costs a forecaster.

## Career artefacts

CV bullet (numbers auto-filled from the current backtest in the Headline
section above):

> Built a trust-level NHS winter-pressure platform on the monthly A&E, RTT
> and ambulance publications: cleaned board-reported statutory data (11
> documented structural defects), modelled 120 Type-1 providers with a
> succession-aware DuckDB warehouse, forecast 8-week breach risk with a
> cluster-pooled seasonal model backtested on two held-out winters, and
> delivered an ICB-style decision memo — Python, SQL, Power BI.

## Repo map

```
scripts/run_pipeline.py     one command, seven idempotent stages
src/nhswp/                  config → download → ingest/ → warehouse/ → analysis/ → forecast/ → export/
sql/                        showcase queries (the permanent views live in src/nhswp/warehouse/views.sql)
powerbi/                    exports + measures.dax + BUILD_GUIDE.md (+ your WinterPressure.pbix)
app/streamlit_app.py        "Look up your local A&E"
docs/                       defect log · data dictionary · manual steps · memo · PLAN.docx
reports/                    forecast-evaluation.md (the honest scorecard)
tests/                      parser fixtures per format era + golden-value tests
```
