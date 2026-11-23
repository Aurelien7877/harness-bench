"""Create a small, versioned Harbor task pack. No model or network calls."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
JSON_TYPES = {int: "number", float: "number", str: "string", bool: "boolean", dict: "object", list: "array"}


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def task(name, category, instruction, files, solution, check, provenance, difficulty="easy"):
    target = TASKS / name
    write(target / "instruction.md", instruction + "\nWork in /workspace. Do not install packages or use the network.\n")
    write(target / "task.toml", f'''schema_version = "1.4"
[metadata]
category = "{category}"
author_name = "Personal harness benchmark"
difficulty = "{difficulty}"
source = "{provenance}"
[agent]
timeout_sec = 600
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
    prompt += "\nWrite answer.json with these fields and types:\n" + json.dumps({k: JSON_TYPES[type(v)] for k, v in expected.items()})
    check = '''import json, math
from pathlib import Path
expected = EXPECTED
checks = {}
errors = {}
def compare(actual, wanted):
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, wanted, rel_tol=0, abs_tol=1e-6)
    if isinstance(wanted, dict):
        return isinstance(actual, dict) and set(actual) == set(wanted) and all(compare(actual[k],v) for k,v in wanted.items())
    if isinstance(wanted, list):
        return isinstance(actual,list) and len(actual)==len(wanted) and all(compare(a,b) for a,b in zip(actual,wanted))
    return type(actual) is type(wanted) and actual == wanted
try:
    answer = json.loads(Path("answer.json").read_text())
    checks["schema"] = isinstance(answer,dict) and set(answer) == set(expected)
    for key,value in expected.items():
        checks[key] = isinstance(answer,dict) and compare(answer.get(key),value)
except Exception as error:
    checks["answer_readable"] = False
    errors["answer"] = type(error).__name__ + ": " + str(error)
target = Path("/logs/verifier") if Path("/logs/verifier").is_dir() else Path(".")
(target/"criteria.json").write_text(json.dumps({"checks":checks,"errors":errors},indent=2))
assert all(checks.values()), json.dumps({"checks":checks,"errors":errors})
'''.replace("EXPECTED", repr(expected))
    solution = "from pathlib import Path\nPath('answer.json').write_text(" + repr(json.dumps(expected)) + ")\n"
    task(name, category, prompt, files, solution, check, "personal-v3; synthetic data; not an official benchmark score")


def pipeline_task(name, category, prompt, filename, initial, hidden, program, expected, groups=None):
    """Require a reusable program, saved public output and independent held-out checks."""
    cases = [("public", initial, expected[0])]
    hidden_inputs = hidden if isinstance(hidden, list) else [hidden]
    cases += [("hidden" if i == 0 else "hidden_" + str(i + 1), payload, wanted)
              for i, (payload, wanted) in enumerate(zip(hidden_inputs, expected[1:]))]
    assert len(hidden_inputs) == len(expected) - 1
    if groups is None:
        groups = {key: [key] for key in expected[0]}
    template = (ROOT / "scripts/templates/pipeline_check.py").read_text()
    check = template.replace("__CASES__", repr(cases)).replace("__GROUPS__", repr(groups))
    prompt += "\nOutput exactly these fields (JSON object order does not matter): " + json.dumps({k: JSON_TYPES[type(v)] for k, v in expected[0].items()})
    prompt += f"\nWrite analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on {filename} and save answer.json. The verifier checks that saved answer and runs your program on public and held-out inputs with the same schema. Use only the supplied input; do not hardcode its answer."
    solution = "from pathlib import Path\nimport subprocess\nPath('analyze.py').write_text(" + repr(program) + ")\nsubprocess.run(['python3','analyze.py'," + repr(filename) + ",'answer.json'],check=True)\n"
    task(name, category, prompt, {filename: initial}, solution, check, "personal-v3; synthetic data; held-out inputs")


def main():
    archive = ROOT / "vendor/humaneval/HumanEval.jsonl.gz"
    rows = [json.loads(line) for line in gzip.decompress(archive.read_bytes()).decode().splitlines()]
    manifest = {"source": "https://github.com/openai/human-eval", "downloaded": "2026-11-04", "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "ids": ["HumanEval/0", "HumanEval/12", "HumanEval/53"], "license": "MIT", "adaptation": "File-based agent task. Original tests and canonical solution retained. Not an official HumanEval score."}
    write(ROOT / "vendor/humaneval/provenance.json", json.dumps(manifest, indent=2) + "\n")
    for index in [0, 12, 53]:
        row = next(r for r in rows if r['task_id'] == f'HumanEval/{index}')
        starter = row['prompt'] + "    raise NotImplementedError\n"
        complete = row['prompt'] + row['canonical_solution']
        check = "import sys\nsys.path.insert(0, '/workspace')\nfrom candidate import " + row['entry_point'] + "\n" + row['test'] + "\ncheck(" + row['entry_point'] + ")\n"
        task(f"humaneval-{index}", "coding", "Complete candidate.py according to its docstring. Preserve the function signature.", {"candidate.py": starter}, "from pathlib import Path\nPath('candidate.py').write_text(" + repr(complete) + ")\n", check, f"openai/human-eval HumanEval/{index}; MIT")

    # Reusable data pipelines evaluate public and held-out inputs independently.
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
    sales_edge = 'id,region,amount,status\na,EU,,paid\na,EU,90,paid\nb,US,10,cancelled\nb,US,20,paid\nc,APAC,0.10,paid\nd,APAC,0.20,paid\ne,EU,-0.30,refunded\nf,US,0,paid\n'
    pipeline_task('ds-aggregation','data-science','Clean the CSV. Deduplicate by id first, retaining its first row even when that row is later excluded. Then exclude cancelled rows and empty amounts. Count all discarded rows in excluded_rows. Include signed refunds and valid zeros. Report net_total and by_region for regions with at least one retained valid row, including zero totals. Use decimal-safe arithmetic; input amounts have at most two decimal places.', 'sales.csv', sales, [sales_hidden, sales_edge], aggregation, [
        {'excluded_rows':3,'net_total':public_total,'by_region':{'EU':public_total,'US':0}},
        {'excluded_rows':3,'net_total':8.5,'by_region':{'US':10.5,'EU':-2}},
        {'excluded_rows':4,'net_total':0,'by_region':{'APAC':0.3,'EU':-0.3,'US':0}},
    ])
    rankings = json.dumps([{'relevant':['d1','d2'],'a':['d1','x','d2'],'b':['x','d1','y']},
                           {'relevant':['d3'],'a':['x','y','d3'],'b':['d3','x','y']},
                           {'relevant':['d4','d5'],'a':['x','y','z'],'b':['d5','d4','x']}])
    retrieval = '''import json, sys
with open(sys.argv[1]) as f: queries=json.load(f)
out={}
for system in ('a','b'):
    recalls=[]; reciprocals=[]
    for query in queries:
        relevant=set(query['relevant']); ranked=query[system][:3]
        recalls.append(len(set(ranked)&relevant)/len(relevant))
        reciprocals.append(next((1/(i+1) for i,x in enumerate(ranked) if x in relevant),0))
    out['recall_'+system]=sum(recalls)/len(queries)
    out['mrr_'+system]=sum(reciprocals)/len(queries)
av=(out['recall_a'],out['mrr_a']); bv=(out['recall_b'],out['mrr_b'])
out['winner']='a' if av>bv else 'b' if bv>av else 'tie'
for key in ('recall_a','recall_b','mrr_a','mrr_b'): out[key]=round(out[key],6)
with open(sys.argv[2],'w') as f: json.dump(out,f)
'''
    hidden_rankings = json.dumps([{'relevant':['r'],'a':['r','x','y'],'b':['x','y','z','r']},{'relevant':['s'],'a':['x','s','y'],'b':['x','y','s']}])
    retrieval_edge = json.dumps([{'relevant':['u','v'],'a':['x','u'],'b':['x','v']},
                                 {'relevant':['z'],'a':[],'b':[]}])
    pipeline_task('ds-retrieval','data-science',
        'Evaluate rankings with non-empty binary relevance sets and distinct result IDs. Result lists may be empty or shorter than three. Recall@3 for a query is the number of relevant IDs among its first three results divided by the total number of relevant IDs for that query. Reciprocal rank@3 is 1 divided by the one-based rank of the FIRST relevant result among the first three, or zero if absent. Average each metric across ALL queries, including queries with no hit. Ignore results after rank 3. Choose winner by mean recall, then mean MRR; return tie when both match. Choose before rounding, then round metrics to 6 decimals. Both metrics must be between 0 and 1.',
        'rankings.json', rankings, [hidden_rankings, retrieval_edge], retrieval, [
            {'winner':'b','recall_a':0.666667,'recall_b':0.833333,'mrr_a':0.444444,'mrr_b':0.833333},
            {'winner':'a','recall_a':1.0,'recall_b':0.5,'mrr_a':0.75,'mrr_b':0.166667},
            {'winner':'tie','recall_a':0.25,'recall_b':0.25,'mrr_a':0.25,'mrr_b':0.25},
        ], groups={'recall':['recall_a','recall_b'],'mrr':['mrr_a','mrr_b'],'winner':['winner']})


    json_task("ds-leakage", "data-science", "Audit experiment.json before approving a churn model. The prediction timestamp is month start and the evaluation should simulate future unseen customers. A leakage column uses information unavailable at that timestamp. The time_group policy uses a chronological holdout and keeps each customer in one partition. Preprocessing must be fitted without holdout data. Return leakage_columns (alphabetically sorted), split_policy chosen from random/time_group, fit_preprocessor_on chosen from all/train, reported_accuracy_trustworthy boolean. No model training is required.", {"experiment.json": json.dumps({"features": {"age": "available at month start", "tenure_months": "available at month start", "cancellation_reason": "recorded after customer cancels", "days_until_churn": "computed from future label"}, "rows": "multiple monthly observations per customer", "split": "random rows", "scaler_fit": "all rows", "reported_accuracy": 0.99})}, {"leakage_columns": ["cancellation_reason", "days_until_churn"], "split_policy": "time_group", "fit_preprocessor_on": "train", "reported_accuracy_trustworthy": False})

    sources = {"S1.txt": "S1 | Official specification | 2026-01-01\nAster supports 64 GB RAM; price 800 EUR excluding delivery.\n", "S2.txt": "S2 | Official correction | 2026-10-01\nSupersedes S1. Aster maximum RAM is 32 GB. Price remains 800 EUR.\n", "S3.txt": "S3 | Official specification | 2026-09-01\nBoreal supports 64 GB RAM; price 900 EUR including delivery.\n", "S4.txt": "S4 | Anonymous forum | 2026-10-02\nI think Aster supports 128 GB. No measurements or link.\n"}
    json_task("research-evidence", "research", "Use the four supplied fictional source documents. Select the product meeting at least 64 GB RAM and a delivered budget of 950 EUR, using authoritative current evidence. Return selected (product name), decisive_sources (sorted source IDs needed to establish both the choice and why Aster fails), aster_ram_gb, aster_delivery_cost_known (boolean). Official corrections supersede earlier official specifications; forum opinions do not override them. Treat an unreported delivery cost as unknown. This is evidence synthesis, not live web research.", sources, {"selected": "Boreal", "decisive_sources": ["S2", "S3"], "aster_ram_gb": 32, "aster_delivery_cost_known": False})

    ledger = {"invoices": [{"id":"i1","customer":"A","date":"2026-01-01","amount":10000},{"id":"i2","customer":"A","date":"2026-02-01","amount":5000},{"id":"i3","customer":"B","date":"2026-01-01","amount":4000}], "payments": [{"payment_id":"p1","customer":"A","amount":12000},{"payment_id":"p1","customer":"A","amount":12000},{"payment_id":"p2","customer":"B","amount":6000}]}
    ledger_hidden = {"invoices":[{"id":"late","customer":"A","date":"2026-04-01","amount":500},{"id":"early","customer":"A","date":"2026-01-01","amount":700},{"id":"unpaid","customer":"B","date":"2026-01-01","amount":300}], "payments":[{"payment_id":"same","customer":"A","amount":800},{"payment_id":"same","customer":"B","amount":9999},{"payment_id":"extra","customer":"C","amount":250}]}
    ledger_edge = {"invoices":[{"id":"b","customer":"A","date":"2026-01-01","amount":200},{"id":"a","customer":"A","date":"2026-01-01","amount":100}], "payments":[{"payment_id":"one","customer":"A","amount":150},{"payment_id":"two","customer":"B","amount":0}]}
    reconciliation = """import json, sys
