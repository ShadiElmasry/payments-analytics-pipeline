"""Run the whole pipeline with one command, on any OS (no `make` needed).

    python -m payments.run_all              # 92 days of data
    python -m payments.run_all --days 14    # smaller and faster

Steps: generate data -> Spark clean -> dbt build (models + tests) -> train fraud model -> charts/exports.
Works the same on Windows, macOS, Linux and inside Docker.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def dbt_executable() -> str:
    """dbt installed next to this Python (same virtual env), with a .exe on Windows."""
    bin_dir = Path(sys.executable).parent
    for name in ("dbt", "dbt.exe"):
        if (bin_dir / name).exists():
            return str(bin_dir / name)
    return "dbt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=92)
    args = parser.parse_args()

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH")]))
    env.setdefault("RAW_PATH", str(ROOT / "data" / "raw"))
    env.setdefault("LAKE_PATH", str(ROOT / "data" / "lake"))
    env.setdefault("DUCKDB_PATH", str(ROOT / "data" / "warehouse.duckdb"))
    env.setdefault("DBT_PROFILES_DIR", str(ROOT / "dbt_project"))
    Path(env["DUCKDB_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    steps = [
        ("1/5 generate data", [py, "-m", "payments.generate_data", "--days", str(args.days)], ROOT),
        ("2/5 Spark: clean -> Parquet", [py, "-m", "payments.spark_clean", "--all"], ROOT),
        ("3/5 dbt: build models + run tests", [dbt_executable(), "build"], ROOT / "dbt_project"),
        ("4/5 train fraud model", [py, "-m", "payments.train_fraud_model"], ROOT),
        ("5/5 charts + CSV exports", [py, "-m", "payments.report"], ROOT),
    ]
    for title, command, cwd in steps:
        print(f"\n=== {title} ===", flush=True)
        subprocess.run(command, cwd=cwd, env=env, check=True)
    print("\nDone. Charts: docs/images/ | CSV exports: exports/ | metrics: reports/metrics.json")


if __name__ == "__main__":
    main()
