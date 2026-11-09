from pathlib import Path
import subprocess
Path('analyze.py').write_text("import csv, json, sys\nfrom decimal import Decimal\nseen=set(); totals={}; excluded=0\nwith open(sys.argv[1]) as f:\n    for row in csv.DictReader(f):\n        if row['id'] in seen:\n            excluded+=1; continue\n        seen.add(row['id'])\n        if row['status']=='cancelled' or not row['amount'].strip():\n            excluded+=1; continue\n        region=row['region']\n        totals[region]=totals.get(region,Decimal(0))+Decimal(row['amount'])\nresult={'excluded_rows':excluded,'net_total':float(sum(totals.values())), 'by_region':{k:float(v) for k,v in totals.items()}}\nwith open(sys.argv[2],'w') as f: json.dump(result,f)\n")
subprocess.run(['python3','analyze.py','sales.csv','answer.json'],check=True)
