"""Read from / write to the warehouse: DuckDB (default) or Snowflake (DBT_TARGET=snowflake).

The ML and report steps only use these two functions, so they do not care which warehouse is behind them.
"""
from __future__ import annotations

import os

import pandas as pd


def is_snowflake() -> bool:
    return os.environ.get("DBT_TARGET", "duckdb").lower() == "snowflake"


def duckdb_path() -> str:
    return os.environ.get("DUCKDB_PATH", "data/warehouse.duckdb")


def snowflake_connection(schema: str = "MARTS"):
    """Connect with a key pair (Snowflake no longer allows single-factor password logins)."""
    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"],
        role=os.environ.get("SNOWFLAKE_ROLE", "PAYMENTS_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "PAYMENTS_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "PAYMENTS_DB"),
        schema=schema,
    )


def read_sql(sql: str) -> pd.DataFrame:
    """Run a query and return a DataFrame with lowercase column names."""
    if is_snowflake():
        conn = snowflake_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            df = cursor.fetch_pandas_all()
        finally:
            conn.close()
    else:
        import duckdb

        con = duckdb.connect(duckdb_path(), read_only=True)
        try:
            df = con.execute(sql).df()
        finally:
            con.close()
    df.columns = [c.lower() for c in df.columns]
    return df


def write_table(df: pd.DataFrame, schema: str, table: str) -> None:
    """Create or replace schema.table from a DataFrame."""
    if is_snowflake():
        from snowflake.connector.pandas_tools import write_pandas

        conn = snowflake_connection(schema.upper())
        try:
            out = df.copy()
            out.columns = [c.upper() for c in out.columns]
            write_pandas(conn, out, table.upper(), auto_create_table=True, overwrite=True,
                         use_logical_type=True)
        finally:
            conn.close()
    else:
        import duckdb

        # pandas 3 uses a new string dtype that older DuckDB versions cannot read; plain objects are safe
        out = df.copy()
        for col in out.columns:
            if pd.api.types.is_string_dtype(out[col]):
                out[col] = out[col].astype(object)
        con = duckdb.connect(duckdb_path())
        try:
            con.register("df_to_write", out)
            con.execute(f"create schema if not exists {schema}")
            con.execute(f"create or replace table {schema}.{table} as select * from df_to_write")
        finally:
            con.close()
