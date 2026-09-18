
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        measurement_class as value_field,
        count(*) as n_records

    from "dynamis_gold"."main"."gold_trial_metrics"
    group by measurement_class

)

select *
from all_values
where value_field not in (
    'SOURCE_DERIVED','PIPELINE_DERIVED','MODEL_ESTIMATED'
)



  
  
      
    ) dbt_internal_test