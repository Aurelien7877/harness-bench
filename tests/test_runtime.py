"""Launcher checks use fake processes and HTTP responses, never a harness."""
import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import bench


def test_runtime_environment_isolates_accounts_and_unrelated_secrets(monkeypatch):
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN',
                'CODEX_AUTH_JSON_PATH', 'GITHUB_TOKEN', 'PRIVATE_DATABASE_PASSWORD'):
        monkeypatch.setenv(key, 'unused-test-value')
    local = bench.runtime_env()
    assert not any(key in local for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY',
                   'CLAUDE_CODE_OAUTH_TOKEN','CODEX_AUTH_JSON_PATH',
                   'GITHUB_TOKEN','PRIVATE_DATABASE_PASSWORD'))
    assert local['HOME'] == str(bench.ROOT/'.home')
    hosted = bench.runtime_env(['OPENAI_API_KEY'])
    assert hosted['OPENAI_API_KEY'] == 'unused-test-value'
    assert 'ANTHROPIC_API_KEY' not in hosted


def test_local_campaign_rejects_unmatched_or_missing_model():
    with pytest.raises(ValueError, match='same model'):
        bench.build_plan('demo',['pi','opencode'],{'pi':'one','opencode':'two'},local=True)
    with pytest.raises(ValueError, match='explicit model'):
        bench.build_plan('demo',['pi'],{},local=True)


def test_report_survives_corrupt_partial_result(tmp_path, monkeypatch):
    monkeypatch.setattr(bench,'ROOT',tmp_path)
    campaign = tmp_path/'campaign'
    campaign.mkdir()
    cell = dict(harness='pi',model='local',task='example',attempt=0,job='one')
    (campaign/'manifest.json').write_text(json.dumps({'cells':[cell]}))
    result = tmp_path/'runs/jobs/one/trial/result.json'
    result.parent.mkdir(parents=True)
    result.write_text('{')
    rows = bench.report(campaign)
    assert rows[0]['status'] == 'technical_error'
    assert rows[0]['error_type'] == 'InvalidResultFile'
    assert (campaign/'results.csv').exists()


def test_local_launcher_error_is_recorded_without_stopping_remaining_cells(tmp_path, monkeypatch):
    source = bench.ROOT
    shutil.copytree(source/'config',tmp_path/'config')
    shutil.copy(source/'requirements.lock',tmp_path/'requirements.lock')
    shutil.copytree(source/'tasks/startup',tmp_path/'tasks/startup')
    monkeypatch.setattr(bench,'ROOT',tmp_path)
    plan = bench.build_plan('demo',['pi'],{'pi':'test-local'},local=True)
    plan['cells'] = [c for c in plan['cells'] if c['task']=='startup']
    plan['cells'].append(dict(plan['cells'][0],attempt=1))
    plan['runs'] = 2
    original_cells = json.loads(json.dumps(plan['cells']))
    monkeypatch.setattr(bench.subprocess,'run',lambda *a,**kw: SimpleNamespace(returncode=0,stdout='test-image'))
    environments = []
    def fake_process(*args,**kwargs):
        environments.append(kwargs['env'])
        return SimpleNamespace(returncode=17,poll=lambda:17)
    monkeypatch.setattr(bench.subprocess,'Popen',fake_process)
    import urllib.request
    def fake_response(url,**kwargs):
        data = {'models':[{'name':'test-local','size':100,'digest':'fixture'}]}
        return io.BytesIO(json.dumps(data).encode())
    monkeypatch.setattr(urllib.request,'urlopen',fake_response)
    assert bench.execute(plan) == 0
    assert len(environments) == 2
    assert plan['cells'] == original_cells
    campaign = next((tmp_path/'runs/campaigns').iterdir())
    manifest = json.loads((campaign/'manifest.json').read_text())
    assert manifest['state'] == 'finished'
    assert all(c['returncode']==17 and c['started_at'] for c in manifest['cells'])
    assert all(row['status']=='technical_error' for row in bench.report(campaign))


def test_stale_runtime_is_rejected_before_any_campaign(monkeypatch):
    monkeypatch.setattr(bench.importlib.metadata,'version',lambda name:'outdated')
    with pytest.raises(ValueError,match='make setup-python'):
        bench.runtime_versions()


def test_notebook_updates_stale_dependencies_before_docker_setup(tmp_path, monkeypatch):
    import importlib.util
    import sys
    import urllib.request
    notebook = json.loads((bench.ROOT/'notebooks/local-comparison.ipynb').read_text())
    preparation = next(''.join(c['source']) for c in notebook['cells']
                       if c['cell_type']=='code' and 'docker", "info' in ''.join(c['source']))
    calls = []
    checks = []
    def versions():
        checks.append(True)
        if len(checks)==1:
            raise ValueError('stale')
        return {}
    monkeypatch.setattr(importlib.util,'find_spec',lambda name:SimpleNamespace())
    monkeypatch.setattr(shutil,'which',lambda name:'uv')
    def fake_run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(bench.subprocess,'run',fake_run)
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'{"models":[{"name":"fixture"}]}'))
    exec(compile(preparation,'notebook preparation','exec'),
         dict(run_new_campaign=True,bench=SimpleNamespace(runtime_versions=versions),
              root=tmp_path,model='fixture',sys=sys))
    assert len(checks)==2
    assert calls[0][-2:]==['-r',str(tmp_path/'requirements.lock')]
    assert calls[1]==['docker','info']
