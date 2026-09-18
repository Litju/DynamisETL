
    
    

select
    run_id as unique_field,
    count(*) as n_records

from "dynamis_gold"."main"."gold_processing_provenance"
where run_id is not null
group by run_id
having count(*) > 1


