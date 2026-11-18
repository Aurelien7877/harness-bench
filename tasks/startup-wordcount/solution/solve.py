from pathlib import Path
import subprocess
Path('analyze.py').write_text("import json, sys\nfrom pathlib import Path\ntext=Path(sys.argv[1]).read_text()\nPath(sys.argv[2]).write_text(json.dumps({'words':len(text.split()),'lines':len(text.splitlines())}))\n")
subprocess.run(['python3','analyze.py','text.txt','answer.json'],check=True)
