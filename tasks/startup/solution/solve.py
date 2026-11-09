from pathlib import Path
import subprocess
Path('analyze.py').write_text("import json, sys\nfrom pathlib import Path\nnumbers=json.loads(Path(sys.argv[1]).read_text())\nPath(sys.argv[2]).write_text(json.dumps({'count':len(numbers),'sum':sum(numbers)}))\n")
subprocess.run(['python3','analyze.py','numbers.json','answer.json'],check=True)
