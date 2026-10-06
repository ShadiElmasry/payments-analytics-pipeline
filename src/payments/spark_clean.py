"""PySpark step: clean raw CSV files and write a partitioned Parquet "lake".

Default (local) sink : Parquet files in data/lake/  (read later by dbt + DuckDB)
Experimental sink    : Snowflake RAW schema via the spark-snowflake connector

Usage:
  python -m payments.spark_clean --all               # every daily file
  python -m payments.spark_clean --date 2026-09-30   # a single day (what Airflow does)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from payments.envfile import load_env_file

# Jars Spark downloads from Maven Central on first use in Snowflake mode.
# Connector 3.2 supports Spark 4.0/4.1 (Scala 2.13) and needs Snowflake JDBC 4.0.2 or newer.
# Override with the SPARK_SNOWFLAKE_PACKAGES environment variable.
SNOWFLAKE_PACKAGES = "net.snowflake:spark-snowflake_2.13:3.2.2,net.snowflake:snowflake-jdbc:4.0.2"


def get_spark(app_name: str = "payments_clean", snowflake: bool = False) -> SparkSession:
    # Make Spark's worker processes use the SAME Python as this script. Without this, Spark may start
    # "python3" from PATH (a different version, or the Microsoft Store stub on Windows) and fail.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    builder = (
        SparkSession.builder.master("local[*]")
        .appName(app_name)
        .config("spark.sql.ansi.enabled", "false")                        # bad values -> NULL (Spark 3 and 4)
        .config("spark.sql.shuffle.partitions", "4")                      # small data: few partitions
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")    # re-runs replace only that day
        .config("spark.ui.showConsoleProgress", "false")
    )
    if snowflake:
        packages = os.environ.get("SPARK_SNOWFLAKE_PACKAGES", SNOWFLAKE_PACKAGES)
        builder = builder.config("spark.jars.packages", packages)
    return builder.getOrCreate()


def clean_transactions(df: DataFrame) -> DataFrame:
    """Fix types and text, drop unusable rows, remove duplicate transaction ids."""
    return (
        df.withColumn("txn_id", F.trim("txn_id"))
        .withColumn("customer_id", F.trim("customer_id"))
        .withColumn("merchant_id", F.trim("merchant_id"))
        .withColumn("txn_ts", F.to_timestamp("txn_ts", "yyyy-MM-dd HH:mm:ss"))
        .withColumn("amount", F.col("amount").cast("decimal(14,2)"))
        .withColumn("currency", F.upper(F.trim("currency")))        # "egp" -> "EGP"
        .withColumn("channel", F.upper(F.trim("channel")))
        .withColumn("status", F.upper(F.trim("status")))            # " approved " -> "APPROVED"
        .withColumn("card_present", F.col("card_present").cast("boolean"))
        .withColumn("is_fraud", F.col("is_fraud").cast("int"))
        .filter(F.col("txn_id").isNotNull() & F.col("txn_ts").isNotNull())
        .filter(F.col("amount").isNotNull() & (F.col("amount") > 0))  # drop missing / negative
        .dropDuplicates(["txn_id"])
        .withColumn("txn_date", F.to_date("txn_ts"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


def clean_customers(df: DataFrame) -> DataFrame:
    return (
        df.withColumn("customer_id", F.trim("customer_id"))
        .withColumn("country", F.upper(F.trim("country")))
        .withColumn("segment", F.upper(F.trim("segment")))
        .withColumn("signup_date", F.to_date("signup_date"))
        .dropDuplicates(["customer_id"])
    )


def clean_merchants(df: DataFrame) -> DataFrame:
    return (
        df.withColumn("merchant_id", F.trim("merchant_id"))
        .withColumn("category", F.upper(F.trim("category")))
        .withColumn("country", F.upper(F.trim("country")))
        .dropDuplicates(["merchant_id"])
    )


def private_key_body(path: str) -> str:
    """The Spark connector wants the key as one line, without the BEGIN/END header and footer lines."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return "".join(line.strip() for line in lines if line.strip() and not line.startswith("-----"))


def snowflake_options() -> dict[str, str]:
    """Connection settings for the Spark connector (key-pair login, values come from .env)."""
    return {
        "sfURL": f"{os.environ['SNOWFLAKE_ACCOUNT']}.snowflakecomputing.com",
        "sfUser": os.environ["SNOWFLAKE_USER"],
        "pem_private_key": private_key_body(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]),
        "sfRole": os.environ.get("SNOWFLAKE_ROLE", "PAYMENTS_ROLE"),
        "sfDatabase": os.environ.get("SNOWFLAKE_DATABASE", "PAYMENTS_DB"),
        "sfWarehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "PAYMENTS_WH"),
        "sfSchema": "RAW",
    }


def write_snowflake(df: DataFrame, table: str, mode: str) -> None:
    """Experimental: write a DataFrame into the Snowflake RAW schema through the Spark connector."""
    (df.write.format("net.snowflake.spark.snowflake").options(**snowflake_options())
       .option("dbtable", table).mode(mode).save())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="process every daily file")
    group.add_argument("--date", help="process one day, e.g. 2026-09-30")
    parser.add_argument("--raw", default=os.environ.get("RAW_PATH", "data/raw"))
    parser.add_argument("--lake", default=os.environ.get("LAKE_PATH", "data/lake"))
    parser.add_argument("--sink", choices=["parquet", "snowflake"], default="parquet")
    args = parser.parse_args()

    load_env_file()
    spark = get_spark(snowflake=args.sink == "snowflake")
    spark.sparkContext.setLogLevel("ERROR")

    pattern = "*" if args.all else args.date
    txn_path = f"{args.raw}/transactions/transactions_{pattern}.csv"

    raw = (
        spark.read.csv(txn_path, header=True)
        .withColumn("_source_file", F.regexp_extract(F.input_file_name(), r"[^/]+$", 0))
    )
    txns = clean_transactions(raw).cache()
    n_raw, n_clean = raw.count(), txns.count()
    print(f"transactions: {n_raw:,} raw rows -> {n_clean:,} clean rows "
          f"({n_raw - n_clean:,} dropped: duplicates, missing or negative amounts)")

    customers = clean_customers(spark.read.csv(f"{args.raw}/dims/customers.csv", header=True))
    merchants = clean_merchants(spark.read.csv(f"{args.raw}/dims/merchants.csv", header=True))

    if args.sink == "parquet":
        txns.write.mode("overwrite").partitionBy("txn_date").parquet(f"{args.lake}/transactions")
        customers.coalesce(1).write.mode("overwrite").parquet(f"{args.lake}/customers")
        merchants.coalesce(1).write.mode("overwrite").parquet(f"{args.lake}/merchants")
        print(f"wrote Parquet lake to {args.lake}/")
    else:
        write_snowflake(txns, "TRANSACTIONS", "append")   # dbt de-duplicates re-runs
        write_snowflake(customers, "CUSTOMERS", "overwrite")
        write_snowflake(merchants, "MERCHANTS", "overwrite")
        print("loaded RAW.TRANSACTIONS / CUSTOMERS / MERCHANTS in Snowflake")

    spark.stop()


if __name__ == "__main__":
    main()
