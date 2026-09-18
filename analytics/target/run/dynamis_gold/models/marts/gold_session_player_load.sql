
    

    create  table
      "dynamis_gold"."main"."gold_session_player_load__dbt_tmp"
  
    
    as (
      -- Session/subject/entity locomotor load summary. Aggregation and pivoting of
-- processor outputs only: no derivative, integration or biomechanics is defined
-- here. The explicit `locomotor.%` scope is documented so the mart never mixes
-- modalities; other modalities have their own marts.
select
    dataset_id,
    session_id,
    subject_id,
    entity_id,
    algorithm_id,
    count(*) as locomotor_metric_count,
    max(value_num) filter (where metric_id = 'locomotor.distance_total') as distance_total_m,
    max(value_num) filter (where metric_id = 'locomotor.mean_speed') as mean_speed_m_s,
    max(value_num) filter (where metric_id = 'locomotor.max_speed') as max_speed_m_s,
    max(value_num) filter (where metric_id = 'locomotor.max_acceleration') as max_acceleration_m_s2,
    max(value_num) filter (where metric_id = 'locomotor.max_deceleration') as max_deceleration_m_s2,
    max(value_num) filter (where metric_id = 'locomotor.effort_count') as effort_count,
    max(value_num) filter (where metric_id = 'locomotor.effort_duration_total') as effort_duration_total_s,
    max(value_num) filter (where metric_id = 'locomotor.effort_distance_total') as effort_distance_total_m,
    max(value_num) filter (where metric_id = 'locomotor.effort_peak_speed') as effort_peak_speed_m_s
from "dynamis_gold"."main"."gold_trial_metrics"
where metric_id like 'locomotor.%'
group by dataset_id, session_id, subject_id, entity_id, algorithm_id
order by dataset_id, session_id, subject_id, entity_id, algorithm_id
    );
    
  