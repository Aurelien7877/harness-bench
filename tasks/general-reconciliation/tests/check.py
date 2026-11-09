"""Independent checks for saved output and each unseen input. Standard library only."""
import json
import math
import subprocess
import tempfile
from pathlib import Path

CASES = [('public', '{"invoices": [{"id": "i1", "customer": "A", "date": "2026-01-01", "amount": 10000}, {"id": "i2", "customer": "A", "date": "2026-02-01", "amount": 5000}, {"id": "i3", "customer": "B", "date": "2026-01-01", "amount": 4000}], "payments": [{"payment_id": "p1", "customer": "A", "amount": 12000}, {"payment_id": "p1", "customer": "A", "amount": 12000}, {"payment_id": "p2", "customer": "B", "amount": 6000}]}', {'balances': {'i1': 0, 'i2': 3000, 'i3': 0}, 'unapplied_credit': {'A': 0, 'B': 2000}, 'duplicate_payments': 1}), ('hidden', '{"invoices": [{"id": "late", "customer": "A", "date": "2026-04-01", "amount": 500}, {"id": "early", "customer": "A", "date": "2026-01-01", "amount": 700}, {"id": "unpaid", "customer": "B", "date": "2026-01-01", "amount": 300}], "payments": [{"payment_id": "same", "customer": "A", "amount": 800}, {"payment_id": "same", "customer": "B", "amount": 9999}, {"payment_id": "extra", "customer": "C", "amount": 250}]}', {'balances': {'early': 0, 'late': 400, 'unpaid': 300}, 'unapplied_credit': {'A': 0, 'B': 0, 'C': 250}, 'duplicate_payments': 1}), ('hidden_2', '{"invoices": [{"id": "b", "customer": "A", "date": "2026-01-01", "amount": 200}, {"id": "a", "customer": "A", "date": "2026-01-01", "amount": 100}], "payments": [{"payment_id": "one", "customer": "A", "amount": 150}, {"payment_id": "two", "customer": "B", "amount": 0}]}', {'balances': {'a': 0, 'b': 150}, 'unapplied_credit': {'A': 0, 'B': 0}, 'duplicate_payments': 0})]
GROUPS = {'balances': ['balances'], 'unapplied_credit': ['unapplied_credit'], 'duplicate_payments': ['duplicate_payments']}


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
