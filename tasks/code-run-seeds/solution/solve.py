import json, subprocess, sys
answer = {f'seed_{s}': int(subprocess.check_output([sys.executable, 'sim.py', str(s)]).decode().split('=')[1]) for s in (3, 7, 11)}
open('answer.json', 'w').write(json.dumps(answer))
