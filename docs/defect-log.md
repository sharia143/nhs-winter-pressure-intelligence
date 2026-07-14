# Defect log — the messy Excel reality of NHS statutory publications

Every defect below was found in the actual published files ingested by this
pipeline (raw copies under `data/raw/`, pinned by hash in
`data/raw/manifest.json`). For each: where it is, **how it silently corrupts
analysis if unhandled**, and how the pipeline survives it. This log is the
Phase-0 deliverable of the build spec and doubles as the parser test plan —
every entry has a corresponding fixture in `tests/fixtures/`.

> Screenshot instructions for the manual evidence pack are in
> `docs/MANUAL_STEPS.docx` (each defect lists its exact file/sheet/cells).

---

## D1 — The national TOTAL row lives *inside* the data rows (A&E monthly CSV)

**Where:** every monthly A&E CSV; last data row. Open `data/raw/ae/2026-06.csv`,
scroll to the final row: the `Period` column contains the literal string
`TOTAL` instead of `MSitAE-JUNE-2026`, and the row holds England's totals.

**Silent corruption:** any `GROUP BY` or sum over the raw rows counts England
twice — every national figure doubles, every regional share halves. Because
the row parses as perfectly valid numbers, nothing errors; dashboards are
simply wrong by a factor of ~2.

**Pipeline handling:** `ingest/ae.py` detects TOTAL markers in *three*
columns (Period / Org Code / Org name), removes the row, and keeps it as the
publisher's own golden total — load-time validation asserts our summed trust
counts reproduce it within 0.1% (`data/state/ae_validations.json`).

## D2 — Phantom columns and a column literally named "a" (A&E, Sep 2024)

**Where:** `data/raw/ae/2024-09.csv` header row: five trailing empty
`Unnamed:` columns from stray commas **plus a 28th column headed just `a`** —
someone's keyboard slip, published in national statistics and never
corrected.

**Silent corruption:** position-based loaders (`usecols=range(22)`, SQL
`COPY` with a fixed column list) either crash or — far worse — bind values to
the wrong columns for the whole month. A schema-locked pipeline that "helpfully"
ignores extras would also mask a *real* new column arriving.

**Pipeline handling:** columns are mapped by name-synonym rules, never
position; unmapped columns are dropped **only if entirely empty**, and an
unmapped column *with data* fails the run loudly (drift canary — covered by
`test_stray_artifact_columns_dropped_only_when_empty`).

## D3 — The RTT extract multiplies every provider by its commissioners

**Where:** any RTT Full CSV (e.g. `data/raw/rtt/2023-04.zip`): rows are
provider × **commissioner** × treatment function. A single provider/TF
appears dozens of times — once per commissioning organisation.

