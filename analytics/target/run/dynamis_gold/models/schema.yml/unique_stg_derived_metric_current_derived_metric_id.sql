
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    derived_metric_id as unique_field,
    count(*) as n_records

from "dynamis_gold"."main"."stg_derived_metric_current"
where derived_metric_id is not null
group by derived_metric_id
having count(*) > 1



  
  
      
    ) dbt_internal_test