# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Reconciliation
# MAGIC
# MAGIC This notebook proves that no line was lost or double-counted between bronze and gold. It also proves that Spark agrees with the generator's independent pure-Python count in `manifest.json`.
# MAGIC
# MAGIC **Identity:** `bronze_lines = exact_duplicate + superseded + valid + quarantine`
# MAGIC
# MAGIC Each run appends one row to `ops_run_log`. That row is the status record Power Automate will read.
# MAGIC If any check fails, the notebook raises an error, so the job task fails visibly.

# COMMAND ----------

# MAGIC %run ./00_common

# COMMAND ----------

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

bronze_lines = explode_timecard_lines(spark.table(t("bronze_timecards")))
removed = spark.table(t("silver_timecard_removed"))
valid = spark.table(t("silver_timecard_lines"))
quarantine = spark.table(t("silver_timecard_quarantine"))
gold = spark.table(t("gold_payroll_stage"))

removed_counts = {r["dedup_status"]: r["count"] for r in removed.groupBy("dedup_status").count().collect()}
reason_counts = {
    r["reason"]: r["count"]
    for r in quarantine.select(F.explode("dq_reasons").alias("reason")).groupBy("reason").count().collect()
}


def dsum(df):
    return Decimal(df.agg(F.sum("hours")).first()[0] or 0).quantize(Decimal("0.01"))


actual = {
    "bronze_lines": bronze_lines.count(),
    "exact_duplicate_lines": removed_counts.get("EXACT_DUPLICATE", 0),
    "superseded_lines": removed_counts.get("SUPERSEDED", 0),
    "valid_lines": valid.count(),
    "quarantine_lines": quarantine.count(),
    "gold_rows": gold.count(),
    "valid_hours": dsum(valid),
    "gold_hours": dsum(gold),
    "multi_reason_lines": quarantine.where(F.size("dq_reasons") > 1).count(),
    "gold_duplicate_keys": gold.groupBy(*GOLD_KEY).count().where("count > 1").count(),
}

with open(MANIFEST_PATH) as f:
    expected = json.load(f)["expected"]

# COMMAND ----------

a = actual
checks = [
    ("identity: bronze = dup + superseded + valid + quarantine",
     a["bronze_lines"] == a["exact_duplicate_lines"] + a["superseded_lines"] + a["valid_lines"] + a["quarantine_lines"],
     f'{a["bronze_lines"]} vs {a["exact_duplicate_lines"]}+{a["superseded_lines"]}+{a["valid_lines"]}+{a["quarantine_lines"]}'),
    ("gold rows = valid lines", a["gold_rows"] == a["valid_lines"], f'{a["gold_rows"]} vs {a["valid_lines"]}'),
    ("gold hours = valid hours", a["gold_hours"] == a["valid_hours"], f'{a["gold_hours"]} vs {a["valid_hours"]}'),
    ("gold key unique", a["gold_duplicate_keys"] == 0, f'{a["gold_duplicate_keys"]} duplicate keys'),
    ("one reason per quarantined line", a["multi_reason_lines"] == 0, f'{a["multi_reason_lines"]} lines'),
]

for k in ["bronze_lines", "exact_duplicate_lines", "superseded_lines", "valid_lines", "quarantine_lines"]:
    checks.append((f"manifest: {k}", a[k] == expected[k], f"spark {a[k]} vs manifest {expected[k]}"))

checks.append(("manifest: valid_hours", a["valid_hours"] == Decimal(expected["valid_hours"]),
               f'spark {a["valid_hours"]} vs manifest {expected["valid_hours"]}'))

for reason in DQ_REASONS:
    got, want = reason_counts.get(reason, 0), expected["quarantine_lines_by_reason"].get(reason, 0)
    checks.append((f"manifest: quarantine {reason}", got == want, f"spark {got} vs manifest {want}"))

display(spark.createDataFrame([(n, bool(p), d) for n, p, d in checks], "check STRING, passed BOOLEAN, detail STRING"))

# COMMAND ----------

failed = [n for n, p, _ in checks if not p]

run_schema = """
    run_id STRING, run_at TIMESTAMP, status STRING,
    bronze_lines BIGINT, exact_duplicate_lines BIGINT, superseded_lines BIGINT,
    valid_lines BIGINT, quarantine_lines BIGINT, gold_rows BIGINT, gold_hours DECIMAL(12,2),
    quarantine_by_reason STRING, failed_checks STRING
"""
run_row = (
    str(uuid.uuid4()), datetime.now(timezone.utc), "FAIL" if failed else "PASS",
    a["bronze_lines"], a["exact_duplicate_lines"], a["superseded_lines"],
    a["valid_lines"], a["quarantine_lines"], a["gold_rows"], a["gold_hours"],
    json.dumps(reason_counts, sort_keys=True), json.dumps(failed),
)
spark.createDataFrame([run_row], run_schema).write.mode("append").saveAsTable(t("ops_run_log"))

if failed:
    raise AssertionError(f"Reconciliation failed: {failed}")
print(f"PASS: {len(checks)} checks")
