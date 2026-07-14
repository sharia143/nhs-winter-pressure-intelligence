"""Refresh the auto-generated Headline section of README.md from current
outputs (kpi_summary.json + backtest metrics + fusion summary)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402

from nhswp import config  # noqa: E402


def main() -> None:
    kpi = json.loads((config.OUTPUTS_DIR / "kpi_summary.json").read_text())
    lines = []
    mk = kpi["latest_month"]
    lines.append(
        f"- **England Type-1 4-hour performance {mk//100}-{mk%100:02d}:** "
        f"{kpi['latest_type1_performance']:.1%} across {kpi['n_type1_trusts_ranked']} "
        f"Type-1 providers ({kpi['latest_att_type1']:,} Type-1 attendances)"
    )
    rmk = kpi["rtt_latest_month"]
    lines.append(
        f"- **RTT incomplete pathways {rmk//100}-{rmk%100:02d}:** "
        f"{kpi['rtt_waiting_list']:,.0f} waiting, {kpi['rtt_pct_within_18wk']:.1%} within 18 weeks"
    )
    eq = kpi["equity"]
    lines.append(
        f"- **Equity:** deprivation-performance correlation r = {eq['pearson_r']:.2f} "
        f"(95% CI {eq['ci95'][0]:.2f} to {eq['ci95'][1]:.2f}, n = {eq['n_trusts']})"
    )

    metrics_path = config.OUTPUTS_DIR / "model" / "backtest_metrics.parquet"
    if metrics_path.exists():
        m = pd.read_parquet(metrics_path)
        head = m[(m.metric == "breach_rate") & (m.horizon == 2)]
        for model_name, label in [("cluster_pooled", "cluster model"),
                                  ("seasonal_naive", "seasonal-naive baseline")]:
            rows = head[head.model == model_name]
            if rows.empty:
                continue
            per_winter = ", ".join(
                f"{r.mae*100:.1f}pp ({r.winter})" for r in rows.itertuples()
            )
            lines.append(f"- **8-week breach-rate MAE, {label}:** {per_winter}")
        cov_path = config.OUTPUTS_DIR / "model" / "interval_coverage.parquet"
        if cov_path.exists():
            cov = pd.read_parquet(cov_path)
            oos = cov[(cov.metric == "breach_rate")
                      & (cov.calibration.str.startswith("calibrated"))
                      & (cov.horizon == 2)]
            if not oos.empty:
                lines.append(
                    f"- **80% interval coverage (out-of-sample winter, h=2):** "
                    f"{oos.coverage.iloc[0]:.0%} — published as measured"
                )

    fusion_path = config.OUTPUTS_DIR / "fusion_summary.json"
    if fusion_path.exists():
        f = json.loads(fusion_path.read_text())
        lines.append(
            f"- **Hospital Under Pressure:** within-region nursing-vacancy vs breach "
            f"correlation r = {f['within_region_corr_same_month']:.2f} (same month), "
            f"r = {f['within_region_corr_lag3']:.2f} (3-month lead)"
        )

    readme = REPO_ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    block = "<!-- HEADLINE:START -->\n" + "\n".join(lines) + "\n<!-- HEADLINE:END -->"
    text = re.sub(r"<!-- HEADLINE:START -->.*?<!-- HEADLINE:END -->", block, text, flags=re.S)
    readme.write_text(text, encoding="utf-8")
    print("README headline updated:")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
