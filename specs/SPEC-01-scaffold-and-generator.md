# SPEC-01 — Repo Scaffold + Synthetic Data Generator

**Repo:** `david-edmister-agent/applications-engineer-lab`
**Branch:** `feature/01-data-generator`
**Mode:** Loop until every acceptance check in §8 passes. Stop conditions in §9.

---

## 1. Goal

Produce deterministic, synthetic HeavyJob-style field timecard data (plus employee, job, and cost-code master data) that the Databricks notebooks in `01-databricks/notebooks/` ingest. The generator also writes a `manifest.json` of expected line counts. Databricks reconciliation (`04_reconciliation`) asserts against this manifest.

The data contains **seeded defects** so that silver validation and quarantine logic have something real to catch.

**Business scenario (fictional):** A Northern California utility contractor runs field crews on gas distribution, electric underground, airport fueling, and telecom work for its utility, airport, and fiber clients. Foremen log daily crew time in HCSS HeavyJob against the job's cost codes. Approved time flows through staging into JD Edwards payroll. Every company, client, project, and person in the data is invented.

## 2. Scope

**In scope**
- Repo scaffold (folders, `.gitignore`, `requirements.txt`, `README.md`)
- `data/generator/` — the generator, the manifest builder, and the tests
- Generated output committed to `data/output/`

**Out of scope — do not touch**
- `01-databricks/notebooks/*.py`. These are already written. Read `00_common.py` for the line definition, but do not edit it.
- Power Automate, Databricks Jobs, and upload scripts
- Any real company data, names, endpoints, or connector names

## 3. Repo layout

```
applications-engineer-lab/
├── README.md
├── requirements.txt            # faker (exact pin), pytest (exact pin)
├── .gitignore                  # .venv/, __pycache__/, .pytest_cache/  (do NOT ignore data/output/)
├── specs/
│   └── SPEC-01-scaffold-and-generator.md
├── data/
│   ├── generator/
│   │   ├── generate.py         # CLI entry point
│   │   ├── config.py           # all counts, seeds, defect plan constants
│   │   ├── master.py           # employees, jobs, cost codes
│   │   ├── timecards.py        # baseline timecards + defect injection
│   │   ├── manifest.py         # independent re-read + count (see §6)
│   │   └── tests/
│   │       ├── conftest.py
│   │       └── test_generator.py
│   └── output/                 # generated, committed
│       ├── master/employees.csv
│       ├── master/jobs.csv
│       ├── master/cost_codes.csv
│       ├── timecards/timecards_YYYYMMDD.json   # one per workday, NDJSON
│       └── manifest/manifest.json
├── 01-databricks/notebooks/    # exists — read-only for this spec
└── 02-power-automate/          # empty placeholder with .gitkeep
```

## 4. CLI

```
python data/generator/generate.py --seed 42 --start-date 2026-11-02 --workdays 10 --out data/output
```

- `--start-date` must be a Monday. Exit non-zero otherwise.
- Workdays are Monday–Friday only. Ten workdays span two pay periods, ending Sun 2026-11-08 and Sun 2026-11-15.
- The output directory is wiped and rewritten on every run.
- Use Python 3.11+ and the standard library plus `faker`. Call `Faker.seed(seed)` and `random.Random(seed)`. Use no global `random`.
- Write every generated file (CSV, NDJSON, JSON) with `newline="\n"` and `encoding="utf-8"`. For CSV, also pass `lineterminator="\n"` to `csv.writer` (its default is `\r\n`). The repo's `.gitattributes` sets `eol=lf`, so output must be byte-identical on Windows and Linux and match what git stores.

## 5. Data contracts

### 5.1 `master/employees.csv` (80 rows)

| column | rule |
|---|---|
| employee_id | `E1001` … `E1080` |
| address_number | int, `10001` … `10080` (JDE AN8 stand-in) |
| first_name, last_name | Faker |
| ssn | `9XX-XX-XXXX`. The area number must be **900–999**, which is never issued, so these values are guaranteed fake. |
| craft | Foreman (12), Equipment Operator, Pipefitter-Welder, Cable Splicer, Laborer, Teamster |
| union_local | `Local 101` … `Local 105` (fictional) |
| pay_rate | 2 decimals, illustrative only. Foreman 62–72, Cable Splicer 58–66, Pipefitter-Welder 54–62, Equipment Operator 52–60, Teamster 42–48, Laborer 36–44 |
| hire_date | ISO date, 2010-01-01 … 2026-06-30 |
| status | `A` |

