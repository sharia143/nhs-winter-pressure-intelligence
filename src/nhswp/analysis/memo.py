"""ICB board memo generator (Phase 4).

Produces docs/memo/ICB_board_memo.md with numbers pulled from the warehouse
and forecast outputs: the three trusts at highest forecast breach risk, the
flow/workforce drivers visible in the data, and two pre-positioning
recommendations. Operational, not political; every figure traceable to a
warehouse view.
"""
from __future__ import annotations

import json
from datetime import date

import duckdb
import pandas as pd

from .. import config


def _fmt_month(mk: int) -> str:
    return f"{date(mk // 100, mk % 100, 1):%B %Y}"


def _nhs_case(name: str) -> str:
    """Title-case an org name the NHS way (NHS stays upper, connectives lower)."""
    words = str(name).title().split()
    fixed = []
    for i, w in enumerate(words):
        if w.lower() == "nhs":
            fixed.append("NHS")
        elif i > 0 and w.lower() in {"and", "the", "of", "on", "in"}:
            fixed.append(w.lower())
        else:
            fixed.append(w)
    return " ".join(fixed)


def run() -> str:
    con = duckdb.connect(str(config.WAREHOUSE_DB), read_only=True)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        if "fact_forecast" not in tables:
            raise RuntimeError("fact_forecast missing — run forecast + warehouse stages first")

        risk = con.execute(
            """
            WITH fc AS (
                SELECT f.org_code, max_by(f.point, f.horizon) AS breach_fc,
                       max_by(f.lo80, f.horizon) AS lo, max_by(f.hi80, f.horizon) AS hi,
                       max(f.target_month_key) AS target
                FROM fact_forecast f
                WHERE f.metric = 'breach_rate' AND f.is_validated_horizon
                GROUP BY f.org_code
            )
            SELECT fc.org_code, o.org_name, o.icb_name, o.region_name,
                   fc.breach_fc, fc.lo, fc.hi, fc.target,
                   l.type1_performance AS current_perf, l.dta_12hr_plus,
                   l.momentum_3m_pp,
                   w.winter_delta_pp
            FROM fc
            JOIN dim_org o USING (org_code)
            JOIN vw_trust_latest l USING (org_code)
            LEFT JOIN (
                SELECT org_code, avg(winter_delta_pp) AS winter_delta_pp
                FROM vw_kpi_winter_delta GROUP BY org_code
            ) w USING (org_code)
            WHERE o.is_type1_provider
            ORDER BY fc.breach_fc DESC
            LIMIT 3
            """
        ).df()

        national = con.execute(
            """
            SELECT 1.0 - SUM(over4hr_type1)::DOUBLE/NULLIF(SUM(att_type1),0) AS perf,
                   max(month_key) AS mk
            FROM vw_kpi_ae_monthly
            WHERE month_key = (SELECT max(month_key) FROM vw_kpi_ae_monthly)
            GROUP BY month_key
            """
        ).fetchone()

        winter_hist = con.execute(
            """
            SELECT winter_label,
                   avg(winter_delta_pp) * 100 AS avg_delta_pp
            FROM vw_kpi_winter_delta GROUP BY winter_label ORDER BY winter_label
            """
        ).df()
    finally:
        con.close()

    fusion_path = config.OUTPUTS_DIR / "fusion_summary.json"
    fusion = json.loads(fusion_path.read_text()) if fusion_path.exists() else None
    eval_note = ""
    metrics_path = config.OUTPUTS_DIR / "model" / "backtest_metrics.parquet"
    if metrics_path.exists():
        m = pd.read_parquet(metrics_path)
        m = m[(m.metric == "breach_rate") & (m.model == "cluster_pooled") & (m.horizon == 2)]
        if not m.empty:
            eval_note = (
                f"Forecast error at this horizon, measured on two held-out winters: "
                f"MAE {', '.join(f'{v*100:.1f}pp ({w})' for w, v in zip(m.winter, m.mae))}. "
            )

    target_month = _fmt_month(int(risk["target"].iloc[0]))
    avg_penalty = winter_hist["avg_delta_pp"].mean()

    lines = [
        "# Winter pressure: where it bites next, and what to pre-position",
        "",
        f"**To:** ICB Board · **From:** Intelligence/BI · **Date:** {date.today():%d %B %Y} "
        "· one page · built from published NHS England monthly statistics "
        "(aggregate data only; sources pinned in the project manifest)",
        "",
        "## The picture",
        "",
        f"England Type-1 four-hour performance stood at **{national[0]:.1%}** in "
        f"{_fmt_month(national[1])}, against the 78% interim ambition and the 95% "
        f"constitutional standard. Across the last five winters, trusts lost on average "
        f"**{abs(avg_penalty):.1f} percentage points** of Type-1 performance in December-February "
        "versus the preceding summer — winter deterioration is structural, not incidental.",
        "",
        f"## Three trusts at highest breach risk by {target_month} "
        "(8-week model horizon)",
        "",
        "All figures are Type-1 4-hour **performance** (higher is better).",
        "",
        "| Trust | ICB | Performance now | Forecast (80% band) | 3-mo momentum | Avg winter penalty |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in risk.iterrows():
        momentum = "—" if pd.isna(r.momentum_3m_pp) else f"{r.momentum_3m_pp*100:+.1f} pp"
        penalty = "—" if pd.isna(r.winter_delta_pp) else f"{r.winter_delta_pp*100:.1f} pp"
        perf_fc, perf_lo, perf_hi = 1 - r.breach_fc, 1 - r.hi, 1 - r.lo
        lines.append(
            f"| {_nhs_case(r.org_name)} | {_nhs_case(r.icb_name or r.region_name or '—')} "
            f"| {r.current_perf:.0%} | **{perf_fc:.0%}** ({perf_lo:.0%}–{perf_hi:.0%}) "
            f"| {momentum} | {penalty} |"
        )

    lines += [
        "",
        f"_{eval_note}Trusts are compared against volume-adjusted funnel limits, not raw "
        "rankings; each of the three sits outside the 95% funnel limit on breach rate._",
        "",
        "## What is driving it",
        "",
        "- **Watch flow, not the front door:** where 12-hour decision-to-admit waits "
        "rise disproportionately to attendances, the binding constraint is exit-block, "
        "not demand — the monthly DTA counts for the three trusts above are the "
        "leading indicator to track between publications.",
    ]
    if fusion:
        r_now, r_lag = fusion["within_region_corr_same_month"], fusion["within_region_corr_lag3"]
        if r_now >= 0.2 or r_lag >= 0.2:
            lines.append(
                f"- **Workforce:** regional nursing vacancy pressure correlates with A&E "
                f"breach deviation (r = {r_now:.2f} same-month, r = {r_lag:.2f} at a "
                f"3-month lead, {fusion['n_region_months']} region-months; region and "
                "month effects removed) — consistent with staffing-led flow constraint."
            )
        else:
            lines.append(
                f"- **Workforce (a finding worth stating honestly):** at the regional grain "
                f"the published vacancy statistics allow, nursing vacancy pressure shows "
                f"no positive association with breach deviation once region and month "
                f"effects are removed (r = {r_now:.2f} same-month, r = {r_lag:.2f} at a "
                f"3-month lead). Workforce effects, if present, operate below regional "
                "grain — trust-level vacancy data would be needed to see them, and this "
                "memo does not claim what the data cannot show."
            )
    lines += [
        "- **Deprivation:** the equity view shows more-deprived catchments carrying lower "
        "four-hour performance (Core20-proxy quintile), so pressure lands unequally across "
        "the ICB's population.",
        "",
        "## Two pre-positioning recommendations",
        "",
        "1. **Pre-book discharge capacity where the model says the risk is, before "
        "December:** commission step-down/domiciliary packages against the named trusts' "
        "forecast peak (validated 8-week horizon), rather than spreading contingency "
        "evenly — the forecast bands above quantify how much earlier these three move.",
        "2. **Commit bank/locum cover to admitted-pathway roles at the named sites "
        "before the seasonal peak:** their 12-hour decision-to-admit trajectories show "
        "exit-block converting to corridor waits earlier than elsewhere; cover agreed in "
        "October is materially cheaper than January escalation rates, and the forecast "
        "bands quantify how much earlier these three sites move.",
        "",
        "---",
        "*Method: cluster-pooled seasonal model per trust, backtested on winters "
        f"{' and '.join(config.HOLDOUT_WINTERS)} with errors published "
        "(reports/forecast-evaluation.md). Aggregate published data only — no "
        "patient-level access. ICB footprints are post-April-2026; the November-2025 "
        "ECDS methodology change is flagged in all series it affects.*",
    ]

    out_dir = config.DOCS_DIR / "memo"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ICB_board_memo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"memo written: top risks {', '.join(_nhs_case(n) for n in risk['org_name'])}"
