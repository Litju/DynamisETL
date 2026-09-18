
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select algorithm_id
from "dynamis_gold"."main"."gold_processing_provenance"
where algorithm_id is null



  
  
      
    ) dbt_internal_test