from pathlib import Path
ledger=json.loads(Path(sys.argv[1]).read_text())
customers={i['customer'] for i in ledger['invoices']}|{p['customer'] for p in ledger['payments']}
credit=dict.fromkeys(customers,0); seen=set(); duplicates=0
for payment in ledger['payments']:
    if payment['payment_id'] in seen:
        duplicates+=1; continue
    seen.add(payment['payment_id'])
    credit[payment['customer']]+=payment['amount']
balances={}
for invoice in sorted(ledger['invoices'],key=lambda i:(i['date'],i['id'])):
    customer=invoice['customer']; applied=min(credit[customer],invoice['amount'])
    credit[customer]-=applied; balances[invoice['id']]=invoice['amount']-applied
Path(sys.argv[2]).write_text(json.dumps({'balances':balances,'unapplied_credit':credit,'duplicate_payments':duplicates}))
"""
    pipeline_task('general-reconciliation','general',
        'Read ledger.json. Amounts are non-negative integer cents. Deduplicate payments globally by payment_id, keeping the first occurrence even if a duplicate names another customer. Sum retained payments within each customer. Apply available credit to that customer’s invoices from oldest date to newest; break same-date ties by invoice id alphabetically. Invoice ids are unique. Return balances for EVERY invoice, unapplied_credit for EVERY customer mentioned in either input list (including zero), and duplicate_payments as the number of discarded payment rows. Never transfer credit between customers.',
        'ledger.json', json.dumps(ledger), [json.dumps(ledger_hidden),json.dumps(ledger_edge)], reconciliation, [
            {'balances':{'i1':0,'i2':3000,'i3':0},'unapplied_credit':{'A':0,'B':2000},'duplicate_payments':1},
            {'balances':{'early':0,'late':400,'unpaid':300},'unapplied_credit':{'A':0,'B':0,'C':250},'duplicate_payments':1},
            {'balances':{'a':0,'b':150},'unapplied_credit':{'A':0,'B':0},'duplicate_payments':0},
        ])


    history = "2026-01-01: Budget 1000 EUR. Preferred region EU.\n2026-02-01: Budget revised to 700 EUR; this replaces the old budget.\n"
    history += "".join(f"Log {i}: background batch completed; no preference changes.\n" for i in range(200))
    history += "2026-10-01: Preferred region now US. Budget unchanged.\n2026-11-01: The earlier budget revision remains valid. Do not infer a new budget.\n"
    json_task("context-revisions", "context", "Recover the current preferences from history.txt, using explicit revisions. Later statements change only the field they explicitly revise; an unchanged or reaffirmed value retains the date when it was set. Return budget_eur, region, budget_source_date. This tests file-based context retrieval, not cross-session memory or compaction.", {"history.txt": history}, {"budget_eur": 700, "region": "US", "budget_source_date": "2026-02-01"})
    pipeline_task(
        'startup', 'startup',
        'Read a JSON array of integers, which may be empty and may contain negative values. Write a reusable script that returns count and sum. An empty array has count 0 and sum 0.',
        'numbers.json', '[2, 3, 5]', ['[-1, 0, 4, 4]', '[]'],
        "import json, sys\nfrom pathlib import Path\nnumbers=json.loads(Path(sys.argv[1]).read_text())\nPath(sys.argv[2]).write_text(json.dumps({'count':len(numbers),'sum':sum(numbers)}))\n",
        [{'count':3,'sum':10}, {'count':4,'sum':7}, {'count':0,'sum':0}],
    )

    # Easy tier: small tasks a modest local model can complete, three per category.
    pipeline_task(
        'startup-wordcount', 'startup',
        'Read a text file that may be empty. Write a reusable script that returns the number of whitespace-separated words and the number of lines.',
        'text.txt', 'the quick brown fox\njumps over\n', ['', 'one\n\n  two  \n'],
        "import json, sys\nfrom pathlib import Path\ntext=Path(sys.argv[1]).read_text()\nPath(sys.argv[2]).write_text(json.dumps({'words':len(text.split()),'lines':len(text.splitlines())}))\n",
        [{'words':6,'lines':2}, {'words':0,'lines':0}, {'words':2,'lines':3}],
    )
    json_task("startup-greeting", "startup", "Read name.txt and return greeting, the text Hello, followed by a comma, a space, the name from the file and an exclamation mark.", {"name.txt": "Ada\n"}, {"greeting": "Hello, Ada!"})

    docs = {"notes-a.txt": "Release 1.2 | 2026-03-05\nAdds CSV export.\n", "notes-b.txt": "Release 1.4 | 2026-08-10\nAdds dark mode. Latest stable release.\n", "notes-c.txt": "Release 1.3 | 2026-06-20\nFixes login bugs.\n"}
    json_task("research-latest", "research", "Three release-note files are supplied, in no particular order. Return latest_version (the highest release number, as text) and released (its date as YYYY-MM-DD text).", docs, {"latest_version": "1.4", "released": "2026-08-10"})
    licenses = {"S1.txt": "S1 | Vendor page\nCedar is proprietary software. Evaluation licence only.\n", "S2.txt": "S2 | Project repository\nMaple is released under the MIT licence.\n", "S3.txt": "S3 | Vendor page\nOak is released under a commercial licence.\n"}
    json_task("research-source", "research", "Three short source files describe three fictional libraries. Find the library released under the MIT licence. Return library (its name) and source_id (the source ID that says so).", licenses, {"library": "Maple", "source_id": "S2"})

    expenses = 'category,amount_cents\nfood,1250\ntravel,9000\nfood,750\ntravel,500\noffice,9500\n'
    pipeline_task(
        'general-expenses', 'general',
        'Read expenses.csv, which may have no rows. Amounts are integer cents. Return total_cents, the number of expense rows as count, and top_category, the category with the largest total (alphabetically first on ties, empty string if no rows).',
        'expenses.csv', expenses, ['category,amount_cents\n', 'category,amount_cents\nb,100\na,100\nb,0\n'],
        "import csv, json, sys\nfrom pathlib import Path\nrows=list(csv.DictReader(open(sys.argv[1])))\ntotals={}\nfor r in rows: totals[r['category']]=totals.get(r['category'],0)+int(r['amount_cents'])\ntop=sorted(totals,key=lambda c:(-totals[c],c))[0] if totals else ''\nPath(sys.argv[2]).write_text(json.dumps({'total_cents':sum(totals.values()),'count':len(rows),'top_category':top}))\n",
        [{'total_cents':21000,'count':5,'top_category':'office'}, {'total_cents':0,'count':0,'top_category':''}, {'total_cents':200,'count':3,'top_category':'a'}],
    )
    pipeline_task(
        'general-contacts', 'general',
        'Read contacts.json, a list of email strings that may be empty. Two emails are the same when they match after trimming spaces and lowercasing. Return unique, the number of distinct emails, and duplicates, the number of discarded repeats.',
        'contacts.json', json.dumps(['a@example.com', 'B@example.com ', 'b@example.com', 'c@example.com']), [json.dumps([]), json.dumps([' X@example.org', 'x@example.org', 'X@EXAMPLE.ORG'])],
        "import json, sys\nfrom pathlib import Path\nitems=[e.strip().lower() for e in json.loads(Path(sys.argv[1]).read_text())]\nPath(sys.argv[2]).write_text(json.dumps({'unique':len(set(items)),'duplicates':len(items)-len(set(items))}))\n",
        [{'unique':3,'duplicates':1}, {'unique':0,'duplicates':0}, {'unique':1,'duplicates':2}],
    )

    log = "".join(f"Log {i}: heartbeat ok.\n" for i in range(150)) + "NOTICE: the access code is 7413-KX.\n" + "".join(f"Log {i}: heartbeat ok.\n" for i in range(150, 300))
    json_task("context-needle", "context", "Find the single access code stated in log.txt. Return access_code as text, exactly as written.", {"log.txt": log}, {"access_code": "7413-KX"})
    notes = "2026-01-10: Contact email is old@example.com.\n" + "".join(f"Note {i}: nothing changed.\n" for i in range(100)) + "2026-05-02: Contact email changed to new@example.com.\n" + "".join(f"Note {i}: nothing changed.\n" for i in range(100, 150))
    json_task("context-contact", "context", "Return the current contact email from notes.txt as email, and the date the current value was set as since (YYYY-MM-DD). Later explicit changes replace earlier values.", {"notes.txt": notes}, {"email": "new@example.com", "since": "2026-05-02"})

    fib70 = 0
    a, b = 0, 1
    for _ in range(70):
        a, b = b, a + b
    fib70 = a
    digit_count = sum(1 for n in range(1, 300001) if n % 7 == 0 and sum(map(int, str(n))) == 20)
    sieve = [True] * 100002
    sieve[0] = sieve[1] = False
    for i in range(2, 317):
        if sieve[i]:
            for j in range(i * i, 100002, i):
                sieve[j] = False
    primes = [i for i in range(100000) if sieve[i]]
    twin = max(p for p in primes if sieve[p + 2])

    # Math tier. Large exact computations that a small model rarely gets right unaided,
    # so the result depends on whether the harness lets and pushes it to run code (PAL / PoT).
    json_task("math-word", "math", "Maya has 50 EUR. She buys 4 notebooks at 3.50 EUR each and 6 pens at 0.75 EUR each. Return change_eur (money left, a number) and items (how many things she bought, an integer).", {"problem.txt": "Maya has 50 EUR. She buys 4 notebooks at 3.50 EUR each and 6 pens at 0.75 EUR each.\n"}, {"change_eur": 50 - 4*3.5 - 6*0.75, "items": 10})
    json_task("math-bignum", "math", "Compute exactly: product = 48271 * 69313; power_mod = the remainder of 3 to the power 2026 divided by 1000007; fibonacci_70 = the 70th Fibonacci number with fib(1)=1 and fib(2)=1. Return them as integers. Use the shell or Python to compute; do not estimate.", {"README.txt": "Exact integer arithmetic. Python 3 is installed.\n"}, {"product": 48271 * 69313, "power_mod": pow(3, 2026, 1000007), "fibonacci_70": fib70})
    json_task("math-count", "math", "Using code, count: digit_sum_20 = the integers n with 1 <= n <= 300000 whose decimal digits sum to 20 and that are divisible by 7; primes_below_100000 = the number of primes below 100000; twin_prime_below_100000 = the largest p below 100000 such that p and p+2 are both prime. Return integers. Use the shell or Python; do not estimate.", {"README.txt": "Counting with code. Python 3 is installed.\n"}, {"digit_sum_20": digit_count, "primes_below_100000": len(primes), "twin_prime_below_100000": twin})
    # Coding tier: the model has to run code (tests, a simulation) to get the answer right.
    for folder in sorted((ROOT / "scripts/templates/code").iterdir()):
        files = {p.name: p.read_text() for p in (folder / "inputs").iterdir() if p.is_file()}
        task(folder.name, "coding", (folder / "instruction.md").read_text().rstrip("\n"), files,
             (folder / "solve.py").read_text(), (folder / "check.py").read_text(), "written for this benchmark", "medium")
    print(f"Prepared {len(list(TASKS.iterdir()))} Harbor tasks")


if __name__ == '__main__':
    main()
