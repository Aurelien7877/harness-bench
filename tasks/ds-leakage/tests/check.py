import json, math
from pathlib import Path
expected = {'leakage_columns': ['cancellation_reason', 'days_until_churn'], 'split_policy': 'time_group', 'fit_preprocessor_on': 'train', 'reported_accuracy_trustworthy': False}
checks = {}
errors = {}
def compare(actual, wanted):
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, wanted, rel_tol=0, abs_tol=1e-6)
    if isinstance(wanted, dict):
        return isinstance(actual, dict) and set(actual) == set(wanted) and all(compare(actual[k],v) for k,v in wanted.items())
    if isinstance(wanted, list):
        return isinstance(actual,list) and len(actual)==len(wanted) and all(compare(a,b) for a,b in zip(actual,wanted))
    return type(actual) is type(wanted) and actual == wanted
try:
    answer = json.loads(Path("answer.json").read_text())
    checks["schema"] = isinstance(answer,dict) and set(answer) == set(expected)
    for key,value in expected.items():
        checks[key] = isinstance(answer,dict) and compare(answer.get(key),value)
except Exception as error:
    checks["answer_readable"] = False
    errors["answer"] = type(error).__name__ + ": " + str(error)
target = Path("/logs/verifier") if Path("/logs/verifier").is_dir() else Path(".")
(target/"criteria.json").write_text(json.dumps({"checks":checks,"errors":errors},indent=2))
assert all(checks.values()), json.dumps({"checks":checks,"errors":errors})
