-- Control-plane serving export (selection only).
select * from read_parquet('{{ var("serving_root") }}/processing_run.parquet')

