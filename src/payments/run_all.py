"""Run the whole pipeline with one command, on any OS (no `make` needed).

    python -m payments.run_all              # 92 days of data
    python -m payments.run_all --days 14    # smaller and faster
    python -m payments.run_all --target snowflake   # same pipeline on Snowflake (see README)

Steps: generate data -> Spark clean -> dbt build (models + tests) -> train fraud model -> charts/exports.
Works the same on Windows, macOS, Linux and inside Docker.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from payments.envfile import load_env_file

ROOT = Path(__file__).resolve().parents[2]


def dbt_command() -> list[str]:
    """Run the dbt-core installed in THIS Python, never a different `dbt` found on PATH.

    (Some machines also have dbt's newer "Fusion" program on PATH, installed by the VS Code dbt extension.
    This project is built and tested on dbt-core, so we call it through Python directly.)
    """
    import importlib.util

    if importlib.util.find_spec("dbt.cli.main") is None:
        raise SystemExit("dbt-core is not installed in this Python. Run: pip install -r requirements.txt")
    return [sys.executable, "-c", "from dbt.cli.main import cli; cli()"]


def check_snowflake_settings(env: dict) -> None:
    """Fail early, with a clear message, if the Snowflake settings are missing."""
    required = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH")
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in.")
    key_path = env["SNOWFLAKE_PRIVATE_KEY_PATH"]
    if not Path(key_path).exists():
        raise SystemExit(f"Private key not found: {key_path} (create it with scripts/make_snowflake_keys.py)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=92)
    parser.add_argument("--target", choices=["duckdb", "snowflake"], default="duckdb")
    args = parser.parse_args()

    load_env_file()                      # reads .env (Snowflake settings) if it exists
    env = os.environ.copy()
    env["DBT_TARGET"] = args.target      # dbt, the model and the report all follow this
    if args.target == "snowflake":
        check_snowflake_settings(env)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH")]))
    env.setdefault("RAW_PATH", str(ROOT / "data" / "raw"))
    env.setdefault("LAKE_PATH", str(ROOT / "data" / "lake"))
    env.setdefault("DUCKDB_PATH", str(ROOT / "data" / "warehouse.duckdb"))
    env.setdefault("DBT_PROFILES_DIR", str(ROOT / "dbt_project"))
    Path(env["DUCKDB_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    sink = "snowflake" if args.target == "snowflake" else "parquet"
    sink_label = "Snowflake RAW" if sink == "snowflake" else "Parquet"
    steps = [
        ("1/5 generate data", [py, "-m", "payments.generate_data", "--days", str(args.days)], ROOT),
        (f"2/5 Spark: clean -> {sink_label}",
         [py, "-m", "payments.spark_clean", "--all", "--sink", sink], ROOT),
        ("3/5 dbt: build models + run tests", [*dbt_command(), "build"], ROOT / "dbt_project"),
        ("4/5 train fraud model", [py, "-m", "payments.train_fraud_model"], ROOT),
        ("5/5 charts + CSV exports", [py, "-m", "payments.report"], ROOT),
    ]
    for title, command, cwd in steps:
        print(f"\n=== {title} ===", flush=True)
        subprocess.run(command, cwd=cwd, env=env, check=True)
    print("\nDone. Charts: docs/images/ | CSV exports: exports/ | metrics: reports/metrics.json")


if __name__ == "__main__":
    main()
