"""RTT parser tests on a trimmed real fixture (2 providers, all their
commissioner rows — exercising the commissioner-summing that prevents
double-counting)."""
import pandas as pd

from conftest import FIXTURES
from nhswp.ingest import rtt


def test_parse_month_sums_over_commissioners():
    summary, bands = rtt.parse_rtt_month(FIXTURES / "rtt_2023-04.zip")
    # one row per provider x treatment function
    assert not summary.duplicated(
        ["org_code_published", "treatment_function_code"]
    ).any()
    assert (summary["month_key"] == 202304).all()
    # within-18-weeks can never exceed the total
    ok = summary.dropna(subset=["within_18wk", "total_incomplete"])
    assert (ok["within_18wk"] <= ok["total_incomplete"] + 1e-6).all()


def test_bands_reconcile_with_publisher_rollup_row():
    summary, bands = rtt.parse_rtt_month(FIXTURES / "rtt_2023-04.zip")
    band_total = bands.groupby("org_code_published")["pathway_count"].sum()
    # The publisher's own C_999 rollup row is the golden value per provider
    rollup = summary[summary["treatment_function_code"] == "C_999"].set_index(
        "org_code_published"
    )["total_incomplete"]
    joined = pd.concat([band_total.rename("bands"), rollup.rename("rollup")], axis=1).dropna()
    assert len(joined) > 0
    assert ((joined["bands"] - joined["rollup"]).abs()
            <= 0.01 * joined["rollup"].clip(lower=100)).all()
    # And per-TF rows (excluding the rollup) must sum to the rollup too
    tf_sum = summary[summary["treatment_function_code"] != "C_999"].groupby(
        "org_code_published"
    )["total_incomplete"].sum()
    joined2 = pd.concat([tf_sum.rename("tf"), rollup.rename("rollup")], axis=1).dropna()
    assert ((joined2["tf"] - joined2["rollup"]).abs()
            <= 0.01 * joined2["rollup"].clip(lower=100)).all()


def test_open_ended_top_band_kept():
    _, bands = rtt.parse_rtt_month(FIXTURES / "rtt_2023-04.zip")
    top = bands[bands["band_weeks_high"].isna()]
    assert (top["band_weeks_low"] == 104).all() and len(top) > 0
