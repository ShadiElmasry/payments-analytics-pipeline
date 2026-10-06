-- Snowflake setup for payments-analytics-pipeline. Run once in a Snowsight worksheet.
-- Before you start: python scripts/make_snowflake_keys.py   (it prints the public key for step 2)

-- ---------------------------------------------------------------------------------------------
-- Step 1: warehouse, database and one schema per layer
-- ---------------------------------------------------------------------------------------------
USE ROLE SYSADMIN;

CREATE WAREHOUSE IF NOT EXISTS PAYMENTS_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60            -- stop after 60 seconds idle, so credits are not wasted
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS PAYMENTS_DB;
CREATE SCHEMA IF NOT EXISTS PAYMENTS_DB.RAW;       -- Spark loads cleaned data here
CREATE SCHEMA IF NOT EXISTS PAYMENTS_DB.STAGING;   -- dbt staging tables
CREATE SCHEMA IF NOT EXISTS PAYMENTS_DB.MARTS;     -- dbt marts + model scores

-- ---------------------------------------------------------------------------------------------
-- Step 2: a role and a SERVICE user for the pipeline (key-pair login only, no password)
-- ---------------------------------------------------------------------------------------------
USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS PAYMENTS_ROLE;
GRANT USAGE, OPERATE ON WAREHOUSE PAYMENTS_WH TO ROLE PAYMENTS_ROLE;
GRANT ALL PRIVILEGES ON DATABASE PAYMENTS_DB TO ROLE PAYMENTS_ROLE;
GRANT ALL PRIVILEGES ON ALL SCHEMAS IN DATABASE PAYMENTS_DB TO ROLE PAYMENTS_ROLE;  -- includes CREATE STAGE, which the Spark connector needs
GRANT ROLE PAYMENTS_ROLE TO ROLE SYSADMIN;

CREATE USER IF NOT EXISTS PAYMENTS_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = PAYMENTS_ROLE
  DEFAULT_WAREHOUSE = PAYMENTS_WH
  RSA_PUBLIC_KEY = '<PASTE_THE_PUBLIC_KEY_TEXT_HERE>';   -- from make_snowflake_keys.py, one line, no BEGIN/END lines
GRANT ROLE PAYMENTS_ROLE TO USER PAYMENTS_SVC;

-- ---------------------------------------------------------------------------------------------
-- Step 3: check it worked. RSA_PUBLIC_KEY_FP should not be empty.
-- ---------------------------------------------------------------------------------------------
DESC USER PAYMENTS_SVC;

-- ---------------------------------------------------------------------------------------------
-- Clean-up when you are done (stops all cost and removes everything this project created):
--   USE ROLE SYSADMIN;      DROP DATABASE IF EXISTS PAYMENTS_DB;   DROP WAREHOUSE IF EXISTS PAYMENTS_WH;
--   USE ROLE SECURITYADMIN; DROP USER IF EXISTS PAYMENTS_SVC;      DROP ROLE IF EXISTS PAYMENTS_ROLE;
-- ---------------------------------------------------------------------------------------------
