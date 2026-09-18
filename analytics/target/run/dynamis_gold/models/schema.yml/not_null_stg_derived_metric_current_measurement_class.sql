
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select measurement_class
from "dynamis_gold"."main"."stg_derived_metric_current"
where measurement_class is null



  
  
      
    ) dbt_internal_test