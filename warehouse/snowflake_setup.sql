-- Experimental Snowflake mode. Run once as SYSADMIN, then:
--   export DBT_TARGET=snowflake  (plus the SNOWFLAKE_* variables from .env.example)
--   Run the Spark step with the spark-snowflake and snowflake-jdbc jars that match YOUR Spark/Scala version
--   (Spark 4 uses Scala 2.13), e.g. spark-submit --packages <connector coordinates> ... --sink snowflake
--   cd dbt_project && dbt build
CREATE WAREHOUSE IF NOT EXISTS PAYMENTS_WH WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;
CREATE DATABASE  IF NOT EXISTS PAYMENTS_DB;
CREATE SCHEMA    IF NOT EXISTS PAYMENTS_DB.RAW;      -- Spark loads here
CREATE SCHEMA    IF NOT EXISTS PAYMENTS_DB.STAGING;  -- dbt
CREATE SCHEMA    IF NOT EXISTS PAYMENTS_DB.MARTS;    -- dbt
