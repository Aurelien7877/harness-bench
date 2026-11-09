"""Create a small, versioned Harbor task pack. No model or network calls."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def task(name, category, instruction, files, solution, check, provenance):
    target = TASKS / name
    write(target / "instruction.md", instruction + "\nWork in /workspace. Do not install packages or use the network.\n")
    write(target / "task.toml", f'''schema_version = "1.4"
[metadata]
category = "{category}"
author_name = "Personal harness benchmark"
difficulty = "easy"
source = "{provenance}"
[agent]
timeout_sec = 180
[verifier]
timeout_sec = 30
[environment]
build_timeout_sec = 300
cpus = 2
memory_mb = 2048
workdir = "/workspace"
''')
    write(target / "environment" / "Dockerfile", "FROM harness-bench-base:1\nWORKDIR /workspace\nCOPY inputs/ /workspace/\n")
    for filename, content in files.items():
        write(target / "environment" / "inputs" / filename, content)
    write(target / "solution" / "solve.sh", "#!/bin/bash\nset -eu\ncd /workspace\npython3 /solution/solve.py\n")
    write(target / "solution" / "solve.py", solution)
    write(target / "tests" / "check.py", check)
    write(target / "tests" / "test.sh", '''#!/bin/bash
set -u
mkdir -p /logs/verifier
cd /workspace
if timeout 20 python3 /tests/check.py; then
    printf '1' > /logs/verifier/reward.txt
else
    printf '0' > /logs/verifier/reward.txt
fi
''')


def json_task(name, category, prompt, files, expected):
    prompt += "\nWrite answer.json with these fields and types:\n" + json.dumps({k: type(v).__name__ for k, v in expected.items()})
    check = '''import json, math
from pathlib import Path
answer = json.loads(Path('answer.json').read_text())
expected = EXPECTED
def compare(actual, wanted):
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, wanted, rel_tol=1e-6, abs_tol=1e-6)
    if isinstance(wanted, dict):
        return isinstance(actual, dict) and set(actual) == set(wanted) and all(compare(actual[k],v) for k,v in wanted.items())
    if isinstance(wanted, list):
        return isinstance(actual,list) and len(actual)==len(wanted) and all(compare(a,b) for a,b in zip(actual,wanted))
    return type(actual) is type(wanted) and actual == wanted
assert compare(answer, expected), f'Unexpected answer: {answer!r}'
'''.replace("EXPECTED", repr(expected))
    solution = "from pathlib import Path\nPath('answer.json').write_text(" + repr(json.dumps(expected)) + ")\n"
    task(name, category, prompt, files, solution, check, "personal-v1; synthetic data; not an official benchmark score")


def pipeline_task(name, category, prompt, filename, initial, hidden, program, check_body):
    """Test a reusable program on public and held-out input, not a memorized answer."""
    check = '''import json, subprocess, tempfile
from pathlib import Path
PUBLIC = PUBLIC_VALUE
HIDDEN = HIDDEN_VALUE
def evaluate(payload):
    with tempfile.TemporaryDirectory(dir='.') as tmp:
        source = Path(tmp)/'input'
        output = Path(tmp)/'output.json'
        source.write_text(payload)
        subprocess.run(['python3', 'analyze.py', str(source), str(output)], check=True, timeout=10)
        return json.loads(output.read_text())
'''.replace('PUBLIC_VALUE', repr(initial)).replace('HIDDEN_VALUE', repr(hidden)) + check_body
    prompt += f"\nWrite analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on {filename} and save answer.json. The verifier will also run your program on another input with the same schema."
    solution = "from pathlib import Path\nimport subprocess\nPath('analyze.py').write_text(" + repr(program) + ")\nsubprocess.run(['python3','analyze.py'," + repr(filename) + ",'answer.json'],check=True)\n"
    task(name, category, prompt, {filename: initial}, solution, check, "personal-v1; synthetic data; held-out input")


def main():
    archive = ROOT / "vendor/humaneval/HumanEval.jsonl.gz"
    rows = [json.loads(line) for line in gzip.decompress(archive.read_bytes()).decode().splitlines()]
    manifest = {"source": "https://github.com/openai/human-eval", "downloaded": "2026-11-04", "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "ids": ["HumanEval/0", "HumanEval/12"], "license": "MIT", "adaptation": "File-based agent task. Original tests and canonical solution retained. Not an official HumanEval score."}
    write(ROOT / "vendor/humaneval/provenance.json", json.dumps(manifest, indent=2) + "\n")
    for index in [0, 12]:
        row = next(r for r in rows if r['task_id'] == f'HumanEval/{index}')
        starter = row['prompt'] + "    raise NotImplementedError\n"
        complete = row['prompt'] + row['canonical_solution']
        check = "import sys\nsys.path.insert(0, '/workspace')\nfrom candidate import " + row['entry_point'] + "\n" + row['test'] + "\ncheck(" + row['entry_point'] + ")\n"
        task(f"humaneval-{index}", "coding", "Complete candidate.py according to its docstring. Preserve the function signature.", {"candidate.py": starter}, "from pathlib import Path\nPath('candidate.py').write_text(" + repr(complete) + ")\n", check, f"openai/human-eval HumanEval/{index}; MIT")

    json_task("ds-aggregation", "data-science", "Clean sales.csv. Keep the first occurrence of each id, exclude cancelled rows and rows with missing amount. Do not drop valid zeros. Sum signed amounts by region. Report excluded_rows, net_total and by_region.", {"sales.csv": "id,region,amount,status\na,EU,100,paid\nb,US,50,paid\na,EU,100,paid\nc,EU,-20,refunded\nd,US,,paid\ne,EU,90,cancelled\nf,US,0,paid\ng,EU,30,paid\n"}, {"excluded_rows": 3, "net_total": 160, "by_region": {"EU": 110, "US": 50}})

    json_task("ds-retrieval", "data-science", "Evaluate two retrievers on rankings.json. Binary relevance. Use the first 3 results only; each result list has distinct IDs. Compute mean recall@3 and mean reciprocal rank@3 across all queries. Choose the higher recall system, breaking ties by MRR. Round metrics to 6 decimals. Include winner, recall_a, recall_b, mrr_a, mrr_b.", {"rankings.json": json.dumps([{"relevant": ["d1", "d2"], "a": ["d1","x","d2"], "b": ["x","d1","y"]}, {"relevant": ["d3"], "a": ["x","y","d3"], "b": ["d3","x","y"]}, {"relevant": ["d4","d5"], "a": ["x","y","z"], "b": ["d5","d4","x"]}])}, {"winner": "b", "recall_a": 0.666667, "recall_b": 0.833333, "mrr_a": 0.444444, "mrr_b": 0.833333})

    # Upgrade two fixtures to actual analysis programs with held-out inputs.
    sales = 'id,region,amount,status\n' + ''.join(f'{i},EU,{i%11},paid\n' for i in range(1200))
    sales += '0,EU,9000,paid\nr,EU,-20,refunded\nx,US,,paid\nc,EU,50,cancelled\nz,US,0,paid\n'
    sales_hidden = 'id,region,amount,status\na,US,10.5,paid\nb,EU,-2,refunded\na,US,500,paid\nc,US,,paid\nd,EU,99,cancelled\ne,EU,0,paid\n'
    aggregation = '''import csv, json, sys
from decimal import Decimal
seen=set(); totals={}; excluded=0
with open(sys.argv[1]) as f:
    for row in csv.DictReader(f):
        if row['id'] in seen:
            excluded+=1; continue
        seen.add(row['id'])
        if row['status']=='cancelled' or not row['amount'].strip():
            excluded+=1; continue
        region=row['region']
        totals[region]=totals.get(region,Decimal(0))+Decimal(row['amount'])
result={'excluded_rows':excluded,'net_total':float(sum(totals.values())), 'by_region':{k:float(v) for k,v in totals.items()}}
with open(sys.argv[2],'w') as f: json.dump(result,f)
'''
    public_total = sum(i%11 for i in range(1200))-20
    pipeline_task('ds-aggregation','data-science','Clean the CSV: first id wins, then exclude cancelled and missing amounts; include refunds and zeros. Produce excluded_rows, net_total, by_region. Use decimal-safe arithmetic.', 'sales.csv', sales, sales_hidden, aggregation, f"assert evaluate(PUBLIC)=={{'excluded_rows':3,'net_total':{public_total},'by_region':{{'EU':{public_total},'US':0}}}}\nassert evaluate(HIDDEN)=={{'excluded_rows':3,'net_total':8.5,'by_region':{{'US':10.5,'EU':-2}}}}\n")
    rankings = (TASKS/'ds-retrieval/environment/inputs/rankings.json').read_text()
    retrieval = '''import json, sys
with open(sys.argv[1]) as f: queries=json.load(f)
out={}
for system in ('a','b'):
    recalls=[]; reciprocals=[]
    for query in queries:
        relevant=set(query['relevant']); ranked=query[system][:3]
        recalls.append(len(set(ranked)&relevant)/len(relevant))
        reciprocals.append(next((1/(i+1) for i,x in enumerate(ranked) if x in relevant),0))
    out['recall_'+system]=round(sum(recalls)/len(queries),6)
    out['mrr_'+system]=round(sum(reciprocals)/len(queries),6)
av=(out['recall_a'],out['mrr_a']); bv=(out['recall_b'],out['mrr_b'])
out['winner']='a' if av>bv else 'b' if bv>av else 'tie'
with open(sys.argv[2],'w') as f: json.dump(out,f)
'''
    hidden_rankings = json.dumps([{'relevant':['r'],'a':['r','x','y'],'b':['x','y','z','r']},{'relevant':['s'],'a':['x','s','y'],'b':['x','y','s']}])
    pipeline_task('ds-retrieval','data-science','Evaluate rankings with non-empty binary relevance and distinct result IDs. Compute mean recall@3 and mean reciprocal rank@3. Ignore results after rank 3. Round to 6 decimals. Output recall_a, recall_b, mrr_a, mrr_b, winner (a/b/tie), choosing recall then MRR.', 'rankings.json', rankings, hidden_rankings, retrieval, "assert evaluate(PUBLIC)=={'winner':'b','recall_a':0.666667,'recall_b':0.833333,'mrr_a':0.444444,'mrr_b':0.833333}\nassert evaluate(HIDDEN)=={'winner':'a','recall_a':1.0,'recall_b':0.5,'mrr_a':0.75,'mrr_b':0.166667}\n")

    json_task("ds-leakage", "data-science", "Audit experiment.json before approving a churn model. The prediction timestamp is month start and the evaluation should simulate future unseen customers. Return leakage_columns (alphabetically sorted), split_policy chosen from random/time_group, fit_preprocessor_on chosen from all/train, reported_accuracy_trustworthy boolean. No model training is required.", {"experiment.json": json.dumps({"features": {"age": "available at month start", "tenure_months": "available at month start", "cancellation_reason": "recorded after customer cancels", "days_until_churn": "computed from future label"}, "rows": "multiple monthly observations per customer", "split": "random rows", "scaler_fit": "all rows", "reported_accuracy": 0.99})}, {"leakage_columns": ["cancellation_reason", "days_until_churn"], "split_policy": "time_group", "fit_preprocessor_on": "train", "reported_accuracy_trustworthy": False})

    sources = {"S1.txt": "S1 | Official specification | 2026-01-01\nAster supports 64 GB RAM; price 800 EUR excluding delivery.\n", "S2.txt": "S2 | Official correction | 2026-10-01\nSupersedes S1. Aster maximum RAM is 32 GB. Price remains 800 EUR.\n", "S3.txt": "S3 | Official specification | 2026-09-01\nBoreal supports 64 GB RAM; price 900 EUR including delivery.\n", "S4.txt": "S4 | Anonymous forum | 2026-10-02\nI think Aster supports 128 GB. No measurements or link.\n"}
    json_task("research-evidence", "research", "Use the four supplied fictional source documents. Select the product meeting at least 64 GB RAM and a delivered budget of 950 EUR, using authoritative current evidence. Return selected, decisive_sources (sorted source IDs), aster_ram_gb, aster_delivery_cost_known. This is evidence synthesis, not live web research.", sources, {"selected": "Boreal", "decisive_sources": ["S2", "S3"], "aster_ram_gb": 32, "aster_delivery_cost_known": False})

    json_task("general-reconciliation", "general", "Apply payments to invoices oldest first, within each customer only. Deduplicate payments by payment_id, keeping first. Amounts are integer cents. Report remaining invoice balances as balances, unapplied_credit by customer, duplicate_payments count. Read ledger.json.", {"ledger.json": json.dumps({"invoices": [{"id":"i1","customer":"A","date":"2026-01-01","amount":10000},{"id":"i2","customer":"A","date":"2026-02-01","amount":5000},{"id":"i3","customer":"B","date":"2026-01-01","amount":4000}], "payments": [{"payment_id":"p1","customer":"A","amount":12000},{"payment_id":"p1","customer":"A","amount":12000},{"payment_id":"p2","customer":"B","amount":6000}]})}, {"balances": {"i1": 0,"i2": 3000,"i3": 0}, "unapplied_credit": {"A":0,"B":2000}, "duplicate_payments": 1})

    history = "2026-01-01: Budget 1000 EUR. Preferred region EU.\n2026-02-01: Budget revised to 700 EUR; this replaces the old budget.\n"
    history += "".join(f"Log {i}: background batch completed; no preference changes.\n" for i in range(200))
    history += "2026-10-01: Preferred region now US. Budget unchanged.\n2026-11-01: The earlier budget revision remains valid. Do not infer a new budget.\n"
    json_task("context-revisions", "context", "Recover the current preferences from history.txt, using explicit revisions. Return budget_eur, region, budget_source_date. This tests file-based context retrieval, not cross-session memory or compaction.", {"history.txt": history}, {"budget_eur": 700, "region": "US", "budget_source_date": "2026-02-01"})
    print(f"Prepared {len(list(TASKS.iterdir()))} Harbor tasks")


if __name__ == '__main__':
    main()
