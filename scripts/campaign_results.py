"""Shared result classification and notebook plots, including older campaigns."""
import csv
import json
from collections import Counter
from pathlib import Path

STATUSES = ["passed", "incorrect", "timeout", "technical_error", "not_run", "incomplete", "installed"]
COLORS = {"passed":"#198754","incorrect":"#d9534f","timeout":"#e5a11a",
          "technical_error":"#8763b5","not_run":"#d9dee4","incomplete":"#7c8998","installed":"#387ca6"}


def classify(result, *, installed=False, started=False):
    error = result.get("exception_info") or {}
    if error:
        return "timeout" if "Timeout" in error.get("exception_type","") else "technical_error"
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
    legacy = {"graded":None, "AgentTimeoutError":"timeout"}
    for row in rows:
        status = row["status"]
        if status == "graded":
            row["status"] = "passed" if row.get("reward") in ("1","1.0") else "incorrect"
        elif status not in STATUSES:
            row["status"] = legacy.get(status) or ("incomplete" if status=="incomplete" else "technical_error")
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


def plot_results(rows):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    if not rows:
        raise ValueError("The campaign has no scheduled trials.")
    harnesses = sorted({r["harness"] for r in rows})
    fig, grid = plt.subplots(2,2,figsize=(13,9),layout="constrained")
    axes = grid.flat
    for i,harness in enumerate(harnesses):
        group = [r for r in rows if r["harness"]==harness]
        counts = Counter(r["status"] for r in group)
        success = 100*counts["passed"]/len(group)
        axes[0].barh(i, success, color=COLORS["passed"], height=0.6)
        axes[0].text(success-2 if success>=90 else success+2, i,
                     f"{success:.0f}% ({counts['passed']}/{len(group)})",
                     va="center",ha="right" if success>=90 else "left")
        left = 0
        for status in STATUSES:
            width = 100*counts[status]/len(group)
            axes[1].barh(i,width,left=left,color=COLORS[status],label=status if i==0 else None)
            if width:
                axes[1].text(left+width/2,i,f"{width:.0f}%",ha="center",va="center",fontsize=9)
            left += width
    for ax in list(grid.flat)[:2]:
        ax.set_yticks(range(len(harnesses)),harnesses)
        ax.set_xlim(0,100)
        ax.xaxis.set_major_formatter(PercentFormatter(100))
        ax.invert_yaxis()
        ax.spines[["top","right"]].set_visible(False)
    axes[0].set_title("Strict success / all scheduled trials")
    axes[1].set_title("Trial outcomes / all scheduled trials")
    axes[1].legend(loc="upper center",bbox_to_anchor=(0.5,-0.15),ncol=3,fontsize=8)
    import numpy as np
    for i,harness in enumerate(harnesses):
        times = [float(r["agent_seconds"]) for r in rows
                 if r["harness"]==harness and r.get("agent_seconds")]
        if times:
            mean = sum(times)/len(times)
            axes[2].barh(i,mean,color="#387ca6")
            axes[2].text(mean,i,f" {mean:.1f}s",va="center")
        else:
            axes[2].text(0,i,"unknown",va="center")
    axes[2].set_yticks(range(len(harnesses)),harnesses)
    axes[2].invert_yaxis()
    axes[2].set_title("Mean agent time, including timed-out trials")
    axes[2].set_xlabel("Seconds")
    axes[2].set_xlim(0,max(1,axes[2].get_xlim()[1]*1.15))
    criteria = sorted({k for row in rows for k in json.loads(row.get("criteria_json") or "{}")})
    if criteria:
        matrix = np.full((len(harnesses),len(criteria)),np.nan)
        for i,harness in enumerate(harnesses):
            for j,key in enumerate(criteria):
                values = [checks[key] for row in rows if row["harness"]==harness
                          for checks in [json.loads(row.get("criteria_json") or "{}")]
                          if key in checks and isinstance(checks[key],bool)]
                if values:
                    matrix[i,j] = 100*sum(values)/len(values)
        cmap = plt.get_cmap("RdYlGn").with_extremes(bad="#d9dee4")
        axes[3].imshow(matrix,vmin=0,vmax=100,cmap=cmap,aspect="auto")
        axes[3].set_xticks(range(len(criteria)),criteria,rotation=40,ha="right",fontsize=8)
        axes[3].set_yticks(range(len(harnesses)),harnesses)
        for i in range(len(harnesses)):
            for j in range(len(criteria)):
                axes[3].text(j,i,"N/A" if np.isnan(matrix[i,j]) else f"{matrix[i,j]:.0f}%",
                             ha="center",va="center",fontsize=8)
    else:
        axes[3].text(0.5,0.5,"No diagnostic checks recorded",ha="center",va="center")
        axes[3].set_axis_off()
    axes[3].set_title("Diagnostic checks / trials with that check")
    return fig
