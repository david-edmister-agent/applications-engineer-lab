"""Master data: employees, jobs, and job cost codes (spec 5.1-5.3)."""

import random
from datetime import date, timedelta

from faker import Faker

import config as C

EMPLOYEE_COLUMNS = [
    "employee_id", "address_number", "first_name", "last_name", "ssn",
    "craft", "union_local", "pay_rate", "hire_date", "status",
]
JOB_COLUMNS = ["job_code", "job_type", "client", "job_description", "business_unit", "status"]
COST_CODE_COLUMNS = ["job_code", "cost_code", "description", "unit_of_measure"]


def _fake_ssn(rng: random.Random) -> str:
    # Area 900-999 is never issued, so these are guaranteed fake.
    return f"{rng.randint(900, 999)}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"


def build_employees(rng: random.Random, fake: Faker) -> list[dict]:
    hire_min = date.fromisoformat(C.HIRE_DATE_MIN)
    hire_span = (date.fromisoformat(C.HIRE_DATE_MAX) - hire_min).days
    seen_ssn = set()
    rows = []
    for i in range(C.EMPLOYEE_COUNT):
        craft = "Foreman" if i < C.FOREMAN_COUNT else rng.choice(C.NON_FOREMAN_CRAFTS)
        lo, hi = C.PAY_RATE_RANGES[craft]
        ssn = _fake_ssn(rng)
        while ssn in seen_ssn:
            ssn = _fake_ssn(rng)
        seen_ssn.add(ssn)
        rows.append({
            "employee_id": f"E{C.EMPLOYEE_ID_START + i}",
            "address_number": C.ADDRESS_NUMBER_START + i,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "ssn": ssn,
            "craft": craft,
            "union_local": rng.choice(C.UNION_LOCALS),
            "pay_rate": f"{rng.randint(lo * 100, hi * 100) / 100:.2f}",
            "hire_date": (hire_min + timedelta(days=rng.randint(0, hire_span))).isoformat(),
            "status": "A",
        })
    return rows


def build_jobs() -> list[dict]:
    rows = []
    for job_code, job_type, description in C.JOBS:
        number = job_code.split("-")[1]
        rows.append({
            "job_code": job_code,
            "job_type": job_type,
            "client": C.CLIENTS[job_type],
            "job_description": description,
            "business_unit": f"26{number}0",
            "status": "Active",
        })
    return rows


def catalog() -> dict[str, tuple[str, str]]:
    """Every valid cost code across all pools: code -> (description, unit_of_measure)."""
    cat = dict(C.COMMON_POOL)
    for pool in C.TYPE_POOLS.values():
        cat.update(pool)
    return dict(sorted(cat.items()))


def job_cost_codes(job_type: str) -> list[str]:
    """Codes assigned to a job: its whole type pool plus 0200 and 9000, sorted."""
    return sorted([*C.TYPE_POOLS[job_type], *C.ASSIGNED_COMMON_CODES])


def build_cost_codes(jobs: list[dict]) -> list[dict]:
    cat = catalog()
    rows = []
    for job in jobs:
        for code in job_cost_codes(job["job_type"]):
            description, uom = cat[code]
            rows.append({
                "job_code": job["job_code"],
                "cost_code": code,
                "description": description,
                "unit_of_measure": uom,
            })
    return rows
