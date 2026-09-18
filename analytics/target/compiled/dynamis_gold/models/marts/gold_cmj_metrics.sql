-- One row per CMJ trial. Pivots the pipeline metrics that were computed by the
-- versioned CMJ force processor; no biomechanical quantity is derived here.
select
    dataset_id,
    session_id,
    subject_id,
    trial_id,
    stream_id,
    algorithm_id,
    run_id,
    max(value_num) filter (where metric_id = 'cmj.net_impulse_per_mass') as net_impulse_per_mass_m_s,
    max(value_num) filter (where metric_id = 'cmj.takeoff_velocity') as takeoff_velocity_m_s,
    max(value_num) filter (where metric_id = 'cmj.com_displacement_to_takeoff') as com_displacement_to_takeoff_m,
    max(value_num) filter (where metric_id = 'cmj.takeoff_to_apex_height') as takeoff_to_apex_height_m,
    max(value_num) filter (where metric_id = 'cmj.jump_height_jhwd') as jump_height_jhwd_m,
    max(value_num) filter (where metric_id = 'cmj.peak_specific_power') as peak_specific_power_w_kg,
    max(value_num) filter (where metric_id = 'cmj.peak_body_weight_ratio') as peak_body_weight_ratio
from "dynamis_gold"."main"."gold_trial_metrics"
where metric_id like 'cmj.%'
group by dataset_id, session_id, subject_id, trial_id, stream_id, algorithm_id, run_id
order by dataset_id, session_id, subject_id, trial_id, stream_id, algorithm_id, run_id