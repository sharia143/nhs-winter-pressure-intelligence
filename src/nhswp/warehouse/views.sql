-- ============================================================================
-- KPI view layer. All views group on the rolled-up analysis key (org_code)
-- and recompute rates from summed counts — never averages of averages.
-- Percentages live here, not in fact tables.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- A&E monthly KPIs per analysis org
-- ----------------------------------------------------------------------------
CREATE VIEW vw_kpi_ae_monthly AS
SELECT f.org_code,
       d.month_key, d.month_start, d.fy, d.month_name, d.days_in_month,
       d.is_winter, d.winter_label, d.is_summer, d.methodology_break,
       SUM(f.att_type1)  AS att_type1,
       SUM(f.att_type2)  AS att_type2,
       SUM(f.att_other)  AS att_other,
       SUM(f.att_type1) + SUM(f.att_type2) + SUM(f.att_other) AS att_all,
       SUM(f.over4hr_type1) AS over4hr_type1,
       SUM(f.over4hr_type1) + SUM(f.over4hr_type2) + SUM(f.over4hr_other) AS over4hr_all,
       SUM(f.dta_4to12hr)   AS dta_4to12hr,
       SUM(f.dta_12hr_plus) AS dta_12hr_plus,
       SUM(f.emadm_type1) + SUM(f.emadm_type2) + SUM(f.emadm_other) AS emadm_via_ae,
       1.0 - SUM(f.over4hr_type1)::DOUBLE / NULLIF(SUM(f.att_type1), 0) AS type1_performance,
       1.0 - (SUM(f.over4hr_type1) + SUM(f.over4hr_type2) + SUM(f.over4hr_other))::DOUBLE
           / NULLIF(SUM(f.att_type1) + SUM(f.att_type2) + SUM(f.att_other), 0) AS alltype_performance,
       SUM(f.att_type1)::DOUBLE / any_value(d.days_in_month) AS att_type1_per_day,
       (1.0 - SUM(f.over4hr_type1)::DOUBLE / NULLIF(SUM(f.att_type1), 0)) >= 0.95 AS type1_meets_95,
       (1.0 - SUM(f.over4hr_type1)::DOUBLE / NULLIF(SUM(f.att_type1), 0)) >= 0.78 AS type1_meets_interim
FROM fact_ae f
JOIN dim_date d USING (month_key)
GROUP BY ALL;

-- ----------------------------------------------------------------------------
-- RTT monthly KPIs per analysis org (all treatment functions combined).
-- Any publisher 'Total' treatment-function rows are excluded before summing.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_kpi_rtt_monthly AS
SELECT r.org_code,
       d.month_key, d.month_start, d.fy, d.is_winter, d.winter_label,
       SUM(r.total_incomplete)   AS total_incomplete,
       SUM(r.within_18wk)        AS within_18wk,
       SUM(r.over_52wk)          AS over_52wk,
       SUM(r.over_65wk)          AS over_65wk,
       SUM(r.over_78wk)          AS over_78wk,
       SUM(r.over_104wk)         AS over_104wk,
       SUM(r.within_18wk)::DOUBLE / NULLIF(SUM(r.total_incomplete), 0) AS pct_within_18wk,
       10000.0 * SUM(r.total_incomplete) / NULLIF(any_value(c.catchment_population), 0)
           AS waiting_per_10k_catchment
FROM fact_rtt r
JOIN dim_date d USING (month_key)
LEFT JOIN dim_trust_catchment c USING (org_code)
WHERE NOT (r.treatment_function_code ILIKE 'C_999%'
           OR r.treatment_function ILIKE 'total%')
GROUP BY ALL;

-- ----------------------------------------------------------------------------
-- Winter delta: each winter (Dec-Feb) vs the *preceding* summer (Jun-Aug).
-- Rates recomputed from summed counts within each window.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_kpi_winter_delta AS
WITH winter AS (
    SELECT org_code, winter_label,
           SUM(att_type1) AS att, SUM(over4hr_type1) AS o4,
           SUM(dta_12hr_plus) AS dta12,
           SUM(att_type1_per_day * days_in_month) / SUM(days_in_month) AS att_per_day
    FROM vw_kpi_ae_monthly
    WHERE is_winter AND winter_label IS NOT NULL
    GROUP BY ALL
), summer AS (
    SELECT org_code, month_key // 100 AS yr,
           SUM(att_type1) AS att, SUM(over4hr_type1) AS o4,
           SUM(dta_12hr_plus) AS dta12,
           SUM(att_type1_per_day * days_in_month) / SUM(days_in_month) AS att_per_day
    FROM vw_kpi_ae_monthly
    WHERE is_summer
    GROUP BY ALL
)
SELECT w.org_code, w.winter_label,
       1.0 - w.o4::DOUBLE / NULLIF(w.att, 0)                     AS winter_type1_performance,
       1.0 - s.o4::DOUBLE / NULLIF(s.att, 0)                     AS summer_type1_performance,
       (1.0 - w.o4::DOUBLE / NULLIF(w.att, 0))
         - (1.0 - s.o4::DOUBLE / NULLIF(s.att, 0))               AS winter_delta_pp,
       w.att_per_day AS winter_att_per_day,
       s.att_per_day AS summer_att_per_day,
       w.att_per_day / NULLIF(s.att_per_day, 0) - 1.0            AS winter_demand_uplift,
       w.dta12 AS winter_dta_12hr, s.dta12 AS summer_dta_12hr
FROM winter w
JOIN summer s
  ON s.org_code = w.org_code
 AND s.yr = CAST(substr(w.winter_label, 1, 4) AS INTEGER);

