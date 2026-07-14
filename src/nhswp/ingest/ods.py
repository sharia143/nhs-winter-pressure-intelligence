"""Organisation reference ingestion: trusts, ICBs, succession, trust→ICB maps.

Sources:
- etr / ect getReport CSVs — headerless, 27 columns (ODS standard layout);
  col 1 org code, 2 name, 3 national grouping (NHSE region), 4 high-level
  health geography, 10 postcode, 11 open date, 12 close date.
- eother getReport CSV — strategic partnerships; ICBs are the rows whose name
  contains "INTEGRATED CARE BOARD" (the ORD API's RO318 filter was
  unreachable from this network, so the file route is used).
- succ getReport CSV — predecessor → successor code mappings with effective
  dates; chains are resolved transitively at warehouse-build time.
- System-Mapping.xls (NHS England, Apr 2026) — provider → ICB on
  post-April-2026 ICB footprints.
- Trust-ICB-Attribution-File.xls (Jun 2022) — provider → ICB on the original
  July-2022 ICB footprints (period-accurate view before the 2026 mergers).
"""
from __future__ import annotations

import pandas as pd

from .. import config

ETR_COLS = {
    0: "org_code",
    1: "org_name",
    2: "national_grouping",
    3: "high_level_geography",
    9: "postcode",
    10: "open_date",
    11: "close_date",
}

# ODS national grouping codes -> NHS England region names
REGION_NAMES = {
    "Y56": "London",
    "Y58": "South West",
    "Y59": "South East",
    "Y60": "Midlands",
    "Y61": "East of England",
    "Y62": "North West",
    "Y63": "North East and Yorkshire",
}


def _read_ods_csv(path, usecols: dict[int, str]) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    df = df[list(usecols)].rename(columns=usecols)
    for col in ("open_date", "close_date"):
        if col in df.columns:
            df[col] = df[col].replace("", pd.NA)
    return df


def parse_org_reference() -> pd.DataFrame:
    """All NHS trusts + care trusts ever registered, with region and dates."""
    frames = []
    for report, org_type in (("etr", "NHS Trust"), ("ect", "Care Trust")):
        df = _read_ods_csv(config.RAW_DIR / f"ods/{report}.csv", ETR_COLS)
        df["org_type"] = org_type
        frames.append(df)
    orgs = pd.concat(frames, ignore_index=True)
    orgs["region_name"] = orgs["national_grouping"].map(REGION_NAMES)
    orgs["is_current"] = orgs["close_date"].isna()
    return orgs


def parse_icbs() -> pd.DataFrame:
    """ICBs (incl. pre-merger codes) from the eother strategic-partnerships file."""
    df = _read_ods_csv(config.RAW_DIR / "ods/eother.csv", ETR_COLS)
    icbs = df[df["org_name"].str.contains("INTEGRATED CARE BOARD", na=False)].copy()
    icbs = icbs.rename(columns={"org_code": "icb_code", "org_name": "icb_name"})
    icbs["is_current"] = icbs["close_date"].isna()
    return icbs[["icb_code", "icb_name", "open_date", "close_date", "is_current"]]


def parse_succession() -> pd.DataFrame:
    """Predecessor -> successor code mappings from the succ report."""
    df = pd.read_csv(
        config.RAW_DIR / "ods/succ.csv", header=None, dtype=str, keep_default_na=False
    )
    df = df.rename(columns={0: "predecessor_code", 1: "successor_code", 3: "effective_date"})
    return df[["predecessor_code", "successor_code", "effective_date"]]


def _parse_attribution_xls(path, vintage: str) -> pd.DataFrame:
    """Both attribution workbooks share the layout: title rows, then a header
    row (Code / Name / ICB Code / ICB Name / Region Name) in column B."""
    raw = pd.read_excel(path, sheet_name="ICB Mapping", header=None, dtype=str)
    header_row = raw.index[raw.iloc[:, 1].eq("Code")][0]
    df = raw.iloc[header_row + 1:, 1:6].copy()
    df.columns = ["org_code", "org_name", "icb_code", "icb_name", "region_name"]
    df = df.dropna(subset=["org_code"])
    df["mapping_vintage"] = vintage
    return df


def parse_org_icb_map() -> pd.DataFrame:
    """Provider → ICB, both vintages (2022 footprints and post-2026-merger)."""
    current = _parse_attribution_xls(
        config.RAW_DIR / "ods/system_mapping.xls", vintage="2026-04"
    )
    original = _parse_attribution_xls(
        config.RAW_DIR / "ods/trust_icb_attribution.xls", vintage="2022-07"
    )
    return pd.concat([current, original], ignore_index=True)


def run_all() -> dict[str, pd.DataFrame]:
    return {
        "org_reference": parse_org_reference(),
        "org_icbs": parse_icbs(),
        "org_succession": parse_succession(),
        "org_icb_map": parse_org_icb_map(),
    }
