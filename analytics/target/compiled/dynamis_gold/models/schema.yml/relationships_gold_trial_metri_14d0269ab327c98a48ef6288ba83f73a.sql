
    
    

with child as (
    select run_id as from_field
    from "dynamis_gold"."main"."gold_trial_metrics"
    where run_id is not null
),

parent as (
    select run_id as to_field
    from "dynamis_gold"."main"."stg_processing_run"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


