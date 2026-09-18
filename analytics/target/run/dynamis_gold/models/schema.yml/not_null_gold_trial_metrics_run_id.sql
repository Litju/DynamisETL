
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select run_id
from "dynamis_gold"."main"."gold_trial_metrics"
where run_id is null



  
  
      
    ) dbt_internal_test