### 5.2 `master/jobs.csv` (12 rows)

| column | rule |
|---|---|
| job_code | `26-1001` … `26-1012` |
| job_type | `26-1001`–`26-1005` Gas Distribution · `26-1006`–`26-1009` Electric Underground · `26-1010` Airport Fueling · `26-1011`–`26-1012` Telecom |
| client | Invented: Gas Distribution and Electric Underground → `Ridgeline Gas & Electric`; Airport Fueling → `Valley Regional Airport`; Telecom → `Harborview Fiber` |
| job_description | Invented, matching job_type, e.g. "Elm St 4in PE Main Replacement", "Oak Ave Gas Service Renewals", "Cedar Blvd Underground Conversion", "Terminal B Fuel Hydrant Extension", "Mill Rd Fiber Backbone". No real streets-plus-city combinations or real projects. |
| business_unit | 7-digit string: `26` + 4-digit job number + `0`, e.g. `2610010` |
| status | `Active` |

Column order: job_code, job_type, client, job_description, business_unit, status.

### 5.3 `master/cost_codes.csv`

Catalog (cost_code, description, unit_of_measure). `cost_code` is a 4-character **string**.

| Pool | Codes |
|---|---|
| Common | `0100 Mobilization LS`, `0200 Traffic Control DAY`, `0300 USA Locate & Pothole EA`, `9000 Restoration & Cleanup LS` |
| Gas Distribution | `1100 Trenching LF`, `1200 Directional Bore LF`, `1300 PE Main Install LF`, `1400 Service Renewal EA`, `1500 Tie-In & Pressure Test EA`, `1600 Main Abandonment LF` |
| Electric Underground | `2100 Trenching LF`, `2200 Conduit Install LF`, `2300 Vault & Splice Box Set EA`, `2400 Cable Pull LF`, `2500 Paving Restoration TN` |
| Airport Fueling | `3100 Excavation CY`, `3200 Fuel Pipe Weld LF`, `3300 Hydrant Pit Install EA`, `3400 Hydrostatic Test EA` |
| Telecom | `4100 Micro-Trench LF`, `4200 Conduit Bore LF`, `4300 Handhole Set EA`, `4400 Fiber Splice EA` |

Each job is assigned **every code in its job_type pool plus `0200` and `9000`** (Gas 8, Electric 7, Airport 6, Telecom 6). This is deterministic, with no random subset. Write one row per (job_code, cost_code), with columns job_code, cost_code, description, unit_of_measure. Codes `0100`, `0300`, and other types' pools are valid catalog codes that are *not* assigned to a given job, which gives INVALID_COST_CODE realistic targets.

### 5.4 `timecards/timecards_YYYYMMDD.json` — NDJSON, one timecard per line

```json
{"timecardId":"TC-000001","revision":1,"jobCode":"26-1001","foremanId":"E1001",
 "date":"2026-11-02","status":"Approved","lastModified":"2026-11-02T17:30:00Z",
 "employees":[{"employeeId":"E1013","costCodes":[
   {"costCode":"1100","regularHours":6.0,"overtimeHours":1.0,"doubleTimeHours":0.0},
   {"costCode":"1300","regularHours":2.0,"overtimeHours":0.0,"doubleTimeHours":0.0}]}]}
```

The baseline (before defects) follows these rules:
- Each job has a fixed crew for the whole period: 1 foreman plus 4–7 non-foreman employees. No employee is on two crews.
- Each workday has exactly one timecard per job. `timecardId` values are sequential across the run.
- The foreman appears on their own timecard as an employee.
- Each employee charges 1–3 cost codes valid for that job. Regular hours sum to exactly 8.0 per employee per day, overtime totals 0–2.0, and double time is 0.0. All hours are in 0.5 increments.
- Status is `Approved`. `lastModified` is the work date at 17:30Z.
- Hours are JSON floats. Key order matches the example above.