-- ----------------------------------------------------------------------------
-- Equity view: Core20 share of catchment vs recent Type-1 performance
-- ----------------------------------------------------------------------------
CREATE VIEW vw_equity AS
WITH last12 AS (
    SELECT org_code,
           SUM(att_type1) AS att, SUM(over4hr_type1) AS o4,
           SUM(dta_12hr_plus) AS dta12
    FROM vw_kpi_ae_monthly
    WHERE month_key >= (SELECT max(month_key) FROM dim_date) - 100  -- ~12 months
    GROUP BY org_code
)
SELECT o.org_code, o.org_name, o.icb_code, o.icb_name, o.region_name,
       c.imd_score, c.deprivation_quintile, c.core20_proxy, c.catchment_population,
       1.0 - l.o4::DOUBLE / NULLIF(l.att, 0) AS type1_performance_12m,
       l.att AS att_type1_12m, l.dta12 AS dta_12hr_12m
FROM dim_org o
JOIN last12 l USING (org_code)
JOIN dim_trust_catchment c USING (org_code)
WHERE o.is_type1_provider;

-- ----------------------------------------------------------------------------
-- Latest snapshot with RAG (documented rule: GREEN >= 78% interim ambition,
-- AMBER 70-78%, RED < 70% Type-1 performance, 95% shown as separate flag)
-- ----------------------------------------------------------------------------
CREATE VIEW vw_trust_latest AS
WITH latest AS (SELECT max(month_key) AS month_key FROM vw_kpi_ae_monthly),
     prior3 AS (
    SELECT org_code,
           SUM(att_type1) AS att, SUM(over4hr_type1) AS o4
    FROM vw_kpi_ae_monthly
    WHERE month_key < (SELECT month_key FROM latest)
      AND month_key >= (SELECT month_key FROM latest) - 4
    GROUP BY org_code
)
SELECT k.org_code, o.org_name, o.icb_code, o.icb_name, o.region_name,
       k.month_key, k.att_type1, k.type1_performance, k.alltype_performance,
       k.dta_12hr_plus, k.type1_meets_95, k.type1_meets_interim,
       k.type1_performance - (1.0 - p.o4::DOUBLE / NULLIF(p.att, 0)) AS momentum_3m_pp,
       CASE
         WHEN k.type1_performance IS NULL THEN 'NO DATA'
         WHEN k.type1_performance < 0.70 THEN 'RED'
         WHEN k.type1_performance < 0.78 THEN 'AMBER'
         ELSE 'GREEN'
       END AS rag
FROM vw_kpi_ae_monthly k
JOIN latest USING (month_key)
JOIN dim_org o USING (org_code)
LEFT JOIN prior3 p USING (org_code)
WHERE o.is_type1_provider;

-- ----------------------------------------------------------------------------
-- Ambulance: regional monthly response times (incident-weighted means).
-- ~11 ambulance services do not map to acute trusts — region is the honest grain.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ambulance_regional AS
SELECT f.region,
       d.month_key, d.month_start, d.is_winter, d.winter_label,
       SUM(f.cat1_mean_sec * f.cat1_incidents) / NULLIF(SUM(f.cat1_incidents), 0) AS cat1_mean_sec,
       SUM(f.cat2_mean_sec * f.cat2_incidents) / NULLIF(SUM(f.cat2_incidents), 0) AS cat2_mean_sec,
       SUM(f.cat1_incidents) AS cat1_incidents,
       SUM(f.cat2_incidents) AS cat2_incidents
FROM fact_ambulance f
JOIN dim_date d USING (month_key)
WHERE NOT f.is_england
GROUP BY ALL;

CREATE VIEW vw_ambulance_england AS
SELECT f.*, d.month_start, d.is_winter, d.winter_label
FROM fact_ambulance f JOIN dim_date d USING (month_key)
WHERE f.is_england;

-- ----------------------------------------------------------------------------
-- Vacancy: regional monthly totals + nursing, with pressure index vs
-- each region's own window mean (counts, not rates — no denominators published)
-- ----------------------------------------------------------------------------
CREATE VIEW vw_vacancy_regional AS
WITH by_region AS (
    SELECT region_code, region_name, month_key,
           SUM(vacancy_wte) AS vacancy_wte_total,
           SUM(vacancy_wte) FILTER (WHERE staff_group ILIKE '%nursing%') AS vacancy_wte_nursing
    FROM fact_vacancy
    GROUP BY ALL
)
SELECT *,
       vacancy_wte_total
         / NULLIF(avg(vacancy_wte_total) OVER (PARTITION BY region_code), 0)
         AS vacancy_pressure_index,
       vacancy_wte_nursing
         / NULLIF(avg(vacancy_wte_nursing) OVER (PARTITION BY region_code), 0)
         AS nursing_pressure_index
FROM by_region;

-- ----------------------------------------------------------------------------
-- Showcase: period-on-period window queries (SQL checklist evidence)
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ae_period_on_period AS
SELECT org_code, month_key, type1_performance,
       lag(type1_performance) OVER w                            AS prev_month,
       type1_performance - lag(type1_performance) OVER w        AS mom_change,
       type1_performance - lag(type1_performance, 12) OVER w    AS yoy_change,
       avg(type1_performance) OVER (
           w ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)          AS rolling_3m,
       rank() OVER (PARTITION BY month_key ORDER BY type1_performance DESC) AS national_rank
FROM vw_kpi_ae_monthly
WHERE att_type1 > 0
WINDOW w AS (PARTITION BY org_code ORDER BY month_key);