**Silent corruption:** the classic. Summing "provider rows" without grouping
inflates every waiting-list count by the provider's commissioner count
(10-50×). The numbers look plausible (they're big anyway); only reconciliation
against the publisher's own rollup reveals it.

**Pipeline handling:** `ingest/rtt.py` groups on provider × TF before any
measure is computed, and reconciles the per-TF sums against the publisher's
embedded `C_999` rollup row (±1%) in `test_bands_reconcile_with_publisher_rollup_row`.

## D4 — The publisher's rollup row hides among the treatment functions (RTT)

**Where:** same files: each provider carries a `C_999` / "Total" treatment
function row alongside the real specialties.

**Silent corruption:** summing across treatment functions without excluding
`C_999` doubles every count — and compounds with D3 into errors of 20-100×.

**Pipeline handling:** rollup rows are excluded from band aggregation and
flagged in the summary; the KPI views exclude `C_999` from all sums and the
tests reconcile TF sums against the rollup.

## D5 — The 'Total' column is blank in some eras (RTT)

**Where:** e.g. April 2023 extract: the explicit `Total` column is empty;
only `Total All` (including unknown clock starts) is populated. Other eras
populate both.

**Silent corruption:** a loader that trusts the `Total` column produces NULL
waiting lists for entire years — or worse, a `fillna(0)` "cleanup" turns the
national waiting list into zero and every derived per-capita metric with it.

**Pipeline handling:** `total_incomplete` falls back to the weeks-band sum
(known clock starts) when the explicit column is blank; both totals are kept
and documented in the data dictionary.

## D6 — A duplicated column name in AmbSYS, and "." as the missing marker

**Where:** `data/raw/ambulance/ambsys.csv` header: column `A5` appears
**twice** (positions 14 and 153). Missing values throughout are `.`, not
blank.

**Silent corruption:** dict-style readers keep only the *last* `A5`,
silently replacing call-answer data with whatever the stray duplicate holds.
The `.` markers coerce whole metric columns to strings — means and centiles
then concatenate instead of aggregate, or a careless `replace('.', 0)`
invents fake zero response times.

**Pipeline handling:** `ingest/ambsys.py` selects metrics by explicit
A-code list from the AmbSYS specification (duplicates never collide), and `.`
parses to NULL with the column forced to float64 (test-covered).

## D7 — File names and URLs are unstable; whole years get silently re-issued

**Where:** NHS England upload URLs embed random hash suffixes
(`June-2026-CSV-Wfg38l.csv`) and change on every revision. The **entire
2021-22 A&E year was re-issued on 12 May 2022**; November 2025's CSV switched
naming convention mid-year (`Monthly-AE-Nov-25-CSV-revised.csv`) — in the
same month as the ECDS methodology change.

**Silent corruption:** hardcoded URLs keep fetching a stale pre-revision
file (or 404 and a retry fetches nothing) — the analysis then mixes revised
and unrevised months without any indication.

**Pipeline handling:** the stable yearly archive *pages* are scraped for
current hrefs at run time; `-revised` files are preferred; every download is
hashed into `manifest.json`, and a changed upstream hash raises a
"REVISED UPSTREAM" warning rather than silently overwriting.

## D8 — The ECDS methodology change (November 2025) breaks the time series

**Where:** all A&E months from `2025-11` onward are derived from ECDS under
NHS England's published methodology change; the publication page carries the
change note, and several trusts show step-changes.

**Silent corruption:** a forecaster trained across the break attributes the
step to seasonality or trend and projects it forward; year-on-year
comparisons spanning the break quietly compare different measurement systems.

**Pipeline handling:** `dim_date.methodology_break` flags affected months;
the forecast re-levels pre-break history only when ≥3 post-break observations
make the shift estimable (net of normal YoY drift), and winter 2025-26
backtest results are reported as their own — visibly degraded — row in
`reports/forecast-evaluation.md`.

## D9 — Reference workbooks bury the header under title rows (.xls, merged cells)

**Where:** `data/raw/ods/system_mapping.xls` (provider→ICB, updated 16 Apr
2026) and `trust_icb_attribution.xls`: header at spreadsheet row 8, preceded
by title/contact/blank rows in merged cells, `.xls` (1997 format). The OHID
catchment ODS file similarly opens every sheet with two narrative rows, and
its Deprivation sheet publishes a *weighted score* — not the decile profile
an equity analysis would want.

**Silent corruption:** `read_excel(header=0)` returns titles as column
names; a positional `skiprows=7` breaks the day a note is added. Assuming
decile-profile data exists leads to silently fabricating Core20 shares.

**Pipeline handling:** header rows are located by content (`"Trust code"` /
`"Code"`), not position; the equity view uses the published weighted IMD
score and labels the most-deprived quintile of trusts as an explicit
**Core20 proxy** — documented as a proxy, never presented as the real
Core20 measure.

## D10 — Organisations merge mid-window; ICBs merged in April 2026

**Where:** ODS succession file (`data/raw/ods/succ.csv`) chains trust codes
through mergers; **12 ICB codes closed and 6 opened in April 2026** (e.g.
Frimley split across three successors). The A&E files keep publishing history
under the old codes.

**Silent corruption:** unmapped, a merged trust's series looks like one org
collapsing to zero while another "explodes" — the forecast reads both as
massive real shifts; ICB-level maps drawn on 2022 codes simply lose 12
systems.

**Pipeline handling:** `bridge_org_succession` resolves succession chains
transitively (depth-capped, splits flagged); every fact carries both the
published code and the rolled-up analysis code; ICB reporting uses the
April-2026 System-Mapping footprints with the 2022 mapping retained for the
as-reported view.

## D11 — The 12-hour column measures DTA, not arrival (naming trap)

**Where:** A&E CSV column `Patients who have waited 12+ hrs from DTA to
admission` — including the typo'd sibling `…4-12 hs from DTA…` ("hs").

**Silent corruption:** conflating this with the (much larger) ECDS
12-hours-from-arrival measure understates the problem by an order of
magnitude in commentary — a credibility-ending mistake in front of an NHS
panel. The "hs" typo also breaks exact-string column matching if the
publisher ever fixes it.

**Pipeline handling:** the measure is named `dta_12hr_plus` end-to-end and
labelled "12-hour DTA waits" in every artefact; the header is matched by
regex tolerant of `hs/hrs/hours`.

---

### Suppression discipline (cross-cutting)

Suppressed or redacted cells (`*`, `-`, markers documented per source) parse
to **NULL plus a suppression flag** through one chokepoint
(`ingest/common.py::parse_count`). Suppressed values are never reconstructed
by differencing totals — that would defeat the publisher's complementary
suppression. `- ' denotes zero` in the vacancy workbook vs `-` as suppression
elsewhere is exactly why the marker set is per-source, not global.