## 6. Defects, manifest, and the line definition

### 6.1 Line definition (must match `01-databricks/notebooks/00_common.py`)

A **line** is one (timecard record × employee × cost code × pay type) where hours ≠ 0. The pay types are REG = regularHours, OT = overtimeHours, and DT = doubleTimeHours.

### 6.2 Defect plan (exact counts, in `config.py`)

| defect | units injected | how |
|---|---|---|
| EXACT_DUPLICATE | 3 timecards | Re-emit the identical record (same id and revision) in the **next** workday's file |
| SUPERSEDED | 4 timecards | Emit revision 2 in a later workday's file. In it, pick one employee who has ≥2 cost codes. Move 1.0 REG from one entry (which must have ≥1.5 REG) to another, so the employee's daily total is unchanged. Revision 1 is then superseded. |
| MISSING_JOB | 2 timecards | `jobCode` = `""` |
| UNKNOWN_JOB | 1 timecard | `jobCode` = `"99-9999"` |
| UNKNOWN_EMPLOYEE | 3 employee entries | Add an employee entry with id `E9001`–`E9003` (not in master), 8.0 REG on one valid cost code |
| INVALID_COST_CODE | 3 cost-code entries | Change an existing entry's costCode to one **not** assigned to that job |
| NEGATIVE_HOURS | 2 cost-code entries | Set regularHours to `-2.0` on an existing entry |
| OVER_24_HOURS | 2 employee-days | Add an existing employee to a **second** job's timecard on the same day with 14.0 REG + 4.0 OT on one valid cost code, so the daily total exceeds 24 |
| NOT_APPROVED | 3 timecards | `status` = `"Pending"` |

**Exclusivity rule (required):** Every line ends up with at most one defect reason. This means:
- Each defect targets a distinct timecard.
- EXACT_DUPLICATE and SUPERSEDED targets are otherwise clean.
- No defect targets the same employee-day as an OVER_24_HOURS injection, except that injection itself.
- After the injection, no other employee-day exceeds 24.

### 6.3 Validation rules the manifest must apply (same order and semantics as silver)

Steps 1 and 2 are dedup; step 3 is validation. Apply them to the parsed files:

1. **EXACT_DUPLICATE:** For records with the same (timecardId, revision), keep the one in the earliest file (ordered by file name). Lines from later copies are exact-duplicate lines.
2. **SUPERSEDED:** Among the surviving records, lines from any revision lower than that timecard's max revision are superseded lines.
3. The remaining lines are CURRENT. Run every check below; a line's reasons are all checks it fails:
   - MISSING_JOB: jobCode blank or null
   - UNKNOWN_JOB: jobCode present but not in jobs.csv
   - UNKNOWN_EMPLOYEE: employeeId not in employees.csv
   - INVALID_COST_CODE: job is known and (jobCode, costCode) is not in cost_codes.csv
   - NEGATIVE_HOURS: hours < 0
   - OVER_24_HOURS: the sum of **positive** hours across all CURRENT lines for (employeeId, date) is > 24
   - NOT_APPROVED: status ≠ `Approved`
4. Lines with zero reasons are valid; all others are quarantined.

### 6.4 `manifest.py` must be independent

It **re-reads the files from disk**. It must not use the in-memory generation plan. It applies §6.3 in pure Python, and `generate.py` then asserts that the manifest's quarantine counts agree with the injection plan before exiting 0.

### 6.5 `manifest/manifest.json`

```json
{
  "seed": 42,
  "line_definition": "timecard record x employee x cost code x pay type, hours != 0",
  "expected": {
    "bronze_lines": 0,
    "exact_duplicate_lines": 0,
    "superseded_lines": 0,
    "valid_lines": 0,
    "quarantine_lines": 0,
    "quarantine_lines_by_reason": {"MISSING_JOB": 0, "UNKNOWN_JOB": 0, "UNKNOWN_EMPLOYEE": 0,
      "INVALID_COST_CODE": 0, "NEGATIVE_HOURS": 0, "OVER_24_HOURS": 0, "NOT_APPROVED": 0},
    "valid_hours": "0.00"
  },
  "injections": [{"defect": "...", "timecardId": "...", "file": "...", "detail": "..."}]
}
```

