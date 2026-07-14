# Manual steps — everything that needs your hands, click by click

Everything else in this project is automated. This guide covers only what
genuinely requires you at the keyboard, in the order you should do it. A
Word copy of this guide is at `docs/MANUAL_STEPS.docx`.

Estimated total time: **3-4 hours**, almost all of it Power BI.

---

## Step 0 — Sanity check the automated build (5 minutes)

1. Open a terminal (Windows key → type `cmd` → Enter).
2. Type `cd "C:\Users\JUBAIR\Downloads\project 3\nhs-winter-pressure"` → Enter.
3. Type `python scripts/run_pipeline.py all` → Enter.
   - Every stage should print `ok … (skipped)` or finish quickly — the
     pipeline is idempotent. If a stage says `FAILED`, open `PROGRESS.md`:
     the run log at the bottom names the stage and error.
4. Type `python -m pytest tests -q` → Enter. Expect `13 passed`.

## Step 1 — Look at your app (2 minutes)

1. Same terminal: `streamlit run app/streamlit_app.py` → Enter.
2. A browser tab opens at `http://localhost:8501`.
3. Type your town (e.g. "Leeds") in the search box, pick a trust, and check
   the forecast fan renders. This is your interview demo — practice the
   30-second walkthrough: *search → RAG card → fan chart → "the bands are
   backtested honest intervals"*.
4. Stop the app later with Ctrl+C in the terminal.

## Step 2 — Build the Power BI report (2-3 hours)

Follow `powerbi/BUILD_GUIDE.md` — it lists every Get Data click, every
relationship to drag, every measure to paste (from `powerbi/measures.dax`),
and the exact visual layout of all five pages. Summary of the clicks:

1. Open **Power BI Desktop** (Start menu → "Power BI Desktop").
2. **Get data ▸ Text/CSV** → load the 14 CSVs from `powerbi\data\`.
3. **Model view** (third icon, left edge) → drag the 13 relationships listed
   in the guide (all many-to-one into `dim_date`/`dim_org`).
4. **Table tools ▸ Mark as date table** on `dim_date` (`month_start`).
5. **Modeling ▸ New measure** → paste measures one at a time from
   `powerbi\measures.dax` (top to bottom).
6. Build the five pages exactly as specified in the guide:
   national → league+funnel → trust drill-down → forecast fan → equity.
7. **File ▸ Save As** → `powerbi\WinterPressure.pbix`.
8. Screenshot each page (Win+Shift+S) → save as
   `powerbi\screenshots\page1.png` … `page5.png`.
9. Commit: in the terminal,
   `git add powerbi && git commit -m "Power BI report + screenshots" && git push`.

## Step 3 — Defect-log screenshot pack (15 minutes)

Open each file in Excel and screenshot (Win+Shift+S) into
`docs\screenshots\`, named as shown:

| # | Open this file | Show this | Save as |
|---|---|---|---|
| 1 | `data\raw\ae\2026-06.csv` | Bottom row: `TOTAL` in the Period column (Ctrl+End jumps there) | `d1_total_row.png` |
| 2 | `data\raw\ae\2024-09.csv` | Header row scrolled right to columns W-AB: empty headers + the stray `a` column | `d2_stray_columns.png` |
| 3 | `data\raw\ambulance\ambsys.csv` | Header row: `A5` at column N **and again** at the far right (Ctrl+→ along row 1); plus any `.` cells | `d6_duplicate_a5.png` |
| 4 | `data\raw\ods\system_mapping.xls` | Rows 1-9: title/contact rows above the real header | `d9_buried_header.png` |
| 5 | `data\raw\rtt\2023-04.zip` → extract, open the CSV | Same provider code repeating down column D (one row per commissioner) | `d3_commissioner_grain.png` |

Then: `git add docs/screenshots && git commit -m "Defect evidence pack" && git push`.

## Step 4 — Make the repo yours on GitHub (already public) (10 minutes)

The repo is created and pushed automatically. Your remaining polish:

1. Visit `https://github.com/sharia143/nhs-winter-pressure` → check the
   README renders, screenshots show.
2. Repo **Settings ▸ General**: add topics `nhs`, `data-engineering`,
   `forecasting`, `power-bi`, `duckdb` (About panel → gear icon).
3. Pin it on your profile: profile page → **Customize your pins**.

## Step 5 — Optional: publish the Power BI report online (15 minutes)

Needs a work/school Microsoft account (personal accounts can't use the free
Power BI service). If you have one:

1. Power BI Desktop → **Home ▸ Publish** → sign in → "My workspace".
2. In app.powerbi.com: open the report → **File ▸ Embed report ▸ Publish to
   web** *only if you are comfortable making it public*; otherwise share
   screenshots in the README (already done).

## Step 6 — CV and cover letter lines (5 minutes)

Copy from `README.md` § "Career artefacts" — the CV bullet there has the real
backtested MAE filled in by the pipeline. Update your CV master document and
the story bank.

## When new NHS data lands each month (10 minutes, monthly)

1. `python scripts/run_pipeline.py all` — downloads the new month, re-runs
   everything, refreshes exports (a "REVISED UPSTREAM" warning means NHS
   England re-issued an old file; the manifest records both hashes).
2. Open `WinterPressure.pbix` → **Home ▸ Refresh** → save → push.
3. Skim `reports/forecast-evaluation.md` — if a new winter has completed, the
   backtest tables now include it.
