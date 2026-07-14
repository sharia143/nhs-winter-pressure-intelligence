-- ============================================================================
-- NHS Winter Pressure warehouse DDL (DuckDB)
-- Staging views (stg_*) are attached by build.py before this script runs.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- dim_date: month grain over every month seen in any fact
-- ----------------------------------------------------------------------------
CREATE TABLE dim_date AS
WITH fact_months AS (
    SELECT DISTINCT month_key FROM stg_ae
    UNION SELECT DISTINCT month_key FROM stg_rtt_summary
    UNION SELECT DISTINCT month_key FROM stg_ambulance
), bounds AS (
    SELECT min(month_key) AS lo,
           -- extend 12 months past the latest fact month so forecast targets
           -- always join to dim_date
           max(month_key) AS hi
    FROM fact_months
), months AS (
    SELECT (year(mo) * 100 + month(mo))::BIGINT AS month_key
    FROM bounds,
         generate_series(
             make_date(lo // 100, lo % 100, 1),
             make_date(hi // 100, hi % 100, 1) + INTERVAL 12 MONTH,
             INTERVAL 1 MONTH
         ) AS t(mo)
), base AS (
    SELECT month_key,
           make_date(month_key // 100, month_key % 100, 1) AS month_start,
           month_key // 100 AS yr,
           month_key % 100  AS mo
    FROM months
)
SELECT month_key,
       month_start,
       date_diff('day', month_start, month_start + INTERVAL 1 MONTH) AS days_in_month,
       strftime(month_start, '%B') AS month_name,
       CASE WHEN mo >= 4 THEN yr ELSE yr - 1 END AS fy_start,
       (CASE WHEN mo >= 4 THEN yr ELSE yr - 1 END)::VARCHAR
         || '-' || substr(((CASE WHEN mo >= 4 THEN yr ELSE yr - 1 END) + 1)::VARCHAR, 3, 2) AS fy,
       mo IN (12, 1, 2) AS is_winter,
       CASE
         WHEN mo = 12 THEN yr::VARCHAR || '-' || substr((yr + 1)::VARCHAR, 3, 2)
         WHEN mo IN (1, 2) THEN (yr - 1)::VARCHAR || '-' || substr(yr::VARCHAR, 3, 2)
       END AS winter_label,
       mo IN (6, 7, 8) AS is_summer,
       month_key >= getvariable('ecds_break_key') AS methodology_break
FROM base;

-- ----------------------------------------------------------------------------
-- Succession bridge: transitive closure of ODS successor mappings (depth-capped)
-- Splits (one predecessor, several successors) are flagged, not hidden.
-- ----------------------------------------------------------------------------
CREATE TABLE org_succession_raw AS
SELECT DISTINCT predecessor_code, successor_code, effective_date
FROM stg_org_succession
WHERE predecessor_code IS NOT NULL AND successor_code IS NOT NULL
  AND predecessor_code <> successor_code;

CREATE TABLE bridge_org_succession AS
WITH RECURSIVE chain(predecessor_code, ultimate, depth) AS (
    SELECT predecessor_code, successor_code, 1 FROM org_succession_raw
    UNION ALL
    SELECT c.predecessor_code, s.successor_code, c.depth + 1
    FROM chain c
    JOIN org_succession_raw s ON s.predecessor_code = c.ultimate
    WHERE c.depth < 8
), terminal AS (
    SELECT predecessor_code, ultimate, depth,
           row_number() OVER (PARTITION BY predecessor_code ORDER BY depth DESC, ultimate) AS rn,
           count(DISTINCT ultimate) OVER (PARTITION BY predecessor_code, depth) AS n_at_depth
    FROM chain
)
SELECT predecessor_code,
       ultimate AS ultimate_successor_code,
       depth    AS chain_depth,
       n_at_depth > 1 AS ambiguous_split
FROM terminal
WHERE rn = 1;

-- ----------------------------------------------------------------------------
-- org_map: any code seen in any fact -> analysis code (ultimate successor)
-- ----------------------------------------------------------------------------
CREATE TABLE org_map AS
WITH seen AS (
    SELECT DISTINCT org_code_published FROM stg_ae
    UNION SELECT DISTINCT org_code_published FROM stg_rtt_summary
    UNION SELECT DISTINCT org_code_published FROM stg_ambulance
)
SELECT s.org_code_published,
       COALESCE(b.ultimate_successor_code, s.org_code_published) AS org_code,
       b.ultimate_successor_code IS NOT NULL AS was_mapped,
       COALESCE(b.ambiguous_split, FALSE) AS ambiguous_split
FROM seen s
LEFT JOIN bridge_org_succession b ON b.predecessor_code = s.org_code_published;

-- ----------------------------------------------------------------------------
-- Facts: published grain + rolled-up analysis key
-- ----------------------------------------------------------------------------
CREATE TABLE fact_ae AS
SELECT om.org_code, a.*
FROM stg_ae a JOIN org_map om USING (org_code_published);

CREATE TABLE fact_rtt AS
SELECT om.org_code, r.*
FROM stg_rtt_summary r JOIN org_map om USING (org_code_published);

CREATE TABLE fact_rtt_bands AS
SELECT om.org_code, r.*
FROM stg_rtt_bands r JOIN org_map om USING (org_code_published);

CREATE TABLE fact_ambulance AS
SELECT om.org_code, a.*
FROM stg_ambulance a JOIN org_map om USING (org_code_published);

CREATE TABLE fact_vacancy AS SELECT * FROM stg_vacancy;
CREATE TABLE fact_weather AS SELECT * FROM stg_weather;

-- ----------------------------------------------------------------------------
-- dim_icb (post-2026 footprints are the reporting layer, 2022 kept for history)
-- ----------------------------------------------------------------------------
CREATE TABLE dim_icb AS
SELECT icb_code, icb_name, open_date, close_date, is_current
FROM stg_org_icbs;

-- Best ICB per analysis org: prefer the April-2026 System-Mapping vintage,
-- falling back to the 2022 attribution, and where several published codes roll to
-- one analysis code, take the most frequent mapping.
CREATE TABLE org_icb AS
WITH mapped AS (
    SELECT om.org_code,
           m.icb_code, m.icb_name, m.region_name, m.mapping_vintage
    FROM stg_org_icb_map m
    JOIN org_map om ON om.org_code_published = m.org_code
), counted AS (
    SELECT org_code, icb_code, icb_name, region_name, mapping_vintage,
           count(*) AS n
    FROM mapped
    GROUP BY ALL
), ranked AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY org_code, mapping_vintage
               ORDER BY n DESC, icb_code
           ) AS rn
    FROM counted
)
SELECT c.org_code,
       c.icb_code, c.icb_name, c.region_name,
       o.icb_code AS icb_code_2022, o.icb_name AS icb_name_2022
FROM (SELECT * FROM ranked WHERE mapping_vintage = '2026-04' AND rn = 1) c
FULL JOIN (SELECT * FROM ranked WHERE mapping_vintage = '2022-07' AND rn = 1) o
    USING (org_code);

-- ----------------------------------------------------------------------------
-- dim_org: every analysis org, enriched
-- ----------------------------------------------------------------------------
CREATE TABLE dim_org AS
WITH ae_stats AS (
    SELECT om.org_code,
           min(a.month_key) AS first_month_seen,
           max(a.month_key) AS last_month_seen,
           count(DISTINCT a.month_key) FILTER (WHERE a.att_type1 > 0) AS months_type1,
           max_by(a.org_name, a.month_key) AS latest_published_name,
           max_by(a.parent_org, a.month_key) AS latest_parent_org
    FROM stg_ae a JOIN org_map om USING (org_code_published)
    GROUP BY om.org_code
), rtt_stats AS (
    SELECT om.org_code,
           min(t.month_key) AS first_month_seen,
           max(t.month_key) AS last_month_seen,
           max_by(t.org_name, t.month_key) AS latest_published_name
    FROM stg_rtt_summary t JOIN org_map om USING (org_code_published)
    GROUP BY om.org_code
), combined AS (
    SELECT org_code, first_month_seen, last_month_seen,
           months_type1, latest_published_name, latest_parent_org
    FROM ae_stats
    UNION ALL
    SELECT org_code, first_month_seen, last_month_seen,
           0 AS months_type1, latest_published_name, NULL AS latest_parent_org
    FROM rtt_stats
    WHERE org_code NOT IN (SELECT org_code FROM ae_stats)
), ref AS (
    SELECT org_code, org_name, org_type, postcode, region_name, is_current
    FROM stg_org_reference
)
SELECT s.org_code,
       COALESCE(r.org_name, s.latest_published_name) AS org_name,
       COALESCE(r.org_type, 'Other provider') AS org_type,
       r.postcode,
       COALESCE(r.region_name, i.region_name, trim(s.latest_parent_org)) AS region_name,
       r.is_current,
       s.first_month_seen, s.last_month_seen,
       s.months_type1,
       s.months_type1 >= 24 AS is_type1_provider,
       i.icb_code, i.icb_name, i.icb_code_2022, i.icb_name_2022
FROM combined s
LEFT JOIN ref r USING (org_code)
LEFT JOIN org_icb i USING (org_code);

-- ----------------------------------------------------------------------------
-- dim_trust_catchment
-- ----------------------------------------------------------------------------
CREATE TABLE dim_trust_catchment AS
WITH rolled AS (
    SELECT COALESCE(b.ultimate_successor_code, c.org_code) AS org_code,
           sum(c.catchment_population) AS catchment_population,
           sum(c.imd_score * c.catchment_population)
               / NULLIF(sum(c.catchment_population), 0) AS imd_score
    FROM stg_catchment c
    LEFT JOIN bridge_org_succession b ON b.predecessor_code = c.org_code
    GROUP BY 1
)
SELECT *,
       rank() OVER (ORDER BY imd_score DESC) AS imd_rank_recomputed,
       ntile(5) OVER (ORDER BY imd_score DESC) AS deprivation_quintile,  -- 1 = most deprived
       ntile(5) OVER (ORDER BY imd_score DESC) = 1 AS core20_proxy
FROM rolled;
