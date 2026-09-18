-- One row per accepted scalar metric of the current revision lineage.
-- Identity (dataset/session/subject/trial/stream/entity) is retained so every
-- value resolves back to its processing run through gold_processing_provenance.
select
    m.derived_metric_id,
    m.dataset_id,
    m.metric_id,
    d.name as metric_name,
    d.description as metric_description,
    m.si_unit,
    m.measurement_class,
    m.subject_id,
    m.session_id,
    m.trial_id,
    m.stream_id,
    m.entity_id,
    m.algorithm_id,
    m.algorithm_version,
    m.parameters_hash,
    m.code_git_sha,
    m.run_id,
    m.value_num,
    m.computed_at
from "dynamis_gold"."main"."stg_derived_metric_current" m
left join "dynamis_gold"."main"."stg_metric_definition" d using (metric_id)
order by
    m.dataset_id,
    m.metric_id,
    m.session_id,
    m.subject_id,
    m.trial_id,
    m.stream_id,
    m.entity_id