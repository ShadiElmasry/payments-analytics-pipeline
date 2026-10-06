{#
  One place that decides where raw data comes from:
    - DuckDB    : read the Parquet files Spark wrote
    - Snowflake : read the RAW table Spark loaded
  Every staging model calls this, so the rest of the project is warehouse-agnostic.
#}
{% macro lake_table(name) -%}
    {%- if target.type == 'duckdb' -%}
        read_parquet('{{ env_var("LAKE_PATH", "../data/lake") }}/{{ name }}/**/*.parquet', hive_partitioning = true)
    {%- else -%}
        {{ source('raw', name) }}
    {%- endif -%}
{%- endmacro %}
