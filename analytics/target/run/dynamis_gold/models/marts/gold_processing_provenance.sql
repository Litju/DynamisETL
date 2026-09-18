
    

    create  table
      "dynamis_gold"."main"."gold_processing_provenance__dbt_tmp"
  
    
    as (
      -- One row per processing run that currently serves a metric, carrying the full
-- provenance chain: algorithm/version, parameters hash, code Git SHA, input
-- checksums and the external processing artifacts of the run.
select
    m.run_id,
    m.dataset_id,
    m.algorithm_id,
    max(m.algorithm_version) as algorithm_version,
    max(m.parameters_hash) as parameters_hash,
    max(m.code_git_sha) as code_git_sha,
    max(m.origin) as origin,
    max(m.input_checksums) as input_checksums,
    min(m.computed_at) as first_computed_at,
    max(m.computed_at) as last_computed_at,
    count(*) as metric_count,
    coalesce(a.artifact_count, 0) as artifact_count
from "dynamis_gold"."main"."stg_derived_metric_current" m
left join (
    select run_id, count(*) as artifact_count
    from "dynamis_gold"."main"."stg_processing_artifact"
    group by run_id
) a using (run_id)
group by m.run_id, m.dataset_id, m.algorithm_id, a.artifact_count
order by m.run_id
    );
    
  