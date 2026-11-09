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
    assert a['runs'] == 10 and a['reserved_eur'] == 10
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
    assert len(rows) == 2 and rows[1]['status']=='incomplete'
    assert all(r['cost_usd'] is None for r in rows)
    assert '1/2' in (campaign/'report.md').read_text()
