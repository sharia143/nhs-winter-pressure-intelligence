"""Context dataset parsers: IMD 2025, OHID trust catchments, HadUK weather,
NHS vacancy statistics.
"""
from __future__ import annotations

import re

import pandas as pd

from .. import config

# ---------------------------------------------------------------------------
# IMD 2025 (File 7): LSOA-level scores/ranks/deciles
# ---------------------------------------------------------------------------


def parse_imd() -> pd.DataFrame:
    df = pd.read_csv(config.RAW_DIR / "imd/imd2025_file7.csv")
    cols = {c.lower().strip(): c for c in df.columns}

    def find(*fragments: str) -> str:
        for lower, original in cols.items():
            if all(f in lower for f in fragments):
                return original
        raise ValueError(f"IMD format drift: no column matching {fragments}")

    out = pd.DataFrame({
        "lsoa_code": df[find("lsoa code")],
        "lsoa_name": df[find("lsoa name")],
        "lad_code": df[find("local authority district code")],
        "lad_name": df[find("local authority district name")],
        "imd_score": df[find("index of multiple deprivation", "score")],
        "imd_rank": df[find("index of multiple deprivation", "rank")],
        "imd_decile": df[find("index of multiple deprivation", "decile")],
    })
    return out


# ---------------------------------------------------------------------------
# OHID trust catchment populations (April 2026 edition, ODS spreadsheet)
# ---------------------------------------------------------------------------


def parse_catchment() -> pd.DataFrame:
    """Per-trust catchment population and catchment-weighted IMD score/rank.

    The OHID April-2026 workbook's Deprivation sheet (Table 6) provides, per
    trust × catchment year × admission type: Total catchment population, the
    catchment-weighted IMD score and the trust's IMD rank. The sheet opens
    with title/notes rows, so the header row is located by content ("Trust
    code") rather than assumed by position.

    Note the published table gives a weighted score, NOT an IMD-decile
    population profile — so Core20 share cannot be computed exactly from
    public aggregates. The equity view therefore uses the weighted IMD score,
    with the most-deprived quintile of trusts labelled as the Core20-proxy
    group (documented in the methodology).
    """
    path = config.RAW_DIR / "catchment/trust_catchment_2026.ods"
    raw = pd.read_excel(path, engine="odf", sheet_name="Deprivation", header=None)

    header_rows = raw.index[
        raw.apply(lambda r: r.astype(str).str.strip().eq("Trust code").any(), axis=1)
    ]
    if len(header_rows) == 0:
        raise ValueError("catchment format drift: no 'Trust code' header row in Deprivation sheet")
    hdr = header_rows[0]
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]

    def col(*fragments: str, exact: str | None = None) -> str:
        if exact is not None:
            for c in df.columns:
                if c.lower().strip() == exact:
                    return c
        for c in df.columns:
            if all(f in c.lower() for f in fragments):
                return c
        raise ValueError(
            f"catchment format drift: no column matching {fragments}; have {list(df.columns)}"
        )

    year_col = col("catchment year")
    adm_col = col("admission type")
    df = df[df[adm_col].astype(str).str.strip().str.lower() == "all admissions"]
    df["_year"] = pd.to_numeric(df[year_col], errors="coerce")
    df = df[df["_year"] == df["_year"].max()]

    out = pd.DataFrame({
        "org_code": df[col("trust code")].astype(str).str.strip(),
        "org_name_catchment": df[col("trust name")].astype(str).str.strip(),
        "catchment_population": pd.to_numeric(df[col("total catchment")], errors="coerce"),
        "imd_score": pd.to_numeric(df[col("imd score", exact="imd score")], errors="coerce"),
        "imd_rank": pd.to_numeric(df[col("imd rank")], errors="coerce"),
    })
    out = out.dropna(subset=["org_code", "catchment_population"])
    out = out[out["org_code"].str.len().between(3, 5)]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# HadUK-Grid England monthly mean temperature
# ---------------------------------------------------------------------------


def parse_weather() -> pd.DataFrame:
    path = config.RAW_DIR / "weather/haduk_england_tmean.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if ln.strip().lower().startswith("year"))
    rows = []
    for line in lines[header_idx + 1:]:
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        year = int(parts[0])
        for month, value in enumerate(parts[1:13], start=1):
            if value in ("---", "-99.9", "-99.90") or month > len(parts) - 1:
                continue
            try:
                rows.append({"month_key": config.month_key(year, month), "tmean_c": float(value)})
            except ValueError:
                continue
    df = pd.DataFrame(rows).drop_duplicates("month_key")
    # Anomaly vs month-of-year climatology over 1991-2020 (standard reference period)
    ref = df[(df.month_key >= 199101) & (df.month_key <= 202012)].copy()
    ref["moy"] = ref["month_key"] % 100
    normals = ref.groupby("moy")["tmean_c"].mean()
    df["moy"] = df["month_key"] % 100
    df["tmean_anomaly"] = df["tmean_c"] - df["moy"].map(normals)
    return df.drop(columns=["moy"])


# ---------------------------------------------------------------------------
# NHS vacancy statistics (ESR source data: region × staff group × month, WTE)
# ---------------------------------------------------------------------------


def parse_vacancy() -> pd.DataFrame:
    df = pd.read_excel(
        config.RAW_DIR / "vacancy/vacancy_tables.xlsx",
        sheet_name="ESR source data",
        header=0,
    )
    df.columns = [str(c).strip() for c in df.columns]
    # First row may repeat the header if the sheet has a spacer row
    if str(df.iloc[0, 0]).lower().startswith("published"):
        df = df.iloc[1:]
    rename = {
        "Published month": "published_month",
        "NWD Staff Group": "staff_group",
        "NHS England region": "region_raw",
        "Vacancy Wte": "vacancy_wte",
    }
    missing = [c for c in rename if c not in df.columns]
    if missing:
        raise ValueError(f"vacancy format drift: missing columns {missing}; have {list(df.columns)}")
    df = df.rename(columns=rename)
    df["published_month"] = pd.to_datetime(df["published_month"], errors="coerce")
    df = df.dropna(subset=["published_month"])
    df["month_key"] = df["published_month"].dt.year * 100 + df["published_month"].dt.month
    # "East of England (Y61)" -> name + code
    extracted = df["region_raw"].astype(str).str.extract(r"^(?P<region_name>.*?)\s*\((?P<region_code>Y\d\d)\)")
    df["region_name"] = extracted["region_name"]
    df["region_code"] = extracted["region_code"]
    df["vacancy_wte"] = pd.to_numeric(df["vacancy_wte"], errors="coerce")
    df = df.dropna(subset=["region_code"])
    return df[["month_key", "region_code", "region_name", "staff_group", "vacancy_wte"]]
