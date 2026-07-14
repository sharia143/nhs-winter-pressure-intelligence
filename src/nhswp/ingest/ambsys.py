"""AmbSYS consolidated CSV parser.

Single back-series file (Aug 2017 → present), grain org × month, ~150
A-coded metric columns. Quirks handled:
- "." marks not-collected/NA (metrics phased in over the years).
- The published header repeats column name "A5" (a genuine data defect —
  pandas mangles the duplicate to "A5.1"; we keep the first).
- Rows exist for England ("Eng"), regions, and individual ambulance services;
  services are kept, England is kept separately for validation, region
  aggregate rows are dropped (regional views recompute from services).
- Response-time metrics are in seconds.
"""
from __future__ import annotations

import pandas as pd

from .. import config


def parse_ambsys() -> pd.DataFrame:
    path = config.RAW_DIR / "ambulance/ambsys.csv"
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    keep = ["Year", "Month", "Region", "Org Code", "Org Name"]
    metric_cols = [c for c in config.AMBSYS_METRICS if c in df.columns]
    missing = sorted(set(config.AMBSYS_METRICS) - set(metric_cols))
    if missing:
        raise ValueError(f"AmbSYS format drift: expected metric columns missing: {missing}")
    df = df[keep + metric_cols].copy()

    df["month_key"] = df["Year"].astype(int) * 100 + df["Month"].astype(int)

    org = df["Org Code"].str.strip()
    is_england = org.eq("Eng")
    # Region aggregate rows carry region-style codes (Y56…Y63) or repeat the
    # region token in Org Code; service rows carry 3-char ODS trust codes.
    is_region_row = org.str.match(r"^Y\d\d$") | (org == df["Region"].str.strip()) & ~is_england

    out = df[~is_region_row | is_england].copy()
    out["is_england"] = is_england[~is_region_row | is_england]

    for raw_code, name in config.AMBSYS_METRICS.items():
        out[name] = pd.to_numeric(out[raw_code].replace(".", ""), errors="coerce").astype(float)
    out = out.drop(columns=list(config.AMBSYS_METRICS))

    out = out.rename(columns={
        "Org Code": "org_code_published", "Org Name": "org_name", "Region": "region",
    })
    out = out[["month_key", "org_code_published", "org_name", "region", "is_england",
               *config.AMBSYS_METRICS.values()]]
    return out.reset_index(drop=True)