- `valid_hours` is a string with exactly 2 decimals. Sum it with `decimal.Decimal`.
- Write no timestamps anywhere, so that output is byte-deterministic.
- Use `json.dumps(indent=2, sort_keys=False)` with a trailing newline.

## 7. README.md content

0. Keep the existing first line, "Interesting role at Underground Construction, Inc.", at the top of the file.
1. One-paragraph purpose: a practice lab for an Applications Engineer role (integrations, data validation, payroll staging) at a utility contractor, modeled on the fictional scenario in §1 and built on synthetic data only.
2. **Synthetic-data notice:** All names, jobs, and SSNs are generated. SSNs use the never-issued 900–999 area range. Silver masks SSN to the last 4 digits, and gold carries no SSN.
3. Architecture sketch in text: generator → Volume → bronze → silver (+ quarantine) → gold → JDE timecard staging view → (planned) Power Automate.
4. **Role-mapping table:**

| Lab component | Skill demonstrated | Status |
|---|---|---|
| Auto Loader + COPY INTO bronze | Databricks integrations, data staging, file-based transfers | Built |
| Silver validation + quarantine | Data validation, master data management | Built |
| SSN masking in silver | Ethical handling of payroll / PII | Built |
| MERGE into gold with row hash | Idempotent integrations, SQL | Built |
| `vw_f06116z1_export` | JD Edwards payroll integration | Built |
| `04_reconciliation` + `ops_run_log` | Troubleshooting, root cause analysis | Built |
| Power Automate flows | Build and maintain Power Automate flows | Planned |
| Solution unpacked to Git | Version control, code review | Planned |
| UAT plan | User Acceptance Testing | Planned |

5. **Run it:** the generator command, then the upload click path: Databricks → **Catalog** → `workspace` → `ae_lab` → **Volumes** → `landing` → **Upload to this volume**. Upload into the folders `master/`, `timecards/`, and `manifest/`, then run notebooks `01`–`04` in order.

## 8. Acceptance checks (all must pass)

1. `pip install -r requirements.txt` succeeds in a fresh venv. Faker and pytest are pinned to exact versions.
2. The generator command in §4 exits 0 and produces exactly 10 timecard files plus 3 master CSVs plus the manifest.
3. `pytest -q data/generator/tests` passes with these tests:
   - **determinism:** Two runs with seed 42 into separate temp dirs produce byte-identical files (compare SHA-256 of every file).
   - **ssn:** Every SSN matches `^9\d{2}-\d{2}-\d{4}$`.
   - **schema:** Every NDJSON line parses and has the keys and types in §5.4. `costCode` is a str and hours are numeric.
   - **identity:** `bronze_lines == exact_duplicate_lines + superseded_lines + valid_lines + quarantine_lines`.
   - **reason sum:** The sum of `quarantine_lines_by_reason` equals `quarantine_lines`, which proves no line has more than one reason.
   - **injection counts:** The count of `injections` per defect equals §6.2.
   - **baseline sanity:** For valid lines, every employee-day totals ≤ 10.0 hours.
   - **start date:** A non-Monday `--start-date` exits non-zero.
   - **line endings:** No file under the output directory contains a `\r` byte.
4. `data/output/` is committed and its contents match a fresh run.
5. Nothing in the repo references Wente, `wentevineyards`, `BAROLO`, or any real company, utility, airport, or person. The single exception is the README's first line naming the hiring company. Generated data uses only the invented names in §5.

## 9. Loop instructions and stop conditions

- **Loop:** Implement → run §8 → fix the failing check with the smallest change → rerun. Prefer surgical edits over rewrites.
- **Commit** after each check passes, using conventional messages (`feat(generator): …`, `test(generator): …`).
- **Stop and report** instead of guessing if any of these happen:
  - the exclusivity rule (§6.2) can't be satisfied with the given counts
  - Faker output is not deterministic across two runs with the pinned version
  - a check seems to require editing `01-databricks/notebooks/`
- **Done** means all §8 checks pass, the branch is pushed, and you have reported a summary listing each `expected` value from the manifest.
