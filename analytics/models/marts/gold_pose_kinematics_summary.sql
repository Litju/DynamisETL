-- Pose kinematics availability/quality summary per dataset/session/subject.
-- Selection and aggregation of versioned pose processor metrics only.
select
    dataset_id,
    session_id,
    subject_id,
    algorithm_id,
    count(*) filter (where metric_id like 'pose.%') as pose_metric_count,
    max(value_num) filter (where metric_id like 'pose.segment_length_mean.%') as max_segment_length_m,
    max(value_num) filter (where metric_id like 'pose.segment_length_error_bound.%') as max_segment_length_error_bound_m,
    max(value_num) filter (where metric_id like 'pose.angular_rom.%') as max_angular_rom_rad,
    max(value_num) filter (where metric_id like 'pose.angular_velocity_peak.%') as max_angular_velocity_rad_s,
    min(value_num) filter (where metric_id like 'pose.availability.%') as min_landmark_availability,
    max(value_num) filter (where metric_id like 'pose.error_radius_mean.%') as max_error_radius_mean_m
from {{ ref('gold_trial_metrics') }}
where metric_id like 'pose.%'
group by dataset_id, session_id, subject_id, algorithm_id
order by dataset_id, session_id, subject_id, algorithm_id
