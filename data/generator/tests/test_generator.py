import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal

import config as C
import manifest
from conftest import SPEC_ARGS, run_generator


def _hashes(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_file_set(output_dir):
    assert len(list((output_dir / "timecards").glob("timecards_*.json"))) == 10
    for name in ["employees.csv", "jobs.csv", "cost_codes.csv"]:
        assert (output_dir / "master" / name).is_file()
    assert (output_dir / "manifest" / "manifest.json").is_file()


def test_determinism(output_dir, tmp_path):
    out2 = tmp_path / "run2"
    result = run_generator(out2, *SPEC_ARGS)
    assert result.returncode == 0, result.stderr
    assert _hashes(output_dir) == _hashes(out2)


def test_ssn(output_dir):
    with open(output_dir / "master" / "employees.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == C.EMPLOYEE_COUNT
    assert all(re.fullmatch(r"9\d{2}-\d{2}-\d{4}", r["ssn"]) for r in rows)


TOP_KEYS = {"timecardId": str, "revision": int, "jobCode": str, "foremanId": str,
            "date": str, "status": str, "lastModified": str, "employees": list}
CC_KEYS = ["costCode", "regularHours", "overtimeHours", "doubleTimeHours"]


def test_schema(output_dir):
    for path in sorted((output_dir / "timecards").glob("*.json")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(raw)
            assert list(rec) == list(TOP_KEYS)
            for key, typ in TOP_KEYS.items():
                assert type(rec[key]) is typ, (path.name, key)
            for emp in rec["employees"]:
                assert list(emp) == ["employeeId", "costCodes"]
                assert isinstance(emp["employeeId"], str)
                for cc in emp["costCodes"]:
                    assert list(cc) == CC_KEYS
                    assert isinstance(cc["costCode"], str)
                    for k in CC_KEYS[1:]:
                        assert isinstance(cc[k], float), (path.name, k)


def test_identity(manifest_doc):
    e = manifest_doc["expected"]
    assert e["bronze_lines"] == (
        e["exact_duplicate_lines"] + e["superseded_lines"] + e["valid_lines"] + e["quarantine_lines"]
    )


def test_reason_sum(manifest_doc):
    e = manifest_doc["expected"]
    assert sum(e["quarantine_lines_by_reason"].values()) == e["quarantine_lines"]


def test_injection_counts(manifest_doc):
    counts = Counter(i["defect"] for i in manifest_doc["injections"])
    assert dict(counts) == C.DEFECT_PLAN


def test_baseline_sanity(output_dir):
    day = defaultdict(Decimal)
    for ln in manifest.classify(output_dir):
        if ln["dedup_status"] == "CURRENT" and not ln["dq_reasons"]:
            day[(ln["employee_id"], ln["work_date"])] += ln["hours"]
    assert day and max(day.values()) <= Decimal("10.0")


def test_start_date_not_monday(tmp_path):
    result = run_generator(tmp_path / "out", "--seed", "42", "--start-date", "2026-11-03", "--workdays", "10")
    assert result.returncode != 0


def test_line_endings(output_dir):
    for p in output_dir.rglob("*"):
        if p.is_file():
            assert b"\r" not in p.read_bytes(), p
