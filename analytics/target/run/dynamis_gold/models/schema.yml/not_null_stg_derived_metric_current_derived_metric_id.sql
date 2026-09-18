
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select derived_metric_id
from "dynamis_gold"."main"."stg_derived_metric_current"
where derived_metric_id is null



  
  
      
    ) dbt_internal_test