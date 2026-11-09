import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import bench
from adapters.command import parse_usage
from adapters.command import DSH


def test_budget_rejects_oversized_campaign():
    with pytest.raises(ValueError, match='above'):
        bench.build_plan('full', ['omp','droid','dsh','pi'], {}, 1)


def test_small_plan_reproducible_and_free_oracle():
    a = bench.build_plan('quick', ['omp','pi'], {}, 1)
    assert a == bench.build_plan('quick', ['omp','pi'], {}, 1)
    assert a['runs'] == 12 and a['reserved_eur'] == 12
    assert bench.build_plan('full', ['oracle','nop'], {}, 2)['reserved_eur'] == 0


def test_paid_run_requires_real_budget_attestation():
    with pytest.raises(ValueError, match='Paid run blocked'):
        bench.execute(bench.build_plan('smoke',['omp'], {'omp':'anthropic/test'}))


@pytest.mark.parametrize('name', sorted(p.name for p in (bench.ROOT/'tasks').iterdir()))
def test_grader_accepts_oracle_rejects_missing_and_wrong(name, tmp_path):
    task = bench.ROOT/'tasks'/name
    shutil.copytree(task/'environment/inputs', tmp_path, dirs_exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    check = [sys.executable, str(task/'tests/check.py')]
    assert subprocess.run(check, cwd=tmp_path, env=env, capture_output=True, timeout=10).returncode != 0
    subprocess.run([sys.executable, str(task/'solution/solve.py')], cwd=tmp_path, env=env, check=True, timeout=10)
    result = subprocess.run(check, cwd=tmp_path, env=env, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    if (tmp_path/'analyze.py').exists():
        (tmp_path/'analyze.py').write_text("raise RuntimeError('deliberately wrong')\n")
    elif (tmp_path/'answer.json').exists():
        answer = json.loads((tmp_path/'answer.json').read_text())
        answer[next(iter(answer))] = 'deliberately wrong'
        (tmp_path/'answer.json').write_text(json.dumps(answer))
    else:
        text = (tmp_path/'candidate.py').read_text()
        (tmp_path/'candidate.py').write_text(text + '\n' + "def " + ('has_close_elements' if name=='humaneval-0' else 'longest') + "(*args, **kwargs): raise RuntimeError('bad')\n")
    assert subprocess.run(check, cwd=tmp_path, env=env, capture_output=True, timeout=10).returncode != 0


def test_usage_does_not_treat_missing_cost_as_zero():
    assert parse_usage('garbage', 'dsh') == {}
    usage = parse_usage(json.dumps({'type':'result','usage':{'input_tokens':10,'output_tokens':5,'cache_read_input_tokens':20}}), 'droid')
    assert usage['n_input_tokens'] == 30
    assert 'cost_usd' not in usage


def test_dsh_model_selection_registers_the_provider_without_secret():
    patch = DSH.model_patch('anthropic/claude-sonnet-4-5')
    assert patch[0]['config']['model'] == 'claude-sonnet-4-5'
    assert patch[1]['config']['providers']['anthropic']['apiKeyEnv'] == 'ANTHROPIC_API_KEY'
    assert DSH.model_patch('deepseek/deepseek-flash')[0]['config']['provider'] == 'deepseek-official'
    with pytest.raises(ValueError):
        DSH.model_patch('not-a-provider/model')


def test_usage_deduplicates_terminal_vs_stream_events():
    message = {'role':'assistant','usage':{'input':10,'cacheRead':20,'cacheWrite':5,'output':3,'cost':{'total':0.01}}}
    text = '\n'.join(json.dumps({'type':t,'message':message}) for t in ('message_start','message_update','message_end'))
    assert parse_usage(text,'omp') == {'n_input_tokens':35,'n_cache_tokens':20,'n_output_tokens':3,'cost_usd':0.01}


def test_report_preserves_errors_and_unknown_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(bench,'ROOT',tmp_path)
    campaign = tmp_path/'campaign'; campaign.mkdir()
    cells = [{'harness':'omp','model':'test','task':'a','attempt':0,'job':'one'}, {'harness':'omp','model':'test','task':'b','attempt':0,'job':'two'}]
    (campaign/'manifest.json').write_text(json.dumps({'cells':cells}))
    result = tmp_path/'runs/jobs/one/trial/result.json'; result.parent.mkdir(parents=True)
    result.write_text(json.dumps({'verifier_result':{'rewards':{'reward':1}},'agent_result':{}}))
    rows = bench.report(campaign)
    assert len(rows) == 2 and rows[1]['status']=='not_run'
    assert all(r['cost_usd'] is None for r in rows)
    assert '1/2' in (campaign/'report.md').read_text()


def test_local_pair_uses_same_weights_and_no_provider_credential(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'unused-cloud-key')
    names = ['pi', 'opencode']
    plan = bench.build_plan('demo', names, dict.fromkeys(names, 'qwen3:4b'), local=True)
    assert plan['reserved_eur'] == 0
    for cell in plan['cells']:
        agent = bench.job_config(cell, 'local-test', local=True)['agents'][0]
        assert agent['base_url'] == 'http://host.docker.internal:11434/v1'
        assert agent['model_name'].endswith('/qwen3:4b')
        assert agent['env'] == {'BENCH_LOCAL_KEY': 'ollama'}
        if cell['harness'] == 'opencode':
            assert agent['model_name'].startswith('bench-local/')
            assert agent['skip_model_parsing']
    with pytest.raises(ValueError, match='Local inference'):
        bench.build_plan('demo', ['claude'], {'claude': 'qwen3:4b'}, local=True)


def test_timeout_keeps_its_status_even_with_a_zero_grade():
    from scripts.campaign_results import classify
    result = {
        "exception_info": {"exception_type": "AgentTimeoutError"},
        "verifier_result": {"rewards": {"reward": 0}},
    }
    assert classify(result) == "timeout"
    assert classify({"verifier_result":{"rewards":{"reward":0}}}) == "incorrect"
    assert classify({}) == "not_run"


def test_startup_runs_before_analysis():
    plan = bench.build_plan("demo", ["pi","opencode"], {}, local=True)
    assert [c["task"] for c in plan["cells"][:2]] == ["startup","startup"]


def test_local_limits_reach_all_adapters():
    settings, registry = bench.read_config()
    settings.update(context_window=16384,max_output_tokens=2048,timeout_sec=300)
    for harness in ("pi","opencode","droid","dsh"):
        cell = {"harness":harness,"model":"lfm3:1.7b","task":"startup"}
        agent = bench.job_config(cell,"test",local=True,snapshot=(settings,registry))["agents"][0]
        assert agent["override_timeout_sec"] == 300
        if harness == "opencode":
            limits = agent["kwargs"]["opencode_config"]["provider"]["bench-local"]["models"]["lfm3:1.7b"]["limit"]
            assert limits == {"context":16384,"output":2048}
        else:
            assert agent["kwargs"]["local_context"] == 16384
            assert agent["kwargs"]["local_output"] == 2048


@pytest.mark.parametrize("failure", [RuntimeError("adapter failed"), KeyboardInterrupt()])
def test_notebook_returns_partial_campaign_after_failure(tmp_path, monkeypatch, failure):
    import sys
    sys.path.insert(0,str(bench.ROOT/"scripts"))
    import local_comparison
    import tqdm.auto

    bars = []
    class Bar:
        def __init__(self, **kwargs):
            self.closed = False
            self.count = 0
            bars.append(self)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.closed = True
        def set_postfix(self, **kwargs):
            pass
        def set_description(self, text):
            pass
        def update(self, count):
            self.count += count

    def fail(plan, progress, settings_override):
        assert settings_override["timeout_sec"] == 300
        progress("campaign", {"path":tmp_path, "total":plan["runs"]})
        raise failure

    monkeypatch.setattr(tqdm.auto,"tqdm",Bar)
    monkeypatch.setattr(bench,"execute",fail)
    result = local_comparison.run_comparison(
        "lfm3:1.7b",["pi"],timeout_sec=300
    )
    assert result == tmp_path
    assert bars[-1].closed
    assert bars[-1].count == 0


def test_percentage_plots_keep_zero_and_runtime_axes_separate():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from scripts.campaign_results import plot_results
    import matplotlib.pyplot as plt
    rows = [dict(harness="a", status="timeout", agent_seconds="180",
                 criteria_json=json.dumps({"mrr": False})),
            dict(harness="b", status="incorrect", agent_seconds="120",
                 criteria_json="{}")]
    figure = plot_results(rows)
    assert "0% (0/1)" in [t.get_text() for t in figure.axes[0].texts]
    assert figure.axes[0].get_xlim() == (0, 100)
    assert figure.axes[2].get_xlim()[1] > 180
    assert figure.axes[3].get_xlim()[1] < 10
    assert "N/A" in [t.get_text() for t in figure.axes[3].texts]
    plt.close(figure)
