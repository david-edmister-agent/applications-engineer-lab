# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver: types, dedup, validation, quarantine
# MAGIC
# MAGIC Silver is fully recomputed from bronze on each run, which makes reruns safe.
# MAGIC
# MAGIC | Output table | Contents |
# MAGIC |---|---|
# MAGIC | `silver_employees` / `silver_jobs` / `silver_cost_codes` | Typed master data with the latest load per key. SSN is reduced to `ssn_last4`. |
# MAGIC | `silver_timecard_removed` | Lines dropped by dedup, tagged `EXACT_DUPLICATE` or `SUPERSEDED` |
# MAGIC | `silver_timecard_lines` | Current lines that pass every rule |
# MAGIC | `silver_timecard_quarantine` | Current lines that fail one or more rules, with a `dq_reasons` array |
# MAGIC
# MAGIC **Dedup order**
# MAGIC 1. For the same (timecardId, revision), keep the earliest landed copy.
# MAGIC 2. Within a timecard, keep only the max revision.

# COMMAND ----------

# MAGIC %run ./00_common

# COMMAND ----------

from pyspark.sql import Window


def latest(df, keys):
    """Keep the most recently landed row per key."""
    w = Window.partitionBy(*keys).orderBy(F.col("_ingested_at").desc(), F.col("_source_file").desc())
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


def save(df, name):
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t(name))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Master data

# COMMAND ----------

employees = latest(spark.table(t("bronze_employees")), ["employee_id"]).select(
    "employee_id",
    F.col("address_number").cast("int").alias("address_number"),
    "first_name",
    "last_name",
    "craft",
    "union_local",
    F.col("pay_rate").cast("decimal(8,2)").alias("hourly_rate"),
    F.to_date("hire_date").alias("hire_date"),
    "status",
    # PII: keep the last 4 digits only. The full SSN never leaves bronze.
    F.expr("right(regexp_replace(ssn, '[^0-9]', ''), 4)").alias("ssn_last4"),
)

jobs = latest(spark.table(t("bronze_jobs")), ["job_code"]).select(
    "job_code", "job_description", "business_unit", "status"
)

cost_codes = latest(spark.table(t("bronze_cost_codes")), ["job_code", "cost_code"]).select(
    "job_code", "cost_code", "description", "unit_of_measure"
)

save(employees, "silver_employees")
save(jobs, "silver_jobs")
save(cost_codes, "silver_cost_codes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Dedup
# MAGIC A record's status is decided at the record level and then carried onto each of its lines.

# COMMAND ----------

w_copy = Window.partitionBy("timecardId", "revision").orderBy("_ingested_at", "_source_file")
w_card = Window.partitionBy("timecardId")

records = (
    spark.table(t("bronze_timecards"))
    .withColumn("_copy_rank", F.row_number().over(w_copy))
    .withColumn("_max_revision", F.max("revision").over(w_card))
    .withColumn(
        "dedup_status",
        F.when(F.col("_copy_rank") > 1, "EXACT_DUPLICATE")
        .when(F.col("revision") < F.col("_max_revision"), "SUPERSEDED")
        .otherwise("CURRENT"),
    )
)

lines = explode_timecard_lines(records, passthrough=["dedup_status", "_source_file", "_ingested_at"])

save(lines.where("dedup_status <> 'CURRENT'"), "silver_timecard_removed")
current = lines.where("dedup_status = 'CURRENT'").drop("dedup_status")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Validation
# MAGIC Every rule is evaluated, and `dq_reasons` collects each rule a line fails.
# MAGIC `OVER_24_HOURS` is checked at the employee-day level across all current timecards, so an employee charging two jobs on the same day is caught.

# COMMAND ----------

job_keys = jobs.select("job_code", F.lit(True).alias("_job_found"))
emp_keys = employees.select("employee_id", F.lit(True).alias("_emp_found"))
cc_keys = cost_codes.select("job_code", "cost_code", F.lit(True).alias("_cc_found"))
w_day = Window.partitionBy("employee_id", "work_date")

checked = (
    current
    .join(job_keys, "job_code", "left")
    .join(emp_keys, "employee_id", "left")
    .join(cc_keys, ["job_code", "cost_code"], "left")
    .withColumn(
        "employee_day_hours",
        F.sum(F.when(F.col("hours") > 0, F.col("hours")).otherwise(F.lit(0))).over(w_day),
    )
    .withColumn(
        "dq_reasons",
        F.array_compact(F.array(
            F.when(F.col("job_code").isNull(), F.lit("MISSING_JOB")),
            F.when(F.col("job_code").isNotNull() & F.col("_job_found").isNull(), F.lit("UNKNOWN_JOB")),
            F.when(F.col("_emp_found").isNull(), F.lit("UNKNOWN_EMPLOYEE")),
            F.when(F.col("_job_found") & F.col("_cc_found").isNull(), F.lit("INVALID_COST_CODE")),
            F.when(F.col("hours") < 0, F.lit("NEGATIVE_HOURS")),
            F.when(F.col("employee_day_hours") > 24, F.lit("OVER_24_HOURS")),
            F.when(F.coalesce(F.col("status"), F.lit("")) != "Approved", F.lit("NOT_APPROVED")),
        )),
    )
    .drop("_job_found", "_emp_found", "_cc_found")
)

save(
    checked.where(F.size("dq_reasons") == 0).drop("dq_reasons", "employee_day_hours"),
    "silver_timecard_lines",
)
save(
    checked.where(F.size("dq_reasons") > 0).withColumn("quarantined_at", F.current_timestamp()),
    "silver_timecard_quarantine",
)

# COMMAND ----------

display(
    spark.table(t("silver_timecard_quarantine"))
    .select(F.explode("dq_reasons").alias("reason"))
    .groupBy("reason").count().orderBy("reason")
)
