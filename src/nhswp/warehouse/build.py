"""Warehouse build: staging parquet -> DuckDB star schema + KPI views.

Always a full rebuild (seconds at this volume; a disposable artifact). Key
modelling rules:

- Every fact carries org_code_published (verbatim from the source file) AND
  org_code (the transitively-resolved ultimate successor) so trust mergers
  roll history up to today's organisations. KPI views group on org_code and
  recompute rates from summed counts.
- ICB reporting uses post-April-2026 footprints (System-Mapping file); the
  2022 footprints are retained as icb_code_2022 for the as-reported view.
- Forecast/cluster tables are attached when present (the forecast stage runs
  after the first warehouse build; re-running warehouse afterwards picks its
  outputs up).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from .. import config

SQL_DIR = Path(__file__).parent


def _attach_staging(con: duckdb.DuckDBPyConnection) -> list[str]:
    tables = []
    for pq in sorted(config.STAGING_DIR.glob("*.parquet")):
        name = f"stg_{pq.stem}"
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{pq.as_posix()}')")
        tables.append(name)
    # Optional post-forecast artifacts
    for pq in sorted((config.OUTPUTS_DIR / "model").glob("*.parquet")) if (
        config.OUTPUTS_DIR / "model"
    ).exists() else []:
        name = f"stg_{pq.stem}"
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{pq.as_posix()}')")
        tables.append(name)
    return tables


def run() -> str:
    config.WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    if config.WAREHOUSE_DB.exists():
        config.WAREHOUSE_DB.unlink()
    con = duckdb.connect(str(config.WAREHOUSE_DB))
    try:
        attached = _attach_staging(con)
        con.execute(f"SET VARIABLE ecds_break_key = {int(config.ECDS_BREAK_MONTH.replace('-', ''))}")
        ddl = (SQL_DIR / "ddl.sql").read_text(encoding="utf-8")
        con.execute(ddl)
        has_model = any(t == "stg_org_clusters" for t in attached)
        if has_model:
            con.execute((SQL_DIR / "model_tables.sql").read_text(encoding="utf-8"))
        views = (SQL_DIR / "views.sql").read_text(encoding="utf-8")
        con.execute(views)

        counts = con.execute(
            """
            SELECT table_name, estimated_size
            FROM duckdb_tables() WHERE database_name = current_database()
            ORDER BY table_name
            """
        ).fetchall()
        summary = ", ".join(f"{name}={rows}" for name, rows in counts)

        # Load-time validation: national Type-1 4-hour performance sanity band
        check = con.execute(
            """
            SELECT month_key,
                   1.0 - SUM(over4hr_type1)::DOUBLE / NULLIF(SUM(att_type1), 0) AS perf
            FROM fact_ae GROUP BY month_key ORDER BY month_key
            """
        ).fetchall()
        bad = [r for r in check if r[1] is not None and not (0.3 < r[1] < 1.0)]
        if bad:
            raise ValueError(f"national Type-1 performance outside sanity band: {bad[:5]}")
        return summary
    finally:
        con.close()
