"""Grade both inputs and retain separate diagnostic checks."""
import json
import math
import subprocess
import tempfile
from pathlib import Path

PUBLIC = '[{"relevant":["d1","d2"],"a":["d1","x","d2"],"b":["x","d1","y"]},{"relevant":["d3"],"a":["x","y","d3"],"b":["d3","x","y"]},{"relevant":["d4","d5"],"a":["x","y","z"],"b":["d5","d4","x"]}]'
HIDDEN = '[{"relevant":["r"],"a":["r","x","y"],"b":["x","y","z","r"]},{"relevant":["s"],"a":["x","s","y"],"b":["x","y","s"]}]'
EXPECTED = [
    ("public", PUBLIC, {"winner":"b","recall_a":0.666667,"recall_b":0.833333,"mrr_a":0.444444,"mrr_b":0.833333}),
    ("hidden", HIDDEN, {"winner":"a","recall_a":1.0,"recall_b":0.5,"mrr_a":0.75,"mrr_b":0.166667}),
]

checks = {"script_present": Path("analyze.py").is_file()}
errors = {}
for name, payload, expected in EXPECTED:
    try:
        with tempfile.TemporaryDirectory(dir=".") as directory:
            source = Path(directory)/"input"
            output = Path(directory)/"output.json"
            source.write_text(payload)
            subprocess.run(["python3","analyze.py",str(source),str(output)], check=True, timeout=10)
            actual = json.loads(output.read_text())
        def correct(key):
            value = actual.get(key)
            wanted = expected[key]
            if isinstance(wanted, str):
                return value == wanted
            return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and math.isclose(value,wanted,abs_tol=1e-6,rel_tol=0)
        checks[name+"_recall"] = all(correct(k) for k in ("recall_a","recall_b"))
        checks[name+"_mrr"] = all(correct(k) for k in ("mrr_a","mrr_b"))
        checks[name+"_winner"] = correct("winner")
        checks[name+"_schema"] = set(actual) == set(expected)
    except Exception as error:
        checks[name+"_execution"] = False
        errors[name] = type(error).__name__ + ": " + str(error)

diagnostics = {"checks": checks, "errors": errors}
# Write beside this grader for local checks, or into Harbor's verifier logs.
target = Path("/logs/verifier") if Path("/logs/verifier").is_dir() else Path(".")
(target/"criteria.json").write_text(json.dumps(diagnostics,indent=2))
assert all(checks.values()), json.dumps(diagnostics)
