
  
  create view "dynamis_gold"."main"."stg_trial__dbt_tmp" as (
    ﻿-- Control-plane serving export (selection only).
select * from read_parquet('D:/Dev/Temp/User/pytest-of-Usuario/pytest-234/test_gold_export_build_publish0/datasets/gold/serving/trial.parquet')
  );
