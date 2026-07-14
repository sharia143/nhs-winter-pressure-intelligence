-- Materialised only when the forecast stage has produced outputs
-- (build.py attaches outputs/model/*.parquet as stg_ views first).
CREATE TABLE org_clusters AS SELECT * FROM stg_org_clusters;
CREATE TABLE fact_forecast AS SELECT * FROM stg_fact_forecast;
CREATE TABLE backtest_metrics AS SELECT * FROM stg_backtest_metrics;
CREATE TABLE interval_coverage AS SELECT * FROM stg_interval_coverage;
