from pathlib import Path
import subprocess
Path('analyze.py').write_text("import csv, json, sys\nfrom pathlib import Path\nrows=list(csv.DictReader(open(sys.argv[1])))\ntotals={}\nfor r in rows: totals[r['category']]=totals.get(r['category'],0)+int(r['amount_cents'])\ntop=sorted(totals,key=lambda c:(-totals[c],c))[0] if totals else ''\nPath(sys.argv[2]).write_text(json.dumps({'total_cents':sum(totals.values()),'count':len(rows),'top_category':top}))\n")
subprocess.run(['python3','analyze.py','expenses.csv','answer.json'],check=True)
