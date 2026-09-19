-- Scientific reconciliation: Gold serving must not add, drop or duplicate a
-- current metric row. The test returns rows only when the counts disagree.
with gold as (
    select count(*) as row_count from {{ ref('gold_trial_metrics') }}
),
staged as (
    select count(*) as row_count from {{ ref('stg_derived_metric_current') }}
)
select gold.row_count as gold_rows, staged.row_count as staged_rows
from gold, staged
where gold.row_count != staged.row_count
