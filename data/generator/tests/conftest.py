import subprocess
import sys
from pathlib import Path

import pytest

GENERATOR_DIR = Path(__file__).resolve().parents[1]
GENERATE = GENERATOR_DIR / "generate.py"
sys.path.insert(0, str(GENERATOR_DIR))

SPEC_ARGS = ["--seed", "42", "--start-date", "2026-11-02", "--workdays", "10"]


def run_generator(out: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GENERATE), *args, "--out", str(out)],
        capture_output=True, text=True,
    )


@pytest.fixture(scope="session")
def output_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("run1") / "output"
    result = run_generator(out, *SPEC_ARGS)
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture(scope="session")
def manifest_doc(output_dir):
    import json
    with open(output_dir / "manifest" / "manifest.json", encoding="utf-8") as f:
        return json.load(f)
