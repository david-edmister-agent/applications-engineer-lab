"""Synthetic HeavyJob-style timecard generator (SPEC-01).

Usage:
    python data/generator/generate.py --seed 42 --start-date 2026-11-02 --workdays 10 --out data/output
"""

import argparse
import csv
import json
import random
import shutil
import sys
from datetime import date
from pathlib import Path

from faker import Faker

import config as C
import manifest
import master
import timecards


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    p.add_argument("--start-date", default=C.DEFAULT_START_DATE, help="ISO date; must be a Monday")
    p.add_argument("--workdays", type=int, default=C.DEFAULT_WORKDAYS)
    p.add_argument("--out", default="data/output")
    return p.parse_args(argv)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        for row in rows:
            w.writerow([row[c] for c in columns])


def write_ndjson(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def wipe(out: Path) -> None:
    if out.exists():
        if (out / ".git").exists() or not out.is_dir():
            sys.exit(f"Refusing to wipe {out}: not a plain output directory")
        shutil.rmtree(out)
    out.mkdir(parents=True)


def check_plan(plan: timecards.Plan, expected: dict) -> list[str]:
    """Compare the manifest's independent counts with what the injection plan says they should be."""
    bronze = sum(timecards.count_lines(r) for recs in plan.files.values() for r in recs)
    planned_q = {r: plan.expected_lines[r] for r in C.DQ_REASONS}
    planned_q_total = sum(planned_q.values())
    want = {
        "bronze_lines": bronze,
        "exact_duplicate_lines": plan.expected_lines["exact_duplicate_lines"],
        "superseded_lines": plan.expected_lines["superseded_lines"],
        "quarantine_lines": planned_q_total,
        "valid_lines": bronze - planned_q_total - plan.expected_lines["exact_duplicate_lines"]
        - plan.expected_lines["superseded_lines"],
    }
    errors = [f"{k}: manifest {expected[k]} vs plan {v}" for k, v in want.items() if expected[k] != v]
    errors += [
        f"quarantine {r}: manifest {expected['quarantine_lines_by_reason'][r]} vs plan {v}"
        for r, v in planned_q.items() if expected["quarantine_lines_by_reason"][r] != v
    ]
    counts = {}
    for inj in plan.injections:
        counts[inj["defect"]] = counts.get(inj["defect"], 0) + 1
    errors += [f"injections {d}: {counts.get(d, 0)} vs plan {n}" for d, n in C.DEFECT_PLAN.items() if counts.get(d, 0) != n]
    return errors


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        start = date.fromisoformat(args.start_date)
    except ValueError:
        print(f"error: --start-date {args.start_date!r} is not an ISO date", file=sys.stderr)
        return 2
    if start.weekday() != 0:
        print(f"error: --start-date {start} is a {start:%A}; it must be a Monday", file=sys.stderr)
        return 2
    if args.workdays < 1:
        print("error: --workdays must be at least 1", file=sys.stderr)
        return 2

    out = Path(args.out)
    wipe(out)

    Faker.seed(args.seed)
    fake = Faker("en_US")
    rng = random.Random(args.seed)

    employees = master.build_employees(rng, fake)
    jobs = master.build_jobs()
    cost_codes = master.build_cost_codes(jobs)
    write_csv(out / "master" / "employees.csv", master.EMPLOYEE_COLUMNS, employees)
    write_csv(out / "master" / "jobs.csv", master.JOB_COLUMNS, jobs)
    write_csv(out / "master" / "cost_codes.csv", master.COST_CODE_COLUMNS, cost_codes)

    plan = timecards.build(rng, employees, jobs, start, args.workdays)
    for name, records in plan.files.items():
        write_ndjson(out / "timecards" / name, records)

    doc = manifest.build_manifest(out, args.seed, plan.injections)
    manifest.write_manifest(out, doc)

    errors = check_plan(plan, doc["expected"])
    if errors:
        print("error: manifest disagrees with injection plan:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1

    e = doc["expected"]
    print(f"Wrote {len(plan.files)} timecard files to {out}")
    print(json.dumps(e, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
