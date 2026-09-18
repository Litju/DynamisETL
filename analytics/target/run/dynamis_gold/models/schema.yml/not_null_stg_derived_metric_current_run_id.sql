
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select run_id
from "dynamis_gold"."main"."stg_derived_metric_current"
where run_id is null



  
  
      
    ) dbt_internal_test