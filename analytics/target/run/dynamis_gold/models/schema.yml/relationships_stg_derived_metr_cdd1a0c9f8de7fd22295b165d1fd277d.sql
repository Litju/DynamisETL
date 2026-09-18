
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with child as (
    select metric_id as from_field
    from "dynamis_gold"."main"."stg_derived_metric_current"
    where metric_id is not null
),

parent as (
    select metric_id as to_field
    from "dynamis_gold"."main"."stg_metric_definition"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null



  
  
      
    ) dbt_internal_test