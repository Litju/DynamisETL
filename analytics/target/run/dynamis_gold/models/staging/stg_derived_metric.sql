
  
  create view "dynamis_gold"."main"."stg_derived_metric__dbt_tmp" as (
    -- Scalar metric serving export. Selection only: every row is a value already
-- computed and versioned by a deterministic processor (or imported as a
-- provider SOURCE_DERIVED value).
select * from read_parquet('D:/Dev/Temp/User/pytest-of-Usuario/pytest-234/test_gold_export_build_publish0/datasets/gold/serving/derived_metric.parquet')
  );
