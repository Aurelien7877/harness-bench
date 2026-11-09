import json, math
from pathlib import Path
answer = json.loads(Path('answer.json').read_text())
expected = {'budget_eur': 700, 'region': 'US', 'budget_source_date': '2026-02-01'}
def compare(actual, wanted):
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, wanted, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(wanted, dict):
        return isinstance(actual, dict) and set(actual) == set(wanted) and all(compare(actual[k],v) for k,v in wanted.items())
    if isinstance(wanted, list):
        return isinstance(actual,list) and len(actual)==len(wanted) and all(compare(a,b) for a,b in zip(actual,wanted))
    return type(actual) is type(wanted) and actual == wanted
assert compare(answer, expected), f'Unexpected answer: {answer!r}'
