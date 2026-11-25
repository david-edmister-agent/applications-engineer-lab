"""Baseline timecards and defect injection (spec 5.4 and 6.2)."""

import copy
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import config as C
from master import catalog, job_cost_codes

HALF = C.HOURS_INCREMENT


def workdays(start: date, count: int) -> list[date]:
    days, d = [], start
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def count_entry_lines(entry: dict) -> int:
    """Lines in one cost-code entry: one per pay type with hours != 0 (spec 6.1)."""
    return sum(1 for k in ("regularHours", "overtimeHours", "doubleTimeHours") if entry[k] != 0)


def count_lines(record: dict, employee_id: str | None = None) -> int:
    return sum(
        count_entry_lines(cc)
        for emp in record["employees"]
        if employee_id is None or emp["employeeId"] == employee_id
        for cc in emp["costCodes"]
    )


@dataclass
class Timecard:
    day_idx: int
    job_idx: int
    record: dict


@dataclass
class Plan:
    files: dict[str, list[dict]]                 # file name -> records in file order
    injections: list[dict] = field(default_factory=list)
    expected_lines: dict[str, int] = field(default_factory=dict)  # from the injection plan


def build_crews(rng: random.Random, employees: list[dict], jobs: list[dict]) -> dict[str, list[str]]:
    """Fixed crew per job: its foreman first, then 4-7 non-foremen. No one is on two crews."""
    foremen = [e["employee_id"] for e in employees if e["craft"] == "Foreman"]
    others = [e["employee_id"] for e in employees if e["craft"] != "Foreman"]
    while True:
        sizes = [rng.randint(C.CREW_SIZE_MIN, C.CREW_SIZE_MAX) for _ in jobs]
        if sum(sizes) <= len(others):
            break
    rng.shuffle(others)
    crews, i = {}, 0
    for job, foreman, size in zip(jobs, foremen, sizes):
        crews[job["job_code"]] = [foreman, *sorted(others[i:i + size])]
        i += size
    return crews


def _employee_day(rng: random.Random, employee_id: str, codes: list[str]) -> dict:
    k = rng.randint(*C.COST_CODES_PER_EMPLOYEE)
    chosen = sorted(rng.sample(codes, k))
    reg_units = int(C.REGULAR_HOURS_PER_DAY / HALF)
    cuts = sorted(rng.sample(range(1, reg_units), k - 1))
    parts = [b - a for a, b in zip([0, *cuts], [*cuts, reg_units])]
    ot_units = rng.randint(0, int(C.MAX_OVERTIME_PER_DAY / HALF))
    ot_idx = rng.randrange(k)
    return {
        "employeeId": employee_id,
        "costCodes": [
            {
                "costCode": code,
                "regularHours": parts[j] * HALF,
                "overtimeHours": (ot_units * HALF) if j == ot_idx else 0.0,
                "doubleTimeHours": 0.0,
            }
            for j, code in enumerate(chosen)
        ],
    }


def file_name(d: date) -> str:
    return f"timecards_{d:%Y%m%d}.json"


def build_baseline(rng, days, jobs, crews) -> list[list[Timecard]]:
    seq = 0
    grid = []
    for di, d in enumerate(days):
        row = []
        for ji, job in enumerate(jobs):
            seq += 1
            crew = crews[job["job_code"]]
            codes = job_cost_codes(job["job_type"])
            record = {
                "timecardId": f"TC-{seq:06d}",
                "revision": 1,
                "jobCode": job["job_code"],
                "foremanId": crew[0],
                "date": d.isoformat(),
                "status": "Approved",
                "lastModified": f"{d.isoformat()}T{C.LAST_MODIFIED_TIME}",
                "employees": [_employee_day(rng, emp, codes) for emp in crew],
            }
            row.append(Timecard(di, ji, record))
        grid.append(row)
    return grid


