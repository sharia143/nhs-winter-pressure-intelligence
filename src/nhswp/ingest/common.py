"""Shared ingest helpers: suppression handling, number parsing, schema contracts.

Suppression policy (single chokepoint, per the project guardrails): suppressed
source values become NULL **plus** a companion boolean flag column. NULL alone
is ambiguous (suppressed ≠ not submitted ≠ not applicable). Suppressed values
are never reconstructed by differencing from totals — that would defeat the
publisher's complementary suppression.
"""
from __future__ import annotations

import re

import pandas as pd

# Markers NHS publications use for disclosure control / not-applicable cells.
SUPPRESSION_MARKERS = {"*", "**", "-", "s", "supp", "low", "c"}


def parse_count(value) -> tuple[float | None, bool]:
    """Parse a numeric cell -> (value, was_suppressed).

    Handles thousands commas, stray whitespace, blank cells and suppression
    markers. Blank -> (None, False); marker -> (None, True).
    """
    if value is None:
        return None, False
    if isinstance(value, (int, float)):
        return (None, False) if pd.isna(value) else (float(value), False)
    text = str(value).strip()
    if text == "":
        return None, False
    if text.lower() in SUPPRESSION_MARKERS:
        return None, True
    text = text.replace(",", "")
    try:
        return float(text), False
    except ValueError:
        return None, True  # unparseable content in a numeric column ≈ redaction


def numericise(df: pd.DataFrame, columns: list[str], flag_suffix: str = "_suppressed",
               keep_flags: bool = False) -> pd.DataFrame:
    """Apply parse_count to columns; optionally keep per-column suppression flags."""
    for col in columns:
        parsed = df[col].map(parse_count)
        df[col] = parsed.map(lambda t: t[0])
        if keep_flags:
            df[col + flag_suffix] = parsed.map(lambda t: t[1])
    return df


def normalise_header(name: str) -> str:
    """Canonical form for column-name matching across format eras."""
    text = str(name).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def check_schema(df: pd.DataFrame, schema: dict[str, str], name: str) -> None:
    """Assert df contains exactly the contract columns (order-insensitive).

    Extra columns are allowed only if they end in '_suppressed'; missing
    columns raise — this is the drift canary firing.
    """
    missing = [c for c in schema if c not in df.columns]
    extra = [c for c in df.columns
             if c not in schema and not c.endswith("_suppressed")]
    problems = []
    if missing:
        problems.append(f"missing columns: {missing}")
    if extra:
        problems.append(f"unexpected columns: {extra}")
    if problems:
        raise ValueError(f"schema contract violated for {name}: " + "; ".join(problems))
