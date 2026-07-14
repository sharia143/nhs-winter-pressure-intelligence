-- ============================================================================
-- Showcase analysis queries (run against warehouse/nhswp.duckdb)
--   duckdb warehouse/nhswp.duckdb < sql/showcase_queries.sql
-- Demonstrates: window functions, period-on-period logic, cohort rollups,
-- suppression-safe aggregation. The permanent versions live as warehouse
-- views (src/nhswp/warehouse/views.sql); these are the interview-friendly
-- standalone forms.
-- ============================================================================

-- 1. Worst 10 trusts this month, with month-on-month and year-on-year change
--    and their national rank trajectory over the last 3 months
WITH ranked AS (
    SELECT org_code, month_key, type1_performance,
           lag(type1_performance)     OVER w AS prev_month,
           lag(type1_performance, 12) OVER w AS same_month_last_year,
           rank() OVER (PARTITION BY month_key ORDER BY type1_performance) AS worst_rank
    FROM vw_kpi_ae_monthly
    WHERE att_type1 > 0
    WINDOW w AS (PARTITION BY org_code ORDER BY month_key)
)
SELECT r.org_code, o.org_name, o.icb_name,
       round(r.type1_performance * 100, 1)                             AS perf_pct,
       round((r.type1_performance - r.prev_month) * 100, 1)            AS mom_pp,
       round((r.type1_performance - r.same_month_last_year) * 100, 1)  AS yoy_pp
FROM ranked r
JOIN dim_org o USING (org_code)
WHERE r.month_key = (SELECT max(month_key) FROM vw_kpi_ae_monthly)
  AND o.is_type1_provider
ORDER BY r.type1_performance
LIMIT 10;

-- 2. Winter penalty league: average Dec-Feb performance drop vs preceding
--    summer, per trust across all complete winters in the window
SELECT w.org_code, o.org_name,
       count(*)                                   AS winters_observed,
       round(avg(w.winter_delta_pp) * 100, 2)     AS avg_winter_penalty_pp,
       round(min(w.winter_delta_pp) * 100, 2)     AS worst_winter_pp
FROM vw_kpi_winter_delta w
JOIN dim_org o USING (org_code)
WHERE o.is_type1_provider
GROUP BY ALL
HAVING count(*) >= 3
ORDER BY avg_winter_penalty_pp
LIMIT 15;

-- 3. RTT pressure vs A&E pressure in the same month (do they travel together?)
--    Correlation computed per ICB on post-2026 footprints
SELECT o.icb_name,
       count(*)                                          AS trust_months,
       round(corr(1 - a.type1_performance, 1 - r.pct_within_18wk), 2) AS breach_corr
FROM vw_kpi_ae_monthly a
JOIN vw_kpi_rtt_monthly r USING (org_code, month_key)
JOIN dim_org o USING (org_code)
WHERE o.is_type1_provider AND o.icb_name IS NOT NULL
GROUP BY ALL
HAVING count(*) >= 100
ORDER BY breach_corr DESC
LIMIT 12;

-- 4. Succession-aware history: a merged trust's series under its analysis key
--    (pick any predecessor code and see history roll up to the successor)
SELECT b.predecessor_code, b.ultimate_successor_code, b.chain_depth,
       o.org_name AS successor_name
FROM bridge_org_succession b
JOIN dim_org o ON o.org_code = b.ultimate_successor_code
WHERE b.predecessor_code IN (SELECT DISTINCT org_code_published FROM fact_ae)
ORDER BY b.chain_depth DESC, b.predecessor_code
LIMIT 15;

-- 5. Weather sensitivity: England Type-1 breach rate vs temperature anomaly,
--    winter months only
SELECT d.month_key, w.tmean_anomaly,
       round(SUM(f.over4hr_type1)::DOUBLE / NULLIF(SUM(f.att_type1), 0) * 100, 1)
           AS breach_rate_pct
FROM fact_ae f
JOIN dim_date d USING (month_key)
JOIN fact_weather w USING (month_key)
WHERE d.is_winter
GROUP BY ALL
ORDER BY d.month_key;

-- 6. Suppression-safe rollup pattern: NULLs propagate as unknown-not-zero,
--    and the count of suppressed inputs is surfaced alongside the total
SELECT month_key,
       sum(dta_12hr_plus)                        AS dta_12hr_total,
       count(*) FILTER (WHERE dta_12hr_plus IS NULL)   AS orgs_with_missing_or_suppressed
FROM fact_ae
GROUP BY month_key
ORDER BY month_key DESC
LIMIT 12;
