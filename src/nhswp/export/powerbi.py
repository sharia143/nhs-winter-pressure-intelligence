"""Power BI export: star-schema CSVs (UTF-8 with BOM so Desktop autodetects
encoding; ISO dates). The report itself is hand-built once in Power BI
Desktop following powerbi/BUILD_GUIDE.md — report-definition generation was
deliberately rejected as an unverifiable-format risk; the model design and
DAX (powerbi/measures.dax) are the reviewable artefacts.
"""
from __future__ import annotations

import duckdb

from .. import config

EXPORTS = {
    # table/view in warehouse -> exported file stem
    "dim_org": "dim_org",
    "dim_date": "dim_date",
    "dim_icb": "dim_icb",
    "dim_trust_catchment": "dim_trust_catchment",
    "vw_kpi_ae_monthly": "fact_ae_monthly",
    "vw_kpi_rtt_monthly": "fact_rtt_monthly",
    "vw_kpi_winter_delta": "fact_winter_delta",
    "vw_equity": "dim_equity",
    "vw_trust_latest": "fact_trust_latest",
    "vw_ambulance_regional": "fact_ambulance_regional",
    "vw_vacancy_regional": "fact_vacancy_regional",
    "vw_ae_period_on_period": "fact_ae_period_on_period",
}

MODEL_EXPORTS = {
    "fact_forecast": "fact_forecast",
    "org_clusters": "dim_org_clusters",
    "backtest_metrics": "fact_backtest_metrics",
    "interval_coverage": "fact_interval_coverage",
}


def run() -> str:
    config.POWERBI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.WAREHOUSE_DB), read_only=True)
    written = []
    try:
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        targets = dict(EXPORTS)
        targets.update({k: v for k, v in MODEL_EXPORTS.items() if k in existing})
        for source, stem in targets.items():
            if source not in existing:
                continue
            out = config.POWERBI_DATA_DIR / f"{stem}.csv"
            con.execute(
                f"COPY (SELECT * FROM {source}) TO '{out.as_posix()}' "
                "(HEADER, DELIMITER ',')"
            )
            # Prepend UTF-8 BOM for Power BI Desktop autodetection
            raw = out.read_bytes()
            if not raw.startswith(b"\xef\xbb\xbf"):
                out.write_bytes(b"\xef\xbb\xbf" + raw)
            written.append(stem)
    finally:
        con.close()
    missing_model = [k for k in MODEL_EXPORTS if k not in written and k]
    note = f"{len(written)} CSVs -> powerbi/data"
    if "fact_forecast" not in written:
        note += " (forecast tables absent — run forecast + warehouse stages, then export again)"
    return note
