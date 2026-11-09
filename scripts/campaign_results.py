"""Shared result classification and notebook plots, including older campaigns."""
import csv
import json
from collections import Counter
from pathlib import Path
import math
import statistics
from itertools import combinations

STATUSES = ["passed", "incorrect", "timeout", "technical_error", "not_run", "incomplete", "installed"]
COLORS = {"passed":"#198754","incorrect":"#d9534f","timeout":"#e5a11a",
          "technical_error":"#8763b5","not_run":"#d9dee4","incomplete":"#7c8998","installed":"#387ca6"}


def classify(result, *, installed=False, started=False):
    error = result.get("exception_info") or {}
    if error:
        return "timeout" if "timeout" in (error.get("exception_type") or "").lower() else "technical_error"
    if installed and result:
        return "installed"
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    if "reward" in rewards:
        return "passed" if rewards["reward"] == 1 else "incorrect"
    return "incomplete" if started or result else "not_run"


def load_rows(campaign):
    with (Path(campaign)/"results.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    # Historical CSVs retain their original values on disk.
    legacy = {"AgentTimeoutError":"timeout", "VerifierTimeoutError":"timeout"}
    for row in rows:
        status = row["status"]
        if status == "graded":
            row["status"] = ("incomplete" if number(row.get("reward")) is None else
                             "passed" if number(row.get("reward")) == 1 else "incorrect")
        elif status not in STATUSES:
            row["status"] = legacy.get(status) or ("timeout" if "timeout" in (status or "").lower() else "technical_error")
    for row in rows:
        if row.get("criteria_json") or row.get("task") != "ds-retrieval" or not row.get("result"):
            continue
        # Recover public-output diagnostics from older campaigns without executing agent code.
        workspace = Path(row["result"]).parent/"artifacts/workspace"
        if not workspace.exists():
            continue
        checks = {"script_present":(workspace/"analyze.py").is_file()}
        answer = workspace/"answer.json"
        if answer.exists():
            try:
                import math
                actual = json.loads(answer.read_text())
                for metric, expected in (("recall",(0.666667,0.833333)),("mrr",(0.444444,0.833333))):
                    values = [actual.get(metric+"_"+system) for system in ("a","b")]
                    checks["saved_public_"+metric] = all(
                        isinstance(v,(int,float)) and math.isclose(v,w,abs_tol=1e-6,rel_tol=0)
                        for v,w in zip(values,expected))
                checks["saved_public_winner"] = actual.get("winner")=="b"
            except (ValueError,TypeError,AttributeError):
                pass
        row["criteria_json"] = json.dumps(checks)
    return rows



def number(value):
    """Return a finite nonnegative measurement, preserving unknowns."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def diagnostic_checks(row):
    try:
        checks = json.loads(row.get("criteria_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return {key:value for key,value in checks.items() if isinstance(value,bool)} if isinstance(checks,dict) else {}


def wilson_interval(passed, total):
    """Exploratory 95% binomial interval, in percent; no population claim."""
    if not total:
        return None, None
    z = 1.959963984540054
    p = passed / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total))/denominator
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator
    return 100*max(0,center-half), 100*min(1,center+half)


def is_work_trial(row):
    return row.get("task") != "startup" and row.get("status") != "installed"


def _configurations(rows):
    return sorted({(r["harness"],r.get("model") or "unknown") for r in rows})


def _label(key, keys):
    harness, model = key
    return harness + (" / " + model if len({k[1] for k in keys})>1 else "")


def summarize(rows):
    """One record per harness and model. Startup is a separate health check.

    Success divides passed work trials by scheduled work trials, including
    timeouts, errors and unfinished work. Costs and tokens retain coverage.
    """
    records = []
    for harness,model in _configurations(rows):
        group = [r for r in rows if r["harness"]==harness and (r.get("model") or "unknown")==model]
        work = [r for r in group if is_work_trial(r)]
        passed = sum(r["status"]=="passed" for r in work)
        low,high = wilson_interval(passed,len(work))
        times = [value for r in work if (value:=number(r.get("agent_seconds"))) is not None]
        costs = [value for r in group if (value:=number(r.get("cost_usd"))) is not None]
        tasks = sorted({r.get("task") or "unknown" for r in work})
        record = dict(harness=harness, model=model, scheduled=len(group), scored=len(work),
                      passed=passed, success_rate=100*passed/len(work) if work else None,
                      success_ci_low=low, success_ci_high=high,
                      distinct_tasks=len(tasks),
                      median_seconds=statistics.median(times) if times else None,
                      time_observations=len(times),
                      known_cost_usd=sum(costs) if costs else None,
                      cost_observations=len(costs),
                      startup_passed=sum(r["status"]=="passed" for r in group if r.get("task")=="startup"),
                      startup_scheduled=sum(r.get("task")=="startup" for r in group),
                      outcomes=dict(Counter(r["status"] for r in work)))
        for key in ("input_tokens","output_tokens"):
            values = [v for r in group if (v:=number(r.get(key))) is not None]
            record[key] = sum(values) if values else None
            record[key+"_observations"] = len(values)
        records.append(record)
    return records


def paired_outcomes(rows):
    """Descriptive pairs only: identical model, task and attempt; no p-values."""
    configurations = _configurations(rows)
    records = []
    for left,right in combinations(configurations,2):
        if left[1] != right[1] or left[1]=="unknown":
            continue
        maps = []
        for harness,model in (left,right):
            mapping = {}
            for row in rows:
                if (row["harness"],row.get("model") or "unknown") != (harness,model) or not is_work_trial(row):
                    continue
                key = (row.get("task"),str(row.get("attempt",0)))
                if key in mapping:
                    raise ValueError("Duplicate trial identity in comparison results.")
                mapping[key] = row["status"]
            maps.append(mapping)
        common = sorted(maps[0].keys() & maps[1].keys())
        # Not-run and incomplete trials cannot support a matched comparison.
        eligible = [key for key in common if all(m[key] not in ("not_run","incomplete") for m in maps)]
        wins = sum(maps[0][key]=="passed" and maps[1][key]!="passed" for key in eligible)
        losses = sum(maps[1][key]=="passed" and maps[0][key]!="passed" for key in eligible)
        records.append(dict(left=left[0],right=right[0],model=left[1],matched=len(eligible),
                            left_wins=wins,right_wins=losses,ties=len(eligible)-wins-losses,
                            unmatched=len(maps[0])+len(maps[1])-2*len(eligible)))
    return records


def summary_html(rows):
    """Compact notebook table with escaped labels and explicit unknowns."""
    import html
    def text(value):
        return html.escape(str(value))
    table = []
    for r in summarize(rows):
        rate = "N/A" if r["success_rate"] is None else f'{r["success_rate"]:.0f}% ({r["passed"]}/{r["scored"]})'
        interval = "N/A" if r["success_rate"] is None else f'{r["success_ci_low"]:.0f}–{r["success_ci_high"]:.0f}%'
        time = "unknown" if r["median_seconds"] is None else f'{r["median_seconds"]:.1f}s ({r["time_observations"]}/{r["scored"]})'
        cost = "unknown" if r["known_cost_usd"] is None else f'${r["known_cost_usd"]:.4f} ({r["cost_observations"]}/{r["scheduled"]})'
        startup = f'{r["startup_passed"]}/{r["startup_scheduled"]}' if r["startup_scheduled"] else "not scheduled"
        tokens = []
        for key in ("input_tokens","output_tokens"):
            tokens.append("unknown" if r[key] is None else f'{r[key]:,.0f} ({r[key+"_observations"]}/{r["scheduled"]})')
        values = (r["harness"],r["model"],rate,interval,r["distinct_tasks"],time,cost,*tokens,startup)
        table.append("<tr>"+"".join("<td>"+text(value)+"</td>" for value in values)+"</tr>")
    headings = ("Harness","Model","Work success","95% interval*","Work tasks","Median time (coverage)","Known USD cost (coverage)","Input tokens (coverage)","Output tokens (coverage)","Startup")
    return ('<style>.hb-table{border-collapse:collapse;font:13px system-ui;width:100%;color:#152c45;background:white;}'
            '.hb-table th{background:#152c45;color:white;text-align:left;}'
            '.hb-table td,.hb-table th{padding:10px;border-bottom:1px solid #dce4ee;}'
            '.hb-table tr:nth-child(even){background:#f2f6fa;}</style>'
            '<div style="overflow-x:auto"><table class="hb-table"><thead><tr>'+"".join("<th>"+h+"</th>" for h in headings)
            +'</tr></thead><tbody>'+"".join(table)+'</tbody></table></div>')


def plot_results(rows, diagnostic_task=None):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    import numpy as np

    if not rows:
        raise ValueError("The campaign has no scheduled trials.")
    keys = _configurations(rows)
    labels = [_label(key,keys) for key in keys]
    records = summarize(rows)
    active_statuses = [status for status in STATUSES
                       if any(record["outcomes"].get(status,0) for record in records)]
    fig,grid = plt.subplots(2,2,figsize=(13,9),layout="constrained")
    axes = grid.flat
    for i,record in enumerate(records):
        n = record["scored"]
        success = record["success_rate"]
        if success is None:
            axes[0].text(2,i,"N/A (no work trials)",va="center")
        else:
            axes[0].barh(i,success,color=COLORS["passed"],height=0.55,alpha=0.8)
            axes[0].errorbar(success,i,xerr=[[success-record["success_ci_low"]],[record["success_ci_high"]-success]],
                             color="#152c45",capsize=4,lw=1.4)
            axes[0].text(2 if success<50 else 98,i+0.29,f"{success:.0f}% ({record['passed']}/{n})",
                         va="center",ha="left" if success<50 else "right",fontsize=9)
        left = 0
        for status in active_statuses:
            width = 100*record["outcomes"].get(status,0)/n if n else 0
            axes[1].barh(i,width,left=left,color=COLORS[status],label=status.replace("_"," ") if i==0 else None)
            if width>=8:
                axes[1].text(left+width/2,i,f"{width:.0f}%",ha="center",va="center",fontsize=9)
            left += width
    for ax in list(grid.flat)[:2]:
        ax.set_yticks(range(len(keys)),labels)
        ax.set_xlim(0,100)
        ax.xaxis.set_major_formatter(PercentFormatter(100))
        ax.invert_yaxis()
        ax.spines[["top","right"]].set_visible(False)
    axes[0].set_title("Work success · 95% exploratory intervals")
    axes[1].set_title("Work outcomes · all scheduled work trials")
    axes[1].legend(loc="upper center",bbox_to_anchor=(0.5,-0.15),ncol=3,fontsize=8)
    for i,record in enumerate(records):
        value = record["median_seconds"]
        if value is not None:
            axes[2].barh(i,value,color="#387ca6",alpha=0.9)
            axes[2].text(value,i,f" {value:.1f}s",va="center")
        else:
            axes[2].text(0,i,"unknown",va="center")
    axes[2].set_yticks(range(len(keys)),labels)
    axes[2].invert_yaxis()
    axes[2].set_title("Median work time · includes observed timeouts")
    axes[2].set_xlabel("Seconds · missing timings excluded")
    axes[2].set_xlim(0,max(1,axes[2].get_xlim()[1]*1.2))
    available_tasks = sorted({row.get("task") or "unknown" for row in rows if diagnostic_checks(row)})
    if diagnostic_task is None and available_tasks:
        diagnostic_task = next((task for task in available_tasks if task!="startup"),available_tasks[0])
    diagnostic_rows = [row for row in rows if (row.get("task") or "unknown")==diagnostic_task]
    criteria = sorted({key for row in diagnostic_rows for key in diagnostic_checks(row)})
    if criteria:
        matrix = np.full((len(keys),len(criteria)),np.nan)
        counts = {}
        for i,(harness,model) in enumerate(keys):
            for j,key in enumerate(criteria):
                values = [checks[key] for row in diagnostic_rows
                          if (row["harness"],row.get("model") or "unknown")== (harness,model)
                          for checks in [diagnostic_checks(row)] if key in checks]
                if values:
                    matrix[i,j] = 100*sum(values)/len(values)
                    counts[i,j] = len(values)
        cmap = plt.get_cmap("RdYlGn").with_extremes(bad="#d9dee4")
        axes[3].imshow(matrix,vmin=0,vmax=100,cmap=cmap,aspect="auto")
        axes[3].set_xticks(range(len(criteria)),criteria,rotation=40,ha="right",fontsize=8)
        axes[3].set_yticks(range(len(keys)),labels)
        for i in range(len(keys)):
            for j in range(len(criteria)):
                value = matrix[i,j]
                axes[3].text(j,i,"N/A" if np.isnan(value) else f"{value:.0f}%\nn={counts[i,j]}",
                             ha="center",va="center",fontsize=8)
    else:
        axes[3].text(0.5,0.5,"No diagnostic checks recorded",ha="center",va="center")
        axes[3].set_axis_off()
    axes[3].set_title("Diagnostics · " + (diagnostic_task or "no task") + " · observed checks")
    fig.suptitle("Campaign overview · startup excluded from work scores",fontsize=15,fontweight="bold",color="#152c45")
    return fig


def plot_task_results(rows):
    """Heatmaps retain the task mix and show missing categories as N/A."""
    import matplotlib.pyplot as plt
    import numpy as np
    keys = _configurations(rows)
    if not keys:
        raise ValueError("The campaign has no scheduled trials.")
    tasks = sorted({r.get("task") or "unknown" for r in rows},key=lambda task:(task!="startup",task))
    categories = sorted({r.get("category") or "unknown" for r in rows if is_work_trial(r)})
    fig,axes = plt.subplots(1,2,figsize=(14,max(3.5,len(keys)*0.8+2)),layout="constrained",
                            gridspec_kw={"width_ratios":[max(1,len(categories)),max(1,len(tasks))]})
    for ax,columns,field,title in ((axes[0],categories,"category","By category · work only"),
                                   (axes[1],tasks,"task","By task · startup shown separately")):
        matrix = np.full((len(keys),max(1,len(columns))),np.nan)
        counts = {}
        for i,(harness,model) in enumerate(keys):
            for j,column in enumerate(columns):
                group = [r for r in rows if (r["harness"],r.get("model") or "unknown")== (harness,model)
                         and (r.get(field) or "unknown")==column and r["status"]!="installed"
                         and (field!="category" or is_work_trial(r))]
                if group:
                    passed = sum(r["status"]=="passed" for r in group)
                    matrix[i,j] = 100*passed/len(group)
                    counts[i,j] = (passed,len(group))
        ax.imshow(matrix,vmin=0,vmax=100,cmap=plt.get_cmap("YlGnBu").with_extremes(bad="#e4e9ef"),aspect="auto")
        display_columns = ["startup (health check)" if field=="task" and col=="startup" else col for col in columns]
        ax.set_xticks(range(len(columns)),display_columns,rotation=35,ha="right",fontsize=9)
        if field=="task" and columns and columns[0]=="startup" and len(columns)>1:
            ax.axvline(0.5,color="#152c45",linewidth=2)
        ax.set_yticks(range(len(keys)),[_label(key,keys) for key in keys])
        for i in range(len(keys)):
            for j in range(max(1,len(columns))):
                value = matrix[i,j]
                label = "N/A" if np.isnan(value) else f"{value:.0f}%\n{counts[i,j][0]}/{counts[i,j][1]}"
                ax.text(j,i,label,ha="center",va="center",fontsize=9,
                        color="white" if not np.isnan(value) and value>=65 else "#152c45")
        ax.set_title(title)
    fig.suptitle("Success by task mix · counts are passed / scheduled",fontsize=15,fontweight="bold",color="#152c45")
    return fig
