import json, subprocess, tempfile
from pathlib import Path
PUBLIC = '[{"relevant": ["d1", "d2"], "a": ["d1", "x", "d2"], "b": ["x", "d1", "y"]}, {"relevant": ["d3"], "a": ["x", "y", "d3"], "b": ["d3", "x", "y"]}, {"relevant": ["d4", "d5"], "a": ["x", "y", "z"], "b": ["d5", "d4", "x"]}]'
HIDDEN = '[{"relevant": ["r"], "a": ["r", "x", "y"], "b": ["x", "y", "z", "r"]}, {"relevant": ["s"], "a": ["x", "s", "y"], "b": ["x", "y", "s"]}]'
def evaluate(payload):
    with tempfile.TemporaryDirectory(dir='.') as tmp:
        source = Path(tmp)/'input'
        output = Path(tmp)/'output.json'
        source.write_text(payload)
        subprocess.run(['python3', 'analyze.py', str(source), str(output)], check=True, timeout=10)
        return json.loads(output.read_text())
assert evaluate(PUBLIC)=={'winner':'b','recall_a':0.666667,'recall_b':0.833333,'mrr_a':0.444444,'mrr_b':0.833333}
assert evaluate(HIDDEN)=={'winner':'a','recall_a':1.0,'recall_b':0.5,'mrr_a':0.75,'mrr_b':0.166667}