def build(rng: random.Random, employees: list[dict], jobs: list[dict], start: date, n_days: int) -> Plan:
    days = workdays(start, n_days)
    crews = build_crews(rng, employees, jobs)
    grid = build_baseline(rng, days, jobs, crews)
    files = {file_name(d): [tc.record for tc in grid[i]] for i, d in enumerate(days)}
    plan = Plan(files=files)
    last = len(days) - 1
    cat = catalog()

    remaining = [tc for row in grid for tc in row]  # each defect takes a distinct timecard

    def take(pred=lambda tc: True) -> Timecard:
        candidates = [tc for tc in remaining if pred(tc)]
        if not candidates:
            raise RuntimeError("Exclusivity rule cannot be satisfied: no eligible timecard left")
        tc = rng.choice(candidates)
        remaining.remove(tc)
        return tc

    def codes_for(tc: Timecard) -> list[str]:
        return job_cost_codes(jobs[tc.job_idx]["job_type"])

    def log(defect: str, tc_or_record, fname: str, detail: str, lines: int, bucket: str | None = None):
        rec = tc_or_record.record if isinstance(tc_or_record, Timecard) else tc_or_record
        plan.injections.append({"defect": defect, "timecardId": rec["timecardId"], "file": fname, "detail": detail})
        key = bucket or defect
        plan.expected_lines[key] = plan.expected_lines.get(key, 0) + lines

    def fname_of(tc: Timecard) -> str:
        return file_name(days[tc.day_idx])

    for key in ["exact_duplicate_lines", "superseded_lines", *C.DQ_REASONS]:
        plan.expected_lines[key] = 0

    # OVER_24_HOURS first: it needs two clean timecards on the same day (home + second job).
    for _ in range(C.DEFECT_PLAN["OVER_24_HOURS"]):
        home = take()
        other = take(lambda tc: tc.day_idx == home.day_idx and tc.job_idx != home.job_idx)
        emp = rng.choice([e["employeeId"] for e in home.record["employees"][1:]])
        code = rng.choice(codes_for(other))
        other.record["employees"].append({
            "employeeId": emp,
            "costCodes": [{"costCode": code, "regularHours": C.OVER_24_REG_HOURS,
                           "overtimeHours": C.OVER_24_OT_HOURS, "doubleTimeHours": 0.0}],
        })
        lines = count_lines(home.record, emp) + 2
        log("OVER_24_HOURS", other, fname_of(other),
            f"{emp} (crew of {home.record['jobCode']}, {home.record['timecardId']}) also charged "
            f"{C.OVER_24_REG_HOURS} REG + {C.OVER_24_OT_HOURS} OT to {other.record['jobCode']} cost code {code}",
            lines)

    # SUPERSEDED: revision 2 in a later file, 1.0 REG moved between two entries of one employee.
    def has_multi_code(tc: Timecard) -> bool:
        return any(len(e["costCodes"]) >= 2 for e in tc.record["employees"])

    for _ in range(C.DEFECT_PLAN["SUPERSEDED"]):
        tc = take(lambda t: t.day_idx < last and has_multi_code(t))
        rev2 = copy.deepcopy(tc.record)
        emp = rng.choice([e for e in rev2["employees"] if len(e["costCodes"]) >= 2])
        sources = [c for c in emp["costCodes"] if c["regularHours"] >= C.SUPERSEDED_MIN_SOURCE_REG]
        src = rng.choice(sources)
        dst = rng.choice([c for c in emp["costCodes"] if c is not src])
        src["regularHours"] -= C.SUPERSEDED_MOVE_HOURS
        dst["regularHours"] += C.SUPERSEDED_MOVE_HOURS
        later = days[rng.randint(tc.day_idx + 1, last)]
        rev2["revision"] = 2
        rev2["lastModified"] = f"{later.isoformat()}T{C.LAST_MODIFIED_TIME}"
        plan.files[file_name(later)].append(rev2)
        log("SUPERSEDED", tc, file_name(later),
            f"revision 2 moves {C.SUPERSEDED_MOVE_HOURS} REG for {emp['employeeId']} "
            f"from {src['costCode']} to {dst['costCode']}; revision 1 in {fname_of(tc)}",
            count_lines(tc.record), "superseded_lines")

    # EXACT_DUPLICATE: identical record re-emitted in the next workday's file.
    for _ in range(C.DEFECT_PLAN["EXACT_DUPLICATE"]):
        tc = take(lambda t: t.day_idx < last)
        nxt = file_name(days[tc.day_idx + 1])
        plan.files[nxt].append(copy.deepcopy(tc.record))
        log("EXACT_DUPLICATE", tc, nxt, f"identical copy of the record in {fname_of(tc)}",
            count_lines(tc.record), "exact_duplicate_lines")

    for _ in range(C.DEFECT_PLAN["MISSING_JOB"]):
        tc = take()
        was = tc.record["jobCode"]
        tc.record["jobCode"] = ""
        log("MISSING_JOB", tc, fname_of(tc), f"jobCode blanked (was {was})", count_lines(tc.record))

    for _ in range(C.DEFECT_PLAN["UNKNOWN_JOB"]):
        tc = take()
        was = tc.record["jobCode"]
        tc.record["jobCode"] = C.UNKNOWN_JOB_CODE
        log("UNKNOWN_JOB", tc, fname_of(tc), f"jobCode {was} -> {C.UNKNOWN_JOB_CODE}", count_lines(tc.record))

    for emp_id in C.UNKNOWN_EMPLOYEE_IDS[:C.DEFECT_PLAN["UNKNOWN_EMPLOYEE"]]:
        tc = take()
        code = rng.choice(codes_for(tc))
        tc.record["employees"].append({
            "employeeId": emp_id,
            "costCodes": [{"costCode": code, "regularHours": C.UNKNOWN_EMPLOYEE_REG_HOURS,
                           "overtimeHours": 0.0, "doubleTimeHours": 0.0}],
        })
        log("UNKNOWN_EMPLOYEE", tc, fname_of(tc),
            f"added {emp_id} with {C.UNKNOWN_EMPLOYEE_REG_HOURS} REG on {code}", 1)

    for _ in range(C.DEFECT_PLAN["INVALID_COST_CODE"]):
        tc = take()
        assigned = set(codes_for(tc))
        emp = rng.choice(tc.record["employees"])
        entry = rng.choice(emp["costCodes"])
        new = rng.choice([c for c in cat if c not in assigned])
        log("INVALID_COST_CODE", tc, fname_of(tc),
            f"{emp['employeeId']} cost code {entry['costCode']} -> {new} (not assigned to {tc.record['jobCode']})",
            count_entry_lines(entry))
        entry["costCode"] = new

    for _ in range(C.DEFECT_PLAN["NEGATIVE_HOURS"]):
        tc = take()
        emp = rng.choice(tc.record["employees"])
        entry = rng.choice(emp["costCodes"])
        log("NEGATIVE_HOURS", tc, fname_of(tc),
            f"{emp['employeeId']} cost code {entry['costCode']} regularHours "
            f"{entry['regularHours']} -> {C.NEGATIVE_REG_HOURS}", 1)
        entry["regularHours"] = C.NEGATIVE_REG_HOURS

    for _ in range(C.DEFECT_PLAN["NOT_APPROVED"]):
        tc = take()
        tc.record["status"] = C.NOT_APPROVED_STATUS
        log("NOT_APPROVED", tc, fname_of(tc), f"status Approved -> {C.NOT_APPROVED_STATUS}", count_lines(tc.record))

    return plan
