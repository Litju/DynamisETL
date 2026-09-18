
    
    

select
    derived_metric_id as unique_field,
    count(*) as n_records

from "dynamis_gold"."main"."gold_trial_metrics"
where derived_metric_id is not null
group by derived_metric_id
having count(*) > 1


