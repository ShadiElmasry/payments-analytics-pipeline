FROM apache/airflow:2.9.3-python3.11

USER root
# Java for Spark, and a writable /data folder for the Docker volume that holds the lake + warehouse
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
 && apt-get clean && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /data && chown airflow:0 /data && chmod -R g+rwX /data

USER airflow
# ONE virtual env with everything the pipeline needs (Spark, dbt, DuckDB, scikit-learn, Snowflake extras).
# It is separate from Airflow's own Python, so their dependencies can never clash.
COPY requirements.txt requirements-snowflake.txt /tmp/
RUN python -m venv /home/airflow/venv \
 && /home/airflow/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-snowflake.txt
