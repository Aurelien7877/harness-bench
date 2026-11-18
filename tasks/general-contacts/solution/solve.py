from pathlib import Path
import subprocess
Path('analyze.py').write_text("import json, sys\nfrom pathlib import Path\nitems=[e.strip().lower() for e in json.loads(Path(sys.argv[1]).read_text())]\nPath(sys.argv[2]).write_text(json.dumps({'unique':len(set(items)),'duplicates':len(items)-len(set(items))}))\n")
subprocess.run(['python3','analyze.py','contacts.json','answer.json'],check=True)
