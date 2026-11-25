# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze ingest
# MAGIC
# MAGIC Lands raw files from the Volume exactly as received, plus lineage columns (`_source_file` and `_ingested_at`). Nothing is cleansed here.
# MAGIC
# MAGIC | Source | Method | Why |
# MAGIC |---|---|---|
# MAGIC | Timecards (NDJSON) | Auto Loader, `availableNow` | Incremental: each run reads only files it hasn't seen. Unexpected fields go to `_rescued_data` instead of failing the load. |
# MAGIC | Master data (CSV) | `COPY INTO` | Idempotent by file: a file that's already loaded is skipped on rerun. Every column is loaded as a string; types are applied in silver. |
# MAGIC
# MAGIC The Volume stands in for an SFTP landing folder. In production, an integration platform such as Boomi or a scheduled transfer would drop files there.

# COMMAND ----------

# MAGIC %run ./00_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Timecards → `bronze_timecards`

# COMMAND ----------

query = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("rescuedDataColumn", "_rescued_data")
    .schema(TIMECARD_SCHEMA)
    .load(TIMECARD_PATH)
    .select(
        "*",
        F.col("_metadata.file_path").alias("_source_file"),
        F.current_timestamp().alias("_ingested_at"),
    )
    .writeStream
    .option("checkpointLocation", f"{CHECKPOINT_ROOT}/bronze_timecards")
    .trigger(availableNow=True)
    .toTable(t("bronze_timecards"))
)
query.awaitTermination()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Master data → `bronze_employees`, `bronze_jobs`, `bronze_cost_codes`
# MAGIC
# MAGIC `bronze_employees` holds the full (fake) SSN as received from the source.
# MAGIC In production, access to this table would be restricted with Unity Catalog grants or a column mask.
# MAGIC Silver keeps only the last 4 digits.

# COMMAND ----------

MASTER_FILES = {
    "bronze_employees": "employees.csv",
    "bronze_jobs": "jobs.csv",
    "bronze_cost_codes": "cost_codes.csv",
}

for table, pattern in MASTER_FILES.items():
    spark.sql(f"CREATE TABLE IF NOT EXISTS {t(table)}")
    result = spark.sql(f"""
        COPY INTO {t(table)}
        FROM (
            SELECT *,
                   _metadata.file_path AS _source_file,
                   current_timestamp() AS _ingested_at
            FROM '{MASTER_PATH}'
        )
        FILEFORMAT = CSV
        PATTERN = '{pattern}'
        FORMAT_OPTIONS ('header' = 'true', 'inferSchema' = 'false')
        COPY_OPTIONS ('mergeSchema' = 'true')
    """).first()
    print(f"{table:<20} loaded={result['num_inserted_rows']}")

# COMMAND ----------

for name in ["bronze_timecards", *MASTER_FILES]:
    print(f"{name:<20} {spark.table(t(name)).count():>8,} rows")
