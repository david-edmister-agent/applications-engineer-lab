# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Common config and helpers
# MAGIC
# MAGIC Every other notebook loads this one with `%run ./00_common`. It holds names, the raw timecard schema, and the **line definition**.
# MAGIC
# MAGIC **Line** = one row per timecard record × employee × cost code × pay type, where hours ≠ 0.
# MAGIC The generator's `manifest.json` uses the same definition, so bronze, silver, and gold reconcile exactly.
# MAGIC
# MAGIC **First-time setup:** Run this notebook once to create the schema and volume. Then upload the generator output:
# MAGIC **Catalog** → `workspace` → `ae_lab` → **Volumes** → `landing` → **Upload to this volume**.
# MAGIC Put the files into the folders `master/`, `timecards/`, and `manifest/`.

# COMMAND ----------

from pyspark.sql import DataFrame, functions as F

CATALOG = "workspace"  # Free Edition default catalog
SCHEMA = "ae_lab"
VOLUME = "landing"

VOLUME_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
TIMECARD_PATH = f"{VOLUME_ROOT}/timecards"
MASTER_PATH = f"{VOLUME_ROOT}/master"
MANIFEST_PATH = f"{VOLUME_ROOT}/manifest/manifest.json"
CHECKPOINT_ROOT = f"{VOLUME_ROOT}/_checkpoints"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")


def t(name: str) -> str:
    """Fully qualified table name."""
    return f"{CATALOG}.{SCHEMA}.{name}"


# Raw HeavyJob-style timecard: one JSON object per line (NDJSON)
TIMECARD_SCHEMA = """
    timecardId STRING,
    revision INT,
    jobCode STRING,
    foremanId STRING,
    date STRING,
    status STRING,
    lastModified STRING,
    employees ARRAY<STRUCT<
        employeeId STRING,
        costCodes ARRAY<STRUCT<
            costCode STRING,
            regularHours DOUBLE,
            overtimeHours DOUBLE,
            doubleTimeHours DOUBLE>>>>
"""

# Pay type multipliers, applied to the employee's base hourly rate in gold:
#   REG = straight time (1.0x), OT = time-and-a-half (1.5x), DT = double time (2.0x).
# Which hours count as OT or DT is decided upstream (union agreement, state law —
# California: daily OT after 8 hours, DT after 12). This lab trusts the hours as reported.
PAY_TYPE_MULTIPLIER = {"REG": 1.0, "OT": 1.5, "DT": 2.0}

# PDBA = Pay, Deduction, Benefit, Accrual. JDE identifies every pay type by a numeric PDBA
# code that each company defines in its own payroll setup. 1/2/3 are placeholders; replace
# them with the target system's codes.
PDBA_CODE = {"REG": 1, "OT": 2, "DT": 3}

# Last day of the weekly pay period. The pay cycle is configured in the payroll system;
# change this one value to match it. Gold derives each line's batch from this.
PAY_WEEK_END = "Sun"

# Natural key of a payroll staging line
GOLD_KEY = ["timecard_id", "employee_id", "work_date", "cost_code", "pay_type"]

DQ_REASONS = [
    "MISSING_JOB", "UNKNOWN_JOB", "UNKNOWN_EMPLOYEE", "INVALID_COST_CODE",
    "NEGATIVE_HOURS", "OVER_24_HOURS", "NOT_APPROVED",
]


def explode_timecard_lines(df: DataFrame, passthrough: list | None = None) -> DataFrame:
    """Flatten raw timecard records to lines (see the line definition above).

    passthrough: extra columns from df to carry onto every line (silver uses this to carry
    the record-level dedup_status down to each line).

    One timecard record nests employees, and each employee nests cost codes, and each cost
    code holds three hour buckets. Flattening:
      explode(employees)  -> one row per employee on the timecard
      explode(costCodes)  -> one row per employee x cost code
      stack(3, ...)       -> one row per employee x cost code x pay type (REG/OT/DT)
    Rows with 0 hours are dropped, so a cost code with only REG hours yields one line.
    """
    passthrough = passthrough or []
    emp = df.select("*", F.explode("employees").alias("_e"))
    cc = emp.select("*", F.explode("_e.costCodes").alias("_c"))
    lines = cc.select(
        F.col("timecardId").alias("timecard_id"),
        F.col("revision"),
        F.expr("nullif(trim(jobCode), '')").alias("job_code"),
        F.col("foremanId").alias("foreman_id"),
        F.to_date("date").alias("work_date"),
        F.col("status"),
        F.col("_e.employeeId").alias("employee_id"),
        F.col("_c.costCode").alias("cost_code"),
        F.expr("""stack(3,
            'REG', cast(_c.regularHours    as decimal(6,2)),
            'OT',  cast(_c.overtimeHours   as decimal(6,2)),
            'DT',  cast(_c.doubleTimeHours as decimal(6,2))
        ) as (pay_type, hours)"""),
        *passthrough,
    )
    return lines.where(F.col("hours").isNotNull() & (F.col("hours") != 0))
