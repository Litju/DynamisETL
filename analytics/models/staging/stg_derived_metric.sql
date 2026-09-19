-- Scalar metric serving export. Selection only: every row is a value already
-- computed and versioned by a deterministic processor (or imported as a
-- provider SOURCE_DERIVED value).
select * from read_parquet('{{ var("serving_root") }}/derived_metric.parquet')
