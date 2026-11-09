"""Lightweight statistics checks. No harness, server or container is started."""
import csv
import json
import math
from pathlib import Path

import pytest

from scripts.campaign_results import (
    classify, diagnostic_checks, load_rows, number, paired_outcomes,
    summarize, summary_html, wilson_interval,
)


def trial(harness="pi", model="tiny", task="analysis", status="incorrect", **kwargs):
    return dict(harness=harness,model=model,task=task,status=status,attempt=0,category="data-science",**kwargs)


def test_work_score_excludes_startup_and_keeps_all_failures():
    rows = [trial(task="startup",status="passed"),trial(status="passed"),
            trial(task="b",status="timeout"),trial(task="c",status="not_run"),
            trial(task="d",status="technical_error")]
    result, = summarize(rows)
    assert result["scheduled"] == 5
    assert result["scored"] == 4
    assert result["passed"] == 1
    assert result["success_rate"] == 25
    assert result["startup_passed"] == result["startup_scheduled"] == 1


def test_only_startup_has_no_work_score():
    result, = summarize([trial(task="startup",status="passed")])
    assert result["success_rate"] is None
    assert result["success_ci_low"] is None
    assert "N/A" in summary_html([trial(task="startup",status="passed")])


def test_measurement_coverage_preserves_unknown_and_real_zero():
    result, = summarize([trial(status="passed",cost_usd=0,input_tokens=0,agent_seconds=0),
                         trial(task="b",cost_usd="",input_tokens="NaN",agent_seconds="")])
    assert result["known_cost_usd"] == result["input_tokens"] == 0
    assert result["cost_observations"] == result["input_tokens_observations"] == 1
    assert result["output_tokens"] is None
    assert result["median_seconds"] == 0
    assert result["time_observations"] == 1
    assert summarize([trial()])[0]["known_cost_usd"] is None
    assert all(number(value) is None for value in (True,False,"NaN","inf",-1,"broken",None))


def test_wilson_interval_warns_about_small_zero_and_perfect_samples():
    low,high = wilson_interval(0,1)
    assert low == 0 and high > 75
    low,high = wilson_interval(1,1)
    assert low < 25 and high == 100
    assert wilson_interval(0,0) == (None,None)


def test_models_are_not_pooled_or_paired_across_tags():
    rows = [trial(model="a",status="passed"),trial(model="b"),trial(harness="dsh",model="b",status="passed")]
    assert len(summarize(rows)) == 3
    pairs = paired_outcomes(rows)
    assert len(pairs) == 1 and pairs[0]["model"] == "b"
    assert pairs[0]["left_wins"] == 1 and pairs[0]["right_wins"] == 0


def test_matched_counts_retain_timeout_and_exclude_unexecuted_trials():
    rows = [trial(status="passed"),trial(harness="dsh",status="timeout"),
            trial(task="b",status="not_run"),trial(harness="dsh",task="b",status="passed"),
            trial(task="startup",status="passed"),trial(harness="dsh",task="startup",status="passed")]
    pair, = paired_outcomes(rows)
    assert pair["matched"] == 1 and pair["right_wins"] == 1
    assert pair["unmatched"] == 2 and pair["ties"] == 0
    with pytest.raises(ValueError,match="Duplicate"):
        paired_outcomes([trial(),trial(),trial(harness="dsh")])


def test_legacy_statuses_and_corrupt_diagnostics_remain_readable(tmp_path):
    with (tmp_path/"results.csv").open("w",newline="") as handle:
        writer = csv.DictWriter(handle,fieldnames=["harness","status","reward","criteria_json"])
        writer.writeheader()
        writer.writerows([dict(harness="pi",status="graded",reward="0",criteria_json="not json"),
                          dict(harness="dsh",status="AgentTimeoutError",reward="",criteria_json="[]"),
                          dict(harness="opencode",status="graded",reward="",criteria_json="{}")])
    rows = load_rows(tmp_path)
    assert [r["status"] for r in rows] == ["incorrect","timeout","incomplete"]
    assert all(diagnostic_checks(r)=={} for r in rows)
    assert diagnostic_checks({"criteria_json":json.dumps({"a":True,"b":1,"c":None})}) == {"a":True}
    assert classify({"exception_info":{"exception_type":None}}) == "technical_error"


def test_html_escapes_labels_and_displays_zero_measurements():
    output = summary_html([trial(harness="<script>",cost_usd=0,input_tokens=0,agent_seconds=0)])
    assert "<script>" not in output and "&lt;script&gt;" in output
    assert "$0.0000 (1/1)" in output
    assert "0.0s (1/1)" in output


def test_notebook_has_separate_preview_and_safe_default():
    notebook = json.loads((Path(__file__).parents[1]/"notebooks/local-comparison.ipynb").read_text())
    sources = "\n".join("".join(c["source"]) for c in notebook["cells"])
    assert "run_new_campaign = False" in sources
    assert "Preview only:" in sources
    assert "campaign_results.plot_task_results(rows)" in sources
    assert all(not c["outputs"] and c["execution_count"] is None for c in notebook["cells"] if c["cell_type"]=="code")


def test_category_plot_handles_missing_categories_and_nonfinite_time():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scripts.campaign_results import plot_results,plot_task_results
    rows = [trial(status="passed",agent_seconds="inf",criteria_json="bad"),
            trial(harness="dsh",task="other",status="timeout",agent_seconds=180)]
    overview = plot_results(rows)
    tasks = plot_task_results(rows)
    assert overview.axes[2].get_xlim()[1] > 180
    assert "unknown" in [t.get_text() for t in overview.axes[2].texts]
    assert "N/A" in [t.get_text() for t in tasks.axes[1].texts]
    plt.close(overview)
    plt.close(tasks)
