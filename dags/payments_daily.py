"""payments_daily: raw CSV -> Spark -> Parquet lake -> dbt (build + test) -> fraud model -> report.

This file only says WHAT runs, in WHAT ORDER, and WHEN. The real work lives in
src/payments (Spark, ML) and dbt_project (SQL models + tests).

Try a backfill (generated data covers 2026-07-01 .. 2026-09-30):
  airflow dags backfill -s 2026-09-28 -e 2026-09-30 payments_daily
"""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models.baseoperator import chain  # type: ignore[import-not-found]
from airflow.operators.bash import BashOperator  # type: ignore[import-not-found]

try:
    from airflow.sensors.python import PythonSensor  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback for Airflow versions that expose the sensor here.
    from airflow.sensors.python_sensor import PythonSensor  # type: ignore[import-not-found]

PROJECT = "/opt/airflow/project"
DATA = "/data"                                  # Docker named volume (see docker-compose.yml)
PY = "/home/airflow/venv/bin/python"            # the virtual env that holds Spark, dbt, DuckDB, sklearn
DBT = "/home/airflow/venv/bin/dbt"
ENV = {
    "PYTHONPATH": f"{PROJECT}/src",
    "RAW_PATH": f"{DATA}/raw",
    "LAKE_PATH": f"{DATA}/lake",
    "DUCKDB_PATH": f"{DATA}/warehouse.duckdb",
    "DBT_PROFILES_DIR": f"{PROJECT}/dbt_project",
}


def on_failure(context):
    """Called by Airflow when a task fails after all retries. Swap print for Slack/email."""
    ti = context["task_instance"]
    print(f"ALERT: {ti.dag_id}.{ti.task_id} failed for {context['ds']} -> {ti.log_url}")


def file_has_arrived(ds, **_):
    return os.path.exists(f"{ENV['RAW_PATH']}/transactions/transactions_{ds}.csv")


def bash(task_id: str, command: str) -> BashOperator:
    return BashOperator(task_id=task_id, bash_command=f"cd {PROJECT} && {command}",
                        env=ENV, append_env=True)


with DAG(
    dag_id="payments_daily",
    default_args={
        "owner": "data-team",
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": on_failure,
    },
    start_date=datetime(2026, 7, 1),
    end_date=datetime(2026, 9, 30),      # the demo data stops here
    schedule="@daily",
    catchup=False,
    max_active_runs=1,                   # DuckDB allows one writer at a time
    tags=["payments", "spark", "dbt", "ml"],
) as dag:

    wait_for_file = PythonSensor(
        task_id="wait_for_file",
        python_callable=file_has_arrived,
        poke_interval=30,
        timeout=60 * 60,
        mode="reschedule",
    )
    spark_clean = bash("spark_clean", f"{PY} -m payments.spark_clean --date {{{{ ds }}}}")
    dbt_seed = bash("dbt_seed", f"cd dbt_project && {DBT} seed")
    dbt_run = bash("dbt_run", f"cd dbt_project && {DBT} run")
    dbt_test = bash("dbt_test", f"cd dbt_project && {DBT} test")   # failure here blocks ML
    train_fraud_model = bash("train_fraud_model", f"{PY} -m payments.train_fraud_model")
    build_report = bash("build_report", f"{PY} -m payments.report")

    chain(wait_for_file, spark_clean, dbt_seed, dbt_run, dbt_test,
          train_fraud_model, build_report)
