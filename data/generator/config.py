"""All counts, seeds, and defect plan constants for the synthetic data generator (SPEC-01)."""

DEFAULT_SEED = 42
DEFAULT_START_DATE = "2026-11-02"  # must be a Monday
DEFAULT_WORKDAYS = 10

# ---- Employees (spec 5.1) ----
EMPLOYEE_COUNT = 80
EMPLOYEE_ID_START = 1001       # E1001 ... E1080
ADDRESS_NUMBER_START = 10001   # 10001 ... 10080 (JDE AN8 stand-in)
FOREMAN_COUNT = 12             # E1001-E1012, one per job
NON_FOREMAN_CRAFTS = ["Equipment Operator", "Pipefitter-Welder", "Cable Splicer", "Laborer", "Teamster"]
UNION_LOCALS = [f"Local {n}" for n in range(101, 106)]
PAY_RATE_RANGES = {            # illustrative only
    "Foreman": (62, 72),
    "Cable Splicer": (58, 66),
    "Pipefitter-Welder": (54, 62),
    "Equipment Operator": (52, 60),
    "Teamster": (42, 48),
    "Laborer": (36, 44),
}
HIRE_DATE_MIN = "2010-01-01"
HIRE_DATE_MAX = "2026-06-30"

# ---- Jobs (spec 5.2) ----
GAS, ELECTRIC, AIRPORT, TELECOM = "Gas Distribution", "Electric Underground", "Airport Fueling", "Telecom"
CLIENTS = {
    GAS: "Ridgeline Gas & Electric",
    ELECTRIC: "Ridgeline Gas & Electric",
    AIRPORT: "Valley Regional Airport",
    TELECOM: "Harborview Fiber",
}
# (job_code, job_type, job_description). All invented.
JOBS = [
    ("26-1001", GAS, "Elm St 4in PE Main Replacement"),
    ("26-1002", GAS, "Oak Ave Gas Service Renewals"),
    ("26-1003", GAS, "Birch Ln 2in PE Main Extension"),
    ("26-1004", GAS, "Willow Ct Steel Main Abandonment"),
    ("26-1005", GAS, "Maple Dr Service Line Tie-Ins"),
    ("26-1006", ELECTRIC, "Cedar Blvd Underground Conversion"),
    ("26-1007", ELECTRIC, "Aspen Way Conduit and Vault Install"),
    ("26-1008", ELECTRIC, "Juniper Rd Feeder Cable Replacement"),
    ("26-1009", ELECTRIC, "Sycamore St Duct Bank Extension"),
    ("26-1010", AIRPORT, "Terminal B Fuel Hydrant Extension"),
    ("26-1011", TELECOM, "Mill Rd Fiber Backbone"),
    ("26-1012", TELECOM, "Poplar Ave Micro-Trench Fiber Laterals"),
]

# ---- Cost codes (spec 5.3): code -> (description, unit_of_measure) ----
COMMON_POOL = {
    "0100": ("Mobilization", "LS"),
    "0200": ("Traffic Control", "DAY"),
    "0300": ("USA Locate & Pothole", "EA"),
    "9000": ("Restoration & Cleanup", "LS"),
}
TYPE_POOLS = {
    GAS: {
        "1100": ("Trenching", "LF"),
        "1200": ("Directional Bore", "LF"),
        "1300": ("PE Main Install", "LF"),
        "1400": ("Service Renewal", "EA"),
        "1500": ("Tie-In & Pressure Test", "EA"),
        "1600": ("Main Abandonment", "LF"),
    },
    ELECTRIC: {
        "2100": ("Trenching", "LF"),
        "2200": ("Conduit Install", "LF"),
        "2300": ("Vault & Splice Box Set", "EA"),
        "2400": ("Cable Pull", "LF"),
        "2500": ("Paving Restoration", "TN"),
    },
    AIRPORT: {
        "3100": ("Excavation", "CY"),
        "3200": ("Fuel Pipe Weld", "LF"),
        "3300": ("Hydrant Pit Install", "EA"),
        "3400": ("Hydrostatic Test", "EA"),
    },
    TELECOM: {
        "4100": ("Micro-Trench", "LF"),
        "4200": ("Conduit Bore", "LF"),
        "4300": ("Handhole Set", "EA"),
        "4400": ("Fiber Splice", "EA"),
    },
}
ASSIGNED_COMMON_CODES = ["0200", "9000"]  # every job gets these plus its whole type pool

# ---- Timecard baseline (spec 5.4) ----
CREW_SIZE_MIN, CREW_SIZE_MAX = 4, 7     # non-foreman employees per crew
COST_CODES_PER_EMPLOYEE = (1, 3)
REGULAR_HOURS_PER_DAY = 8.0
MAX_OVERTIME_PER_DAY = 2.0
HOURS_INCREMENT = 0.5
LAST_MODIFIED_TIME = "17:30:00Z"

# ---- Defect plan (spec 6.2): defect -> units injected ----
DEFECT_PLAN = {
    "EXACT_DUPLICATE": 3,
    "SUPERSEDED": 4,
    "MISSING_JOB": 2,
    "UNKNOWN_JOB": 1,
    "UNKNOWN_EMPLOYEE": 3,
    "INVALID_COST_CODE": 3,
    "NEGATIVE_HOURS": 2,
    "OVER_24_HOURS": 2,
    "NOT_APPROVED": 3,
}
UNKNOWN_JOB_CODE = "99-9999"
UNKNOWN_EMPLOYEE_IDS = ["E9001", "E9002", "E9003"]
UNKNOWN_EMPLOYEE_REG_HOURS = 8.0
NEGATIVE_REG_HOURS = -2.0
SUPERSEDED_MOVE_HOURS = 1.0
SUPERSEDED_MIN_SOURCE_REG = 1.5
OVER_24_REG_HOURS = 14.0
OVER_24_OT_HOURS = 4.0
NOT_APPROVED_STATUS = "Pending"

DQ_REASONS = [
    "MISSING_JOB", "UNKNOWN_JOB", "UNKNOWN_EMPLOYEE", "INVALID_COST_CODE",
    "NEGATIVE_HOURS", "OVER_24_HOURS", "NOT_APPROVED",
]
LINE_DEFINITION = "timecard record x employee x cost code x pay type, hours != 0"
