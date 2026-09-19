-- Control-plane serving export (selection only).
select * from read_parquet('{{ var("serving_root") }}/sample_artifact.parquet')

