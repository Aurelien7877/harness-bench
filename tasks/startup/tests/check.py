import json, subprocess, tempfile
from pathlib import Path
PUBLIC = '[2, 3, 5]'
HIDDEN = '[-1, 0, 4, 4]'
def evaluate(payload):
    with tempfile.TemporaryDirectory(dir='.') as tmp:
        source = Path(tmp)/'input'
        output = Path(tmp)/'output.json'
        source.write_text(payload)
        subprocess.run(['python3', 'analyze.py', str(source), str(output)], check=True, timeout=10)
        return json.loads(output.read_text())
assert evaluate(PUBLIC)=={'count':3,'sum':10}
assert evaluate(HIDDEN)=={'count':4,'sum':7}
