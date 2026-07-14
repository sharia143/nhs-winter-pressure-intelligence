"""Suppression chokepoint + AmbSYS quirks."""
import pandas as pd
import pytest

from conftest import FIXTURES
from nhswp.ingest.common import check_schema, normalise_header, parse_count


def test_parse_count_handles_nhs_cell_realities():
    assert parse_count("1,234") == (1234.0, False)
    assert parse_count("") == (None, False)
    assert parse_count(None) == (None, False)
    assert parse_count("*") == (None, True)      # suppressed
    assert parse_count("-") == (None, True)      # suppressed/zero marker
    assert parse_count(" 42 ") == (42.0, False)


def test_check_schema_is_a_drift_canary():
    df = pd.DataFrame({"a": [1], "b": [2]})
    with pytest.raises(ValueError, match="missing"):
        check_schema(df, {"a": "i", "c": "i"}, "x")
    with pytest.raises(ValueError, match="unexpected"):
        check_schema(df, {"a": "i"}, "x")


def test_normalise_header_folds_ampersand_and_punctuation():
    assert normalise_header("A&E attendances Type 1") == "a and e attendances type 1"


def test_ambsys_duplicate_a5_and_dot_markers(monkeypatch, tmp_path):
    from nhswp import config
    from nhswp.ingest import ambsys

    monkeypatch.setattr(config, "RAW_DIR", FIXTURES)
    (FIXTURES / "ambulance").mkdir(exist_ok=True)
    (FIXTURES / "ambulance" / "ambsys.csv").write_text(
        (FIXTURES / "ambsys_sample.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    df = ambsys.parse_ambsys()
    assert "cat2_mean_sec" in df.columns
    assert df["month_key"].between(202401, 202512).all()
    # '.' markers must become NaN, not strings or zeros
    assert df["cat1_mean_sec"].dtype == float
