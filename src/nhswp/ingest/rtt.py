"""RTT monthly Full-CSV-extract parser.

Each month's zip holds one CSV at grain provider × commissioner × RTT part ×
treatment function, wide on weeks-waited bands ("Gt 00 To 01 Weeks SUM 1" …
"Gt 104 Weeks SUM 1"). We keep Part_2 (Incomplete Pathways) only and sum over
commissioners — a provider appears once per commissioner, so skipping that
aggregation would double-count massively (defect-log material).

Outputs two staging tables:
- rtt_summary: provider × month × treatment function — total incomplete,
  within-18-weeks, long-wait tallies (52/65/78/104+).
- rtt_bands:   provider × month × weeks-band (summed over treatment
  functions) — powers waiting-list distribution charts without exploding to
  tens of millions of rows.

Weeks bands were extended over the years (52+ → 104+ as long waits grew), so
band columns are discovered by regex, never enumerated.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from .. import config

BAND_RE = re.compile(r"^Gt (\d+) To (\d+) Weeks SUM 1$", re.IGNORECASE)
BAND_OPEN_RE = re.compile(r"^Gt (\d+) Weeks SUM 1$", re.IGNORECASE)

MONTH_NUM = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}


def _band_columns(columns) -> dict[str, tuple[int, int | None]]:
    """Map band column name -> (weeks_low, weeks_high); high None = open-ended."""
    out = {}
    for col in columns:
        m = BAND_RE.match(col.strip())
        if m:
            out[col] = (int(m.group(1)), int(m.group(2)))
            continue
        m = BAND_OPEN_RE.match(col.strip())
        if m:
            out[col] = (int(m.group(1)), None)
    return out


def parse_rtt_month(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse one monthly zip -> (summary df, bands df)."""
    with zipfile.ZipFile(path) as z:
        inner = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(inner) != 1:
            raise ValueError(f"expected exactly one CSV in {path.name}, found {inner}")
        with z.open(inner[0]) as f:
            df = pd.read_csv(
                io.TextIOWrapper(f, encoding="utf-8-sig"), dtype=str, low_memory=False
            )

    df.columns = [c.strip() for c in df.columns]
    bands = _band_columns(df.columns)
    if not bands:
        raise ValueError(f"RTT format drift: no weeks-band columns found in {path.name}")

    # Month from Period ("RTT-April-2023")
    period = str(df["Period"].iloc[0])
    m = re.search(r"([A-Za-z]+)-(\d{4})", period)
    if not m or m.group(1).upper() not in MONTH_NUM:
        raise ValueError(f"unparseable RTT Period {period!r} in {path.name}")
    mkey = config.month_key(int(m.group(2)), MONTH_NUM[m.group(1).upper()])

    part_col = "RTT Part Type" if "RTT Part Type" in df.columns else "RTT Part Description"
    incomplete = df[df[part_col].str.strip().str.lower().eq("part_2")].copy()
    if incomplete.empty:  # older files may spell the part differently
        incomplete = df[
            df["RTT Part Description"].str.strip().str.lower().eq("incomplete pathways")
        ].copy()
    if incomplete.empty:
        raise ValueError(f"no incomplete-pathway rows found in {path.name}")

    numeric_cols = [*bands, "Total", "Total All", "Patients with unknown clock start date"]
    numeric_cols = [c for c in numeric_cols if c in incomplete.columns]
    for col in numeric_cols:
        incomplete[col] = pd.to_numeric(
            incomplete[col].str.replace(",", ""), errors="coerce"
        )

    keys = ["Provider Org Code", "Provider Org Name", "Treatment Function Code",
            "Treatment Function Name"]
    grouped = incomplete.groupby(keys, as_index=False)[numeric_cols].sum(min_count=1).copy()

    within18_cols = [c for c, (lo, hi) in bands.items() if hi is not None and hi <= 18]

    def _over(threshold: int) -> pd.Series:
        cols = [c for c, (lo, hi) in bands.items() if lo >= threshold]
        return grouped[cols].sum(axis=1, min_count=1)

    band_sum = grouped[list(bands)].sum(axis=1, min_count=1)
    # Some eras leave the explicit 'Total' column blank and populate only
    # 'Total All' — the band sum (known clock starts) is then authoritative.
    explicit_total = grouped["Total"] if "Total" in grouped.columns else pd.Series(
        pd.NA, index=grouped.index
    )
    summary = pd.DataFrame({
        "month_key": mkey,
        "org_code_published": grouped["Provider Org Code"].str.strip(),
        "org_name": grouped["Provider Org Name"].str.strip(),
        "treatment_function_code": grouped["Treatment Function Code"].str.strip(),
        "treatment_function": grouped["Treatment Function Name"].str.strip(),
        "total_incomplete": explicit_total.fillna(band_sum),
        "total_incl_unknown_start": grouped.get("Total All"),
        "unknown_clock_start": grouped.get("Patients with unknown clock start date"),
        "within_18wk": grouped[within18_cols].sum(axis=1, min_count=1),
        "over_52wk": _over(52),
        "over_65wk": _over(65),
        "over_78wk": _over(78),
        "over_104wk": _over(104),
    })

    # The extract carries a publisher rollup row (C_999 / "Total") per
    # provider. Keep it in the summary (it is the publisher's own total,
    # useful for reconciliation) but exclude it from the bands aggregation or
    # every band would double-count.
    is_rollup = (
        incomplete["Treatment Function Code"].str.strip().eq("C_999")
        | incomplete["Treatment Function Name"].str.strip().str.lower().eq("total")
    )
    by_provider = incomplete[~is_rollup].groupby(
        ["Provider Org Code", "Provider Org Name"], as_index=False
    )[list(bands)].sum(min_count=1)
    melted = by_provider.melt(
        id_vars=["Provider Org Code", "Provider Org Name"],
        var_name="band_col", value_name="pathway_count",
    )
    melted["band_weeks_low"] = melted["band_col"].map(lambda c: bands[c][0])
    melted["band_weeks_high"] = melted["band_col"].map(lambda c: bands[c][1])
    bands_df = pd.DataFrame({
        "month_key": mkey,
        "org_code_published": melted["Provider Org Code"].str.strip(),
        "org_name": melted["Provider Org Name"].str.strip(),
        "band_weeks_low": melted["band_weeks_low"],
        "band_weeks_high": melted["band_weeks_high"].astype("Int64"),
        "pathway_count": melted["pathway_count"],
    })
    return summary, bands_df


def parse_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted((config.RAW_DIR / "rtt").glob("*.zip"))
    if not files:
        raise FileNotFoundError("no RTT raw files — run the download stage first")
    summaries, band_frames = [], []
    for path in files:
        s, b = parse_rtt_month(path)
        summaries.append(s)
        band_frames.append(b)
    return (
        pd.concat(summaries, ignore_index=True),
        pd.concat(band_frames, ignore_index=True),
    )
