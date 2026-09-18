
    
    

with all_values as (

    select
        measurement_class as value_field,
        count(*) as n_records

    from "dynamis_gold"."main"."stg_derived_metric_current"
    group by measurement_class

)

select *
from all_values
where value_field not in (
    'SOURCE_DERIVED','PIPELINE_DERIVED','MODEL_ESTIMATED'
)


