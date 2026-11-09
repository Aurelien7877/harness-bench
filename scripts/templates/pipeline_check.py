"""Independent checks for saved output and each unseen input. Standard library only."""
import json
import math
import subprocess
import tempfile
from pathlib import Path

CASES = __CASES__
GROUPS = __GROUPS__


def compare(actual, wanted):
    if isinstance(wanted, bool):
        return type(actual) is bool and actual == wanted
    if isinstance(wanted, (int, float)):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                and math.isfinite(actual)
                and math.isclose(actual, wanted, rel_tol=0, abs_tol=1e-6))
    if isinstance(wanted, dict):
        return (isinstance(actual, dict) and set(actual) == set(wanted)
                and all(compare(actual[k], value) for k, value in wanted.items()))
    if isinstance(wanted, list):
        return (isinstance(actual, list) and len(actual) == len(wanted)
                and all(compare(a, b) for a, b in zip(actual, wanted)))
    return type(actual) is type(wanted) and actual == wanted


checks = {"script_present": Path("analyze.py").is_file()}
errors = {}


def grade(name, actual, expected):
    checks[name + "_schema"] = isinstance(actual, dict) and set(actual) == set(expected)
    for label, fields in GROUPS.items():
        checks[name + "_" + label] = (isinstance(actual, dict)
                                        and all(compare(actual.get(k), expected[k]) for k in fields))


try:
    grade("saved_public", json.loads(Path("answer.json").read_text()), CASES[0][2])
except Exception as error:
    checks["saved_public_execution"] = False
    errors["saved_public"] = type(error).__name__ + ": " + str(error)

for name, payload, expected in CASES:
    try:
        with tempfile.TemporaryDirectory(dir=".") as directory:
            source = Path(directory) / "input"
            output = Path(directory) / "output.json"
            source.write_text(payload)
            subprocess.run(["python3", "analyze.py", str(source), str(output)], check=True, timeout=5)
            grade(name, json.loads(output.read_text()), expected)
    except Exception as error:
        checks[name + "_execution"] = False
        errors[name] = type(error).__name__ + ": " + str(error)

diagnostics = {"checks": checks, "errors": errors}
target = Path("/logs/verifier") if Path("/logs/verifier").is_dir() else Path(".")
(target / "criteria.json").write_text(json.dumps(diagnostics, indent=2))
assert all(checks.values()), json.dumps(diagnostics)
