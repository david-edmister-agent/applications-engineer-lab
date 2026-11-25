"""Independent re-read and count of the generated files (spec 6.3-6.5).

This module reads only what is on disk. It does not import the generation plan. It mirrors
the dedup and validation semantics of 01-databricks/notebooks/02_silver_validate.py.
"""

import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

REASONS = [
    "MISSING_JOB", "UNKNOWN_JOB", "UNKNOWN_EMPLOYEE", "INVALID_COST_CODE",
    "NEGATIVE_HOURS", "OVER_24_HOURS", "NOT_APPROVED",
]
PAY_TYPES = [("REG", "regularHours"), ("OT", "overtimeHours"), ("DT", "doubleTimeHours")]
LINE_DEFINITION = "timecard record x employee x cost code x pay type, hours != 0"


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _explode(record: dict, source_file: str) -> list[dict]:
    """One line per employee x cost code x pay type with hours != 0 (00_common.explode_timecard_lines)."""
    job = record.get("jobCode")
    job = job.strip() if isinstance(job, str) else None
    out = []
    for emp in record.get("employees") or []:
        for cc in emp.get("costCodes") or []:
            for pay_type, key in PAY_TYPES:
                raw = cc.get(key)
                if raw is None:
                    continue
                hours = Decimal(str(raw)).quantize(Decimal("0.01"))
                if hours == 0:
                    continue
                out.append({
                    "timecard_id": record.get("timecardId"),
                    "revision": record.get("revision"),
                    "job_code": job or None,
                    "work_date": record.get("date"),
                    "status": record.get("status"),
                    "employee_id": emp.get("employeeId"),
                    "cost_code": cc.get("costCode"),
                    "pay_type": pay_type,
                    "hours": hours,
                    "source_file": source_file,
                })
    return out


def classify(out_dir: Path) -> list[dict]:
    """Every bronze line, tagged with dedup_status and (for CURRENT lines) dq_reasons."""
    out_dir = Path(out_dir)
    master = out_dir / "master"
    job_codes = {r["job_code"] for r in _read_csv(master / "jobs.csv")}
    employee_ids = {r["employee_id"] for r in _read_csv(master / "employees.csv")}
    job_cost = {(r["job_code"], r["cost_code"]) for r in _read_csv(master / "cost_codes.csv")}

    records = []  # (record, file) in landing order: file name, then line order
    for path in sorted((out_dir / "timecards").glob("*.json")):
        with open(path, encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    records.append((json.loads(raw), path.name))

    # Dedup at record level. Step 1: earliest copy of (timecardId, revision) wins.
    seen = set()
    max_rev = defaultdict(int)
    tagged = []
    for rec, fname in records:
        key = (rec["timecardId"], rec["revision"])
        if key in seen:
            status = "EXACT_DUPLICATE"
        else:
            seen.add(key)
            status = None
            max_rev[rec["timecardId"]] = max(max_rev[rec["timecardId"]], rec["revision"])
        tagged.append((rec, fname, status))

    # Step 2: among survivors, revisions below the max are superseded.
    lines = []
    for rec, fname, status in tagged:
        if status is None:
            status = "SUPERSEDED" if rec["revision"] < max_rev[rec["timecardId"]] else "CURRENT"
        for line in _explode(rec, fname):
            line["dedup_status"] = status
            lines.append(line)

    # Step 3: validate CURRENT lines.
    current = [ln for ln in lines if ln["dedup_status"] == "CURRENT"]
    day_hours = defaultdict(Decimal)
    for ln in current:
        if ln["hours"] > 0:
            day_hours[(ln["employee_id"], ln["work_date"])] += ln["hours"]

    for ln in current:
        reasons = []
        job = ln["job_code"]
        job_found = job is not None and job in job_codes
        if job is None:
            reasons.append("MISSING_JOB")
        if job is not None and not job_found:
            reasons.append("UNKNOWN_JOB")
        if ln["employee_id"] not in employee_ids:
            reasons.append("UNKNOWN_EMPLOYEE")
        if job_found and (job, ln["cost_code"]) not in job_cost:
            reasons.append("INVALID_COST_CODE")
        if ln["hours"] < 0:
            reasons.append("NEGATIVE_HOURS")
        if day_hours[(ln["employee_id"], ln["work_date"])] > 24:
            reasons.append("OVER_24_HOURS")
        if (ln["status"] or "") != "Approved":
            reasons.append("NOT_APPROVED")
        ln["dq_reasons"] = reasons
    return lines


def compute_expected(out_dir: Path) -> dict:
    lines = classify(out_dir)
    current = [ln for ln in lines if ln["dedup_status"] == "CURRENT"]
    valid = [ln for ln in current if not ln["dq_reasons"]]
    quarantine = [ln for ln in current if ln["dq_reasons"]]
    by_reason = {r: 0 for r in REASONS}
    for ln in quarantine:
        for r in ln["dq_reasons"]:
            by_reason[r] += 1
    valid_hours = sum((ln["hours"] for ln in valid), Decimal("0")).quantize(Decimal("0.01"))
    return {
        "bronze_lines": len(lines),
        "exact_duplicate_lines": sum(ln["dedup_status"] == "EXACT_DUPLICATE" for ln in lines),
        "superseded_lines": sum(ln["dedup_status"] == "SUPERSEDED" for ln in lines),
        "valid_lines": len(valid),
        "quarantine_lines": len(quarantine),
        "quarantine_lines_by_reason": by_reason,
        "valid_hours": f"{valid_hours:.2f}",
    }


def build_manifest(out_dir: Path, seed: int, injections: list[dict]) -> dict:
    return {
        "seed": seed,
        "line_definition": LINE_DEFINITION,
        "expected": compute_expected(out_dir),
        "injections": injections,
    }


def write_manifest(out_dir: Path, manifest: dict) -> Path:
    path = Path(out_dir) / "manifest" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    return path
