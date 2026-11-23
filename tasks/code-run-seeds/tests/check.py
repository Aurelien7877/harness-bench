import json, math
from pathlib import Path
expected = {'seed_3': 785308, 'seed_7': 784104, 'seed_11': 784851}
checks, errors = {}, {}
try:
    answer = json.loads(Path("answer.json").read_text())
    checks["schema"] = isinstance(answer, dict) and set(answer) == set(expected)
    for key, value in expected.items():
        got = answer.get(key) if isinstance(answer, dict) else None
        checks[key] = isinstance(got, (int, float)) and not isinstance(got, bool) and got == value
except Exception as error:
    checks["answer_readable"] = False
    errors["answer"] = type(error).__name__ + ": " + str(error)
target = Path("/logs/verifier") if Path("/logs/verifier").is_dir() else Path(".")
(target / "criteria.json").write_text(json.dumps({"checks": checks, "errors": errors}, indent=2))
assert all(checks.values()), json.dumps({"checks": checks, "errors": errors})
