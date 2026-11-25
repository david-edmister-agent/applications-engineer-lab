# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold: payroll staging + JDE export
# MAGIC
# MAGIC | Object | Purpose |
# MAGIC |---|---|
# MAGIC | `gold_payroll_stage` | One row per valid line, with rate, gross pay, and pay-period batch. Loaded with **MERGE**. |
# MAGIC | `gold_labor_by_job_costcode` | View: hours, labor cost, and headcount by week, job, and cost code |
# MAGIC | `vw_f06116z1_export` | View shaped like a JDE timecard batch (Z) table for payroll import |
# MAGIC
# MAGIC **Flow:** this stage → `vw_f06116z1_export` → a separate load process (Boomi, or a scheduled insert) writes the JDE timecard Z table → JDE's batch upload validates rows and moves them into the timecard table.
# MAGIC
# MAGIC **Idempotency:** `batch_id` is derived from the pay period (`PAY_WEEK_END` in `00_common`) rather than the run time.
# MAGIC Updates fire only when `_row_hash` changes. A second run with no new data reports 0 inserted, 0 updated, and 0 deleted.
# MAGIC
# MAGIC **Production note:** `whenNotMatchedBySourceDelete` removes lines that were superseded upstream.
# MAGIC In production, restrict updates and deletes to batches payroll hasn't processed yet, meaning the Z table's processed flag (`EDSP`) is still 0.
# MAGIC Changes to processed batches become adjustment lines in the next batch instead.

# COMMAND ----------

# MAGIC %run ./00_common

# COMMAND ----------

from delta.tables import DeltaTable

valid = spark.table(t("silver_timecard_lines"))
employees = spark.table(t("silver_employees"))
jobs = spark.table(t("silver_jobs"))

multiplier = F.create_map(*[F.lit(x) for kv in PAY_TYPE_MULTIPLIER.items() for x in kv])
pdba = F.create_map(*[F.lit(x) for kv in PDBA_CODE.items() for x in kv])

value_cols = [
    "batch_id", "pay_period_end", "revision", "address_number", "job_code", "business_unit",
    "pdba_code", "hours", "hourly_rate", "pay_rate", "gross_pay",
]

source = (
    valid
    .join(employees.select("employee_id", "address_number", "hourly_rate"), "employee_id")
    .join(jobs.select("job_code", "business_unit"), "job_code")
    # Pay period end = the first PAY_WEEK_END day on or after work_date.
    # (next_day returns the NEXT occurrence, so step back one day first to include work_date itself.)
    .withColumn("pay_period_end", F.next_day(F.date_sub("work_date", 1), PAY_WEEK_END))
    # Batch = pay period, e.g. PE20261108. Same data -> same batch on every run.
    .withColumn("batch_id", F.concat(F.lit("PE"), F.date_format("pay_period_end", "yyyyMMdd")))
    .withColumn("pdba_code", pdba[F.col("pay_type")])
    # Rate for this pay type = base hourly rate x multiplier (1.0 / 1.5 / 2.0).
    .withColumn("pay_rate", F.round(F.col("hourly_rate") * multiplier[F.col("pay_type")], 2).cast("decimal(8,2)"))
    .withColumn("gross_pay", F.round(F.col("hours") * F.col("pay_rate"), 2).cast("decimal(10,2)"))
    # Fingerprint of the payroll values; MERGE updates a row only when this changes.
    .withColumn("_row_hash", F.sha2(F.concat_ws("|", *[F.col(c).cast("string") for c in value_cols]), 256))
    .withColumn("_updated_at", F.current_timestamp())
    .select(*GOLD_KEY, *value_cols, "_row_hash", "_updated_at")
)

# COMMAND ----------

target = t("gold_payroll_stage")
if not spark.catalog.tableExists(target):
    source.limit(0).write.saveAsTable(target)

(
    DeltaTable.forName(spark, target).alias("t")
    .merge(source.alias("s"), " AND ".join(f"t.{k} = s.{k}" for k in GOLD_KEY))
    .whenMatchedUpdateAll(condition="t._row_hash <> s._row_hash")
    .whenNotMatchedInsertAll()
    .whenNotMatchedBySourceDelete()
    .execute()
)

metrics = DeltaTable.forName(spark, target).history(1).select("operationMetrics").first()[0]
for k in ["numTargetRowsInserted", "numTargetRowsUpdated", "numTargetRowsDeleted"]:
    print(f"{k:<24} {metrics.get(k)}")

# COMMAND ----------

# Job-cost reporting view — NOT part of the JDE export. Project managers track labor hours
# and cost against each job's budget by cost code each week; this is the feed for that
# (e.g. a Power BI report).
spark.sql(f"""
CREATE OR REPLACE VIEW {t('gold_labor_by_job_costcode')} AS
SELECT pay_period_end,
       job_code,
       business_unit,
       cost_code,
       pay_type,
       SUM(hours)                  AS hours,
       SUM(gross_pay)              AS labor_cost,
       COUNT(DISTINCT employee_id) AS headcount
FROM {target}
GROUP BY ALL
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ### JDE timecard batch export
# MAGIC Column aliases are modeled on JDE's timecard batch (Z) table, `F06116Z1`.
# MAGIC **Verify the names and data types against your release's data dictionary before you rely on them.**
# MAGIC The conventions shown here are standard JDE: dates are Julian `CYYDDD`, business units are 12 characters right-justified, and the employee is the numeric address book number.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {t('vw_f06116z1_export')} AS
SELECT
    'AELAB'                                                  AS VLEDUS,  -- batch user ID
    batch_id                                                 AS VLEDBT,  -- batch number
    CAST(ROW_NUMBER() OVER (
        PARTITION BY batch_id
        ORDER BY address_number, work_date, timecard_id, cost_code, pay_type) AS INT)
                                                             AS VLEDTN,  -- transaction number
    address_number                                           AS VLAN8,   -- employee address number
    (YEAR(work_date) - 1900) * 1000 + DAYOFYEAR(work_date)   AS VLDWK,   -- date worked, Julian CYYDDD
    pdba_code                                                AS VLPDBA,  -- pay type
    hours                                                    AS VLPHRW,  -- hours worked
    pay_rate                                                 AS VLSHRT,  -- hourly rate
    LPAD(business_unit, 12, ' ')                             AS VLMCU,   -- charge-out business unit
    cost_code                                                AS VLSUB,   -- subsidiary (cost code)
    '0'                                                      AS VLEDSP   -- processed flag: 0 = not yet processed; JDE batch upload sets 1
FROM {target}
""")

display(spark.table(t("vw_f06116z1_export")).limit(20))
