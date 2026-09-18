-- Exactly one row per scientific identity and revision lineage.
--
-- Derived-metric identity includes the algorithm version, parameters hash and
-- code revision, so two revisions of the same metric legitimately coexist as
-- history. Gold serving selects the *most recent computation* per identity
-- (documented rule, no hidden filtering): latest computed_at, then run_id as a
-- deterministic tie-break. `gold_processing_provenance` keeps the full history.
with ranked as (
    select
        *,
        json_extract_string(provenance, '$.algorithm_id') as algorithm_id,
        json_extract_string(provenance, '$.algorithm_version') as algorithm_version,
        json_extract_string(provenance, '$.parameters_hash') as parameters_hash,
        json_extract_string(provenance, '$.code_git_sha') as code_git_sha,
        json_extract_string(provenance, '$.origin') as origin,
        json_extract_string(provenance, '$.entity_id') as entity_id,
        row_number() over (
            partition by
                dataset_id,
                metric_id,
                coalesce(subject_id, ''),
                coalesce(session_id, ''),
                coalesce(trial_id, ''),
                coalesce(stream_id, ''),
                coalesce(json_extract_string(provenance, '$.entity_id'), '')
            order by computed_at desc nulls last, run_id desc
        ) as revision_rank
    from "dynamis_gold"."main"."stg_derived_metric"
)
select * exclude (revision_rank)
from ranked
where revision_rank = 1