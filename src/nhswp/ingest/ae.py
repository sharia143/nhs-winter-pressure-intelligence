"""A&E monthly CSV parser — era-aware.

One CSV per month (trust/site level). The header set has been stable across
the window in the *revised* CSVs, but mapping is done by name-synonym rules
rather than position so a renamed or reordered column fails loudly (drift
canary) instead of silently corrupting downstream KPIs.

Known structural facts handled here:
- Period cell format "MSitAE-APRIL-2021" → month key.
- A TOTAL row is appended at the bottom → dropped, but retained as the
  publisher's own national total for load-time validation.
- "Other A&E Department" is Type 3 in all but name.
- Counts arrive as strings with commas; blanks and markers → NULL (+ flag).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .. import config
from .common import check_schema, normalise_header, numericise

# Exact-match synonyms on normalised headers.
EXACT = {
    "period": "period",
    "org code": "org_code_published",
    "parent org": "parent_org",
    "org name": "org_name",
    "a and e attendances type 1": "att_type1",
    "a and e attendances type 2": "att_type2",
    "a and e attendances other a and e department": "att_other",
    "a and e attendances booked appointments type 1": "att_booked_type1",
    "a and e attendances booked appointments type 2": "att_booked_type2",
    "a and e attendances booked appointments other department": "att_booked_other",
    "attendances over 4hrs type 1": "over4hr_type1",
    "attendances over 4hrs type 2": "over4hr_type2",
    "attendances over 4hrs other department": "over4hr_other",
    "attendances over 4hrs booked appointments type 1": "over4hr_booked_type1",
    "attendances over 4hrs booked appointments type 2": "over4hr_booked_type2",
    "attendances over 4hrs booked appointments other department": "over4hr_booked_other",
    "emergency admissions via a and e type 1": "emadm_type1",
    "emergency admissions via a and e type 2": "emadm_type2",
    "emergency admissions via a and e other a and e department": "emadm_other",
    "other emergency admissions": "emadm_not_ae",
}

# Regex fallbacks for headers whose wording wobbles between files
# (e.g. "4-12 hs" vs "4-12 hrs" vs "4-12 hours" in the DTA columns).
PATTERNS = [
    (re.compile(r"4 ?12 h(rs|s|ours)? from dta"), "dta_4to12hr"),
    (re.compile(r"12 h(rs|s|ours)? from dta"), "dta_12hr_plus"),
    (re.compile(r"over 4 ?h(rs|ours)?.*type 1"), "over4hr_type1"),
    (re.compile(r"over 4 ?h(rs|ours)?.*type 2"), "over4hr_type2"),
]

COUNT_COLS = [c for c in config.SCHEMA_AE if c.startswith(("att_", "over4hr_", "dta_", "emadm_"))]

MONTH_NUM = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}


def _map_column(header: str, path: Path) -> str:
    norm = normalise_header(header)
    if norm in EXACT:
        return EXACT[norm]
    for pattern, target in PATTERNS:
        if pattern.search(norm):
            return target
    raise ValueError(
        f"A&E format drift: unmapped column {header!r} (normalised: {norm!r}) in {path.name}"
    )


def _month_key_from_period(period: str, path: Path) -> int:
    m = re.search(r"([A-Z]+)-(\d{4})", str(period).upper())
    if not m or m.group(1) not in MONTH_NUM:
        raise ValueError(f"unparseable Period value {period!r} in {path.name}")
    return config.month_key(int(m.group(2)), MONTH_NUM[m.group(1)])


def parse_ae_month(path: Path) -> tuple[pd.DataFrame, dict]:
    """Parse one monthly CSV -> (clean rows, validation record)."""
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=str, encoding="cp1252")

    # Some months ship stray artifact columns: trailing commas that pandas
    # reads as "Unnamed: N", and in Sep-2024 a column literally headed "a" —
    # all empty. Drop unmapped columns only when they are genuinely empty;
    # an unrecognised column WITH data is real drift and must fail loudly.
    def _is_mapped(header: str) -> bool:
        norm = normalise_header(header)
        return norm in EXACT or any(p.search(norm) for p, _ in PATTERNS)

    for col in [c for c in df.columns if not _is_mapped(str(c))]:
        if df[col].isna().all() or df[col].fillna("").str.strip().eq("").all():
            df = df.drop(columns=[col])

    df.columns = [_map_column(c, path) for c in df.columns]

    for col in ("period", "org_code_published", "org_name", "parent_org"):
        df[col] = df[col].fillna("").str.strip()

    # The publisher's national TOTAL row writes "TOTAL" into the Period column.
    is_total = (
        df["period"].str.upper().eq("TOTAL")
        | df["org_code_published"].str.upper().eq("TOTAL")
        | df["org_name"].str.upper().isin(["TOTAL", "ENGLAND"])
    )
    totals = df[is_total].copy()
    df = df[~is_total].copy()

    df["month_key"] = df["period"].map(lambda p: _month_key_from_period(p, path))
    df = df.drop(columns=["period"])
    totals["month_key"] = df["month_key"].iloc[0] if len(df) else None
    totals = totals.drop(columns=["period"])

    df = numericise(df, COUNT_COLS)

    validation = {"file": path.name, "month_key": int(df["month_key"].iloc[0])}
    if not totals.empty:
        totals = numericise(totals, COUNT_COLS)
        pub = float(totals["att_type1"].iloc[0] or 0)
        ours = float(df["att_type1"].sum())
        validation.update(
            published_att_type1=pub,
            summed_att_type1=ours,
            total_row_matches=abs(pub - ours) <= max(5.0, 0.001 * max(pub, 1.0)),
        )
    check_schema(df, config.SCHEMA_AE, path.name)
    return df, validation


def parse_all() -> tuple[pd.DataFrame, list[dict]]:
    files = sorted((config.RAW_DIR / "ae").glob("*.csv"))
    if not files:
        raise FileNotFoundError("no A&E raw files — run the download stage first")
    frames, validations = [], []
    for path in files:
        df, val = parse_ae_month(path)
        frames.append(df)
        validations.append(val)
    out = pd.concat(frames, ignore_index=True)
    # One row per org per month: some files repeat an org (site splits) — keep
    # published grain but guard against exact duplicates.
    out = out.drop_duplicates()
    return out, validations
