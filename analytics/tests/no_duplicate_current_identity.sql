-- The documented "latest revision per identity" rule must leave exactly one row
-- per (dataset, metric, subject, session, trial, stream, entity).
select
    dataset_id,
    metric_id,
    subject_id,
    session_id,
    trial_id,
    stream_id,
    entity_id,
    count(*) as duplicate_count
from {{ ref('stg_derived_metric_current') }}
group by
    dataset_id,
    metric_id,
    subject_id,
    session_id,
    trial_id,
    stream_id,
    entity_id
having count(*) > 1
