"""A&E parser tests over one trimmed real fixture per format era.

Eras covered:
- 2021-04: baseline 22-column layout (revised 12/05/2022 re-issue)
- 2024-09: the defect month — 5 trailing unnamed empty columns plus a stray
  empty column literally headed "a"
- 2026-06: current era (post-ECDS publication change)
"""
import pandas as pd
import pytest

from conftest import FIXTURES
from nhswp import config
from nhswp.ingest import ae


@pytest.mark.parametrize("month", ["2021-04", "2024-09", "2026-06"])
def test_parses_every_era_to_contract_schema(month):
    df, validation = ae.parse_ae_month(FIXTURES / f"ae_{month}.csv")
    assert set(config.SCHEMA_AE) <= set(df.columns)
    assert (df["month_key"] == int(month.replace("-", ""))).all()
    # TOTAL row must be excluded from the body...
    assert not df["org_code_published"].str.upper().eq("TOTAL").any()
    # ...but captured for validation
    assert "published_att_type1" in validation


def test_stray_artifact_columns_dropped_only_when_empty(tmp_path):
    src = (FIXTURES / "ae_2026-06.csv").read_text(encoding="utf-8").splitlines()
    # Add a stray named column WITH data -> must fail loudly (drift canary)
    bad = [src[0] + ",mystery"] + [line + ",42" for line in src[1:]]
    p = tmp_path / "bad.csv"
    p.write_text("\n".join(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        ae.parse_ae_month(p)


def test_counts_parse_with_commas_and_blanks(tmp_path):
    df, _ = ae.parse_ae_month(FIXTURES / "ae_2026-06.csv")
    assert df["att_type1"].dtype == float
    assert (df["att_type1"].dropna() >= 0).all()


def test_golden_type1_performance_matches_total_row():
    """The publisher's own TOTAL row is the golden value: our summed counts
    must reproduce it (fixture keeps the real TOTAL row, so compare on the
    full raw file where available)."""
    raw = config.RAW_DIR / "ae" / "2026-06.csv"
    if not raw.exists():
        pytest.skip("raw data not downloaded in this environment")
    df, validation = ae.parse_ae_month(raw)
    assert validation["total_row_matches"], validation
