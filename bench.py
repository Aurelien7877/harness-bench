"""Small campaign planner around Harbor. Harbor executes and grades every trial."""
import argparse
import csv
import copy
import hashlib
import importlib.metadata
import json
import os
import random
import shutil
import signal
import queue
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from scripts.campaign_results import classify, summarize
from scripts.image import build_base_image as _build_base_image
from scripts.llm_proxy import Proxy, summarize_calls

ROOT = Path(__file__).resolve().parent


def _find_tools():
    """IDE-launched notebook kernels often lack Docker and Ollama on PATH; add the usual install folders."""
    if shutil.which('docker') and shutil.which('ollama'):
        return
    extra = [Path.home()/'.orbstack/bin', Path('/usr/local/bin'), Path('/opt/homebrew/bin'),
             Path('/Applications/Docker.app/Contents/Resources/bin')]
    known = os.environ.get('PATH', '').split(os.pathsep)
    os.environ['PATH'] = os.pathsep.join(known + [str(d) for d in extra if d.is_dir() and str(d) not in known])


_find_tools()
HARBOR = ROOT / '.venv/bin/harbor'
HARBOR_COMMAND = [str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/harbor_entry.py')]


def read_config():
    return tuple(tomllib.loads((ROOT / 'config' / f'{name}.toml').read_text()) for name in ('bench', 'harnesses'))


def runtime_versions():
    """Reject stale execution libraries before starting containers or inference."""
    pins = dict(line.split('==',1) for line in (ROOT/'requirements.lock').read_text().splitlines()
                if '==' in line and not line.startswith('#'))
    versions = {}
    for name in ('harbor','litellm','filelock'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
        if versions[name] != pins[name]:
            raise ValueError('Python execution dependencies are out of date. Run make setup-python before starting a campaign.')
    return versions


def folder_bytes(directory=ROOT):
    size = 0
    for parent, _, names in os.walk(directory):
        for name in names:
            try:
                size += os.lstat(os.path.join(parent, name)).st_size
            except FileNotFoundError:
                continue
    return size


def runtime_env(credential_names=()):
    # Only deliberate provider credentials may reach Harbor. Isolate personal logins.
    allowed = {'PATH', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LC_CTYPE',
               'SYSTEMROOT', 'WINDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
               'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY',
               'DOCKER_CERT_PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
               'http_proxy', 'https_proxy', 'no_proxy'}
    env = {k:v for k,v in os.environ.items() if k in allowed or k in credential_names}
    home = ROOT / '.home'
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home/'.config'),
               XDG_CACHE_HOME=str(ROOT/'.cache'), PYTHONPATH=str(ROOT),
               LITELLM_LOCAL_MODEL_COST_MAP='True')
    # Docker discovery stays on the host; this directory is never mounted into trials.
    env.setdefault('DOCKER_CONFIG', str(Path.home()/'.docker'))
    env['PATH'] = str(ROOT / '.venv/bin') + os.pathsep + env.get('PATH', '')
    # Preserve the socket location, not the user's Docker configuration/secrets.
    if 'DOCKER_HOST' not in env:
        socket = Path.home() / '.orbstack/run/docker.sock'
        if socket.exists():
            env['DOCKER_HOST'] = 'unix://' + str(socket)
    return env


def parse_models(items):
    result = {}
    for item in items or []:
        key, sep, value = item.partition('=')
        if not sep or not key or not value:
            raise ValueError('Use --model harness=provider/model')
        if key in result:
            raise ValueError(f'Duplicate model for {key}')
        result[key] = value
    return result


def read_json_object(path):
    """Partial files remain diagnosable instead of destroying the whole report."""
    try:
        value = path.read_text()
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError('Expected a JSON object')
        return result
    except (OSError, ValueError) as error:
        return {'exception_info': {'exception_type':'InvalidResultFile',
                                  'exception_message':type(error).__name__}}


def write_manifest(campaign, manifest):
    path = campaign/'manifest.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, indent=2))
    temporary.replace(path)


def build_plan(suite, harnesses, models, attempts=1, *, local=False):
    settings, registry = read_config()
    if attempts < 1:
        raise ValueError('attempts must be positive')
    if suite not in settings['suites']:
        raise ValueError(f'Unknown suite {suite}')
    if not harnesses or len(set(harnesses)) != len(harnesses):
        raise ValueError('Choose distinct harness names')
    for name in harnesses:
        if name not in registry and name not in ('oracle', 'nop'):
            raise ValueError(f'Unknown harness: {name}')
    unknown_models = set(models) - set(harnesses)
    if unknown_models:
        raise ValueError(f'Model supplied for unselected harness: {unknown_models}')
    cells = [{'harness': h, 'model': models.get(h), 'task': t, 'attempt': k}
             for k in range(attempts) for t in settings['suites'][suite] for h in harnesses]
    random.Random(settings['seed']).shuffle(cells)
    cells.sort(key=lambda cell: not cell['task'].startswith('startup'))
    paid = sum(c['harness'] not in ('oracle', 'nop') for c in cells)
    if local and any(h not in ('pi', 'opencode', 'droid', 'dsh', 'droid-tuned', 'bare') for h in harnesses):
        raise ValueError('Local inference supports pi, opencode, droid, droid-tuned, dsh and bare')
    if local and any(not c['model'] for c in cells):
        raise ValueError('Local inference requires an explicit model for every harness')
    if local and len({c['model'] for c in cells}) != 1:
        raise ValueError('A local campaign compares the same model tag across harnesses')
    reserved = 0 if local else paid * settings['reserve_eur_per_trial']
    if reserved > settings['budget_eur']:
        raise ValueError(f'{len(cells)} runs reserve EUR {reserved:.2f}, above EUR {settings["budget_eur"]:.2f}; reduce tasks/harnesses/attempts')
    return {'local': local, 'suite': suite, 'seed': settings['seed'], 'runs': len(cells), 'reserved_eur': reserved,
            'campaign_limit_eur': settings['budget_eur'], 'budget_kind': 'planning reserve; provider hard cap required', 'cells': cells}


def job_config(cell, name, install_only=False, snapshot=None, *, local=False, port=None):
    settings, registry = snapshot or read_config()
    h = cell['harness']
    if h in ('oracle', 'nop'):
        agent = {'name': h}
    else:
        entry = registry[h]
        profile = entry.get('profile')
        options = entry.get('options', {})
        h = entry.get('base', h)  # a tuned variant behaves like its base harness
        agent = {'model_name': cell['model'], 'kwargs': {'version': entry['version'], **options},
                 'override_timeout_sec': settings['timeout_sec'],
                 'env': {k: '${' + k + '}' for k in entry['credential_env'] if os.environ.get(k)}}
        agent.update({'import_path': entry['import_path']} if 'import_path' in entry else {'name': entry['agent']})
        if h == 'claude':
            agent['kwargs'].update(max_turns=12, max_budget_usd='1.00')
        if h == 'pi':
            agent['kwargs']['max_turns'] = 12
        if h == 'dsh':
            agent['env']['DSH_TELEMETRY_DISABLED'] = '1'
    if local:
        context = settings.get('context_window',32768)
        output = settings.get('max_output_tokens',8192)
        port = port or settings.get('llm_proxy_port',11434)
        agent['env'] = {'BENCH_LOCAL_KEY': 'ollama'}
        if h == 'bare':
            agent.update(model_name=cell['model'], skip_model_parsing=True)
            agent['kwargs'].update(local_model=cell['model'], local_output=output, local_port=port)
        elif h in ('droid', 'dsh'):
            agent['skip_model_parsing'] = True
            agent['kwargs'].update(local_model=cell['model'], local_context=context, local_output=output, local_port=port)
            if profile:
                agent['kwargs']['profile'] = str(ROOT / profile)
            agent['model_name'] = (
                'custom:' + cell['model'] + '-0'
                if h == 'droid' else 'bench-ollama/' + cell['model']
            )
            if h == 'dsh':
                agent['env']['DSH_TELEMETRY_DISABLED'] = '1'
        else:
            provider = 'bench-local' if h == 'opencode' else 'openai'
            agent.update(
                model_name=provider + '/' + cell['model'],
                skip_model_parsing=(h == 'opencode'),
                base_url=f'http://host.docker.internal:{port}/v1',
                model_api_format='openai_chat_completions',
                model_api_key_name='BENCH_LOCAL_KEY',
            )
        if h == 'pi':
            agent.pop('name',None)
            agent['import_path'] = 'adapters.local_pi:LocalPi'
            agent['kwargs'].update(local_context=context, local_output=output, local_port=port)
        if h == 'opencode':
            agent.pop('name',None)
            agent['import_path'] = 'adapters.local_opencode:LocalOpenCode'
            agent['kwargs']['opencode_config'] = {
                'provider': {'bench-local': {'models': {cell['model']: {
                    'limit': {'context':context, 'output':output},
                }}}},
            }
    return {'job_name': name, 'jobs_dir': str(ROOT / 'runs/jobs'), 'n_attempts': 1,
            'n_concurrent_trials': 1, 'retry': {'max_retries': 0},
            'install_only': install_only, 'skip_credential_checks': install_only,
            'environment': {'type': 'docker', 'delete': True},
            'agents': [agent], 'tasks': [{'path': str(ROOT / 'tasks' / cell['task'])}],
            'artifacts': [] if install_only else ['/workspace']}


def validate():
    from harbor.models.job.config import JobConfig
    from harbor.models.task.task import Task
    from harbor.agents.factory import AgentFactory
    settings, registry = read_config()
    for task in (ROOT / 'tasks').iterdir():
        Task(task)
    for h in [*registry, 'oracle', 'nop']:
        config = JobConfig.model_validate(job_config({'harness':h, 'model':'anthropic/claude-sonnet-4-5', 'task':'humaneval-0'}, 'validation'))
        AgentFactory.get_agent_class_from_config(config.agents[0])
    for tasks in settings['suites'].values():
        for task in tasks:
            if not (ROOT / 'tasks' / task).is_dir():
                raise ValueError(f'Missing task {task}')
    print(f'Valid: {len(registry)} harness configurations, {len(list((ROOT / "tasks").iterdir()))} tasks; Harbor {importlib.metadata.version("harbor")}')


def doctor():
    validate()
    settings, registry = read_config()
    size = folder_bytes()/1e9
    print(f'Folder: {size:.3f} GB / {settings["max_folder_gb"]} GB (decimal; no local model weights)')
    result = subprocess.run(['docker','info','--format','{{.ServerVersion}}'], capture_output=True, text=True, env=runtime_env(), timeout=15)
    print('Docker: ' + (result.stdout.strip() if result.returncode == 0 else 'unavailable; start OrbStack/Docker'))
    for h, entry in registry.items():
        available = [k for k in entry['credential_env'] if os.environ.get(k)]
        print(f'{h}: pinned {entry["version"]}; credential variable present: {", ".join(available) or "none"}')
    print('Docker images live outside this folder. Inspect `docker system df`; no global prune is performed.')
    return 0 if result.returncode == 0 and size < settings['stop_folder_gb'] else 1


def report(campaign):
    manifest = json.loads((campaign / 'manifest.json').read_text())
    rows = []
    for cell in manifest['cells']:
        files = sorted((ROOT / 'runs/jobs' / cell['job']).glob('*/result.json'))
        result = read_json_object(files[0]) if files else {}
        if len(files) > 1:
            result = {'exception_info': {'exception_type':'AmbiguousResults',
                                        'exception_message':'Multiple trial results for one scheduled cell'}}
        if not result and cell.get('returncode'):
            result = {'exception_info': {'exception_type':'LauncherError',
                                        'exception_message':f"Harbor exited {cell['returncode']} without a result"}}
        usage = result.get('agent_result') or {}
        rewards = (result.get('verifier_result') or {}).get('rewards') or {}
        error = result.get('exception_info') or {}
        timing = result.get('agent_execution') or {}
        elapsed = None
        if timing.get('started_at') and timing.get('finished_at'):
            elapsed = (datetime.fromisoformat(timing['finished_at']) - datetime.fromisoformat(timing['started_at'])).total_seconds()
        task_meta = tomllib.loads((ROOT/'tasks'/cell['task']/'task.toml').read_text()).get('metadata', {}) if (ROOT/'tasks'/cell['task']/'task.toml').exists() else {}
        status = classify(result, installed=manifest.get('install_only',False),
                          started=bool(cell.get('started_at')) or (ROOT/'runs/jobs'/cell['job']).exists())
        criteria = {}
        if files:
            diagnostic = files[0].parent/'verifier/criteria.json'
            if diagnostic.exists():
                criteria = read_json_object(diagnostic).get('checks',{})
        script = None
        if files:
            workspace = files[0].parent/'artifacts/workspace'
            if workspace.exists():
                script = (workspace/'analyze.py').is_file()
        started = timing.get('started_at')
        calls = summarize_calls(campaign/(cell['job']+'.calls.jsonl'),
                                datetime.fromisoformat(started).timestamp() if started else None) or {}
        reported = [usage.get('n_input_tokens'), usage.get('n_output_tokens')]
        proxied = [calls.get('proxy_input_tokens'), calls.get('proxy_output_tokens')]
        source = ('harness' if None not in reported else None if None in proxied else
                  'proxy' if calls.get('proxy_usage_complete') else 'proxy_partial')
        rows.append({**{k:cell[k] for k in ('harness','model','task','attempt')},
                     'category': cell.get('category', task_meta.get('category')), 'version': (result.get('agent_info') or {}).get('version'),
                     'agent_seconds': elapsed,
                     'status': status, 'error_type':error.get('exception_type'),
                     'error_message':error.get('exception_message'),
                     'script_present':script, 'criteria_json':json.dumps(criteria),
                     'logs':str(files[0].parent) if files else '',
                     'reward': rewards.get('reward'),
                     'cost_usd': usage.get('cost_usd'),
                     'input_tokens': reported[0] if source == 'harness' else proxied[0] if source else None,
                     'cached_input_tokens': usage.get('n_cache_tokens'),
                     'output_tokens': reported[1] if source == 'harness' else proxied[1] if source else None,
                     'tokens_source': source,
                     **{key: calls.get(key) for key in ('llm_calls','tool_calls','first_call_seconds','call_latency_median','ttft_median','llm_seconds')},
                     'result': str(files[0]) if files else ''})
    with (campaign / 'results.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['status'])
        writer.writeheader(); writer.writerows(rows)
    if manifest.get('install_only'):
        lines = ['# Installation checks', '', 'No model calls. Installation success does not establish successful paid execution.', '', '| Harness | Status | Reported version |', '|---|---|---|']
        lines += [f'| {r["harness"]} | {r["status"]} | {r["version"] or "unknown"} |' for r in rows]
        (campaign/'report.md').write_text('\n'.join(lines)+'\n')
        return rows
    lines = ['# Campaign results', '',
             'Startup is a separate health check. Work success includes all scheduled work trials, including failures and unfinished trials.',
             '95% Wilson intervals describe this small sample. Tasks are handpicked, and repeated attempts are not independent evidence of general ability.',
             'Missing measurements stay unknown. Known costs are partial when coverage is incomplete; USD is not converted to EUR.', '',
             '| Harness | Model | Work passed / scheduled | Success | 95% interval | Startup | Median agent seconds |',
             '|---|---|---:|---:|---:|---:|---:|']
    summaries = summarize(rows)
    def text(value, digits=1):
        return 'unknown' if value is None else f'{value:.{digits}f}'
    for summary in summaries:
        s = summary
        interval = 'N/A' if s['success_ci_low'] is None else f"{s['success_ci_low']:.1f}% to {s['success_ci_high']:.1f}%"
        rate = 'N/A' if s['success_rate'] is None else f"{s['success_rate']:.1f}%"
        lines.append(f"| {s['harness']} | {s['model']} | {s['passed']}/{s['scored']} | {rate} | {interval} | {s['startup_passed']}/{s['startup_scheduled']} | {text(s['median_seconds'])} ({s['time_observations']} measured) |")
    lines += ['', '| Harness | Model | Category | Passed / scheduled |', '|---|---|---|---:|']
    for h, model, category in sorted({(r['harness'],r['model'] or 'unknown',r['category'] or 'unknown') for r in rows}):
        group = [r for r in rows if r['harness']==h and (r['model'] or 'unknown')==model and (r['category'] or 'unknown')==category]
        lines.append(f'| {h} | {model} | {category} | {sum(r["status"]=="passed" for r in group)}/{len(group)} |')
    lines += ['', '| Harness | Model | Incorrect | Timeout | Technical error | Not run / incomplete |',
              '|---|---|---:|---:|---:|---:|']
    for s in summaries:
        counts = s['outcomes']
        def rate(statuses):
            count = sum(counts.get(status,0) for status in statuses)
            return f"{count}/{s['scored']} ({100*count/s['scored']:.1f}%)" if s['scored'] else 'N/A'
        lines.append('| '+s['harness']+' | '+s['model']+' | '+' | '.join([
            rate(['incorrect']),rate(['timeout']),rate(['technical_error']),rate(['not_run','incomplete'])])+' |')
    lines += ['', '| Harness | Model | Known cost USD | Cost coverage | Input tokens | Output tokens |',
              '|---|---|---:|---:|---:|---:|']
    for s in summaries:
        lines.append(f"| {s['harness']} | {s['model']} | {text(s['known_cost_usd'],4)} | {s['cost_observations']}/{s['scheduled']} | {text(s['input_tokens'],0)} ({s['input_tokens_observations']}/{s['scheduled']}) | {text(s['output_tokens'],0)} ({s['output_tokens_observations']}/{s['scheduled']}) |")
    lines += ['', '| Harness | Model | LLM calls (median) | Tool calls (median) | Time to first call s | Call latency s | TTFT s | Output tokens/s |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        lines.append(f"| {s['harness']} | {s['model']} | {text(s['llm_calls_median'],0)} | {text(s['tool_calls_median'],0)} | {text(s['first_call_median'])} | {text(s['latency_median'],2)} | {text(s['ttft_median'],2)} | {text(s['tokens_per_second'])} |")
    lines += ['', 'Call metrics come from a local logging proxy and are unknown when no call was recorded. Time to first call includes harness start-up inside the agent phase.',
              '', 'No overall winner is declared. Compare the same tasks, model weights, limits and hardware, then inspect the saved programs and logs.']
    (campaign / 'report.md').write_text('\n'.join(lines)+'\n')
    return rows


def is_cloud(tag):
    """Ollama cloud models carry a `cloud` suffix and run through the signed-in local daemon."""
    return bool(tag) and tag.endswith(('-cloud', ':cloud'))


def cloud_check(tag):
    """One-token request that proves sign-in, model name and quota before a campaign starts."""
    request = urllib.request.Request('http://127.0.0.1:11434/api/chat', method='POST', data=json.dumps({
        'model': tag, 'messages': [{'role': 'user', 'content': 'ok'}], 'stream': False,
        'options': {'num_predict': 1}}).encode())
    try:
        urllib.request.urlopen(request, timeout=120).read()
    except urllib.error.HTTPError as error:
        raise ValueError(f'Ollama refused {tag} (HTTP {error.code}). Run `ollama signin`, check the model name '
                         f'at https://ollama.com/search?c=cloud and your plan. {error.read()[:200].decode(errors="replace")}')
    except OSError as error:
        raise ValueError(f'Ollama is not reachable at 127.0.0.1:11434 ({error}). Start Ollama first.')


def load_env_file(path=None):
    """Read KEY=value lines from .env into this process only; Harbor and the containers never inherit them."""
    try:
        lines = (path or ROOT/'.env').read_text().splitlines()
    except OSError:
        return
    for line in lines:
        name, _, value = line.partition('=')
        if name.strip() and not name.lstrip().startswith('#') and value:
            os.environ.setdefault(name.strip(), value.strip().strip('"\''))


def remote_provider(settings, name, workers=1):
    """Connection settings for an API provider from config/bench.toml; the key comes from the environment."""
    config = settings.get('providers', {}).get(name)
    if not config:
        raise ValueError(f'Unknown provider {name!r}; add [providers.{name}] to config/bench.toml.')
    load_env_file()
    key = os.environ.get(config['key_env'])
    if not key:
        raise ValueError(f'Set {config["key_env"]} in the environment or in .env (it is git-ignored).')
    # Spacing is per proxy and each worker has its own, so scale it to keep the provider's total rate.
    return dict(host=config['host'], key=key, path_from=config['path_from'], path_to=config['path_to'],
                min_interval=config.get('min_interval', 0) * workers,
                drop_fields=config.get('drop_fields', [])), config


def provider_check(remote, tag):
    """One-token request proving the key, the model name and the free quota before a campaign starts."""
    request = urllib.request.Request(f'https://{remote["host"]}{remote["path_to"]}/chat/completions', method='POST',
                                     headers={'Authorization': 'Bearer ' + remote['key'], 'Content-Type': 'application/json'},
                                     data=json.dumps({'model': tag, 'messages': [{'role': 'user', 'content': 'ok'}], 'max_tokens': 5}).encode())
    try:
        urllib.request.urlopen(request, timeout=120).read()
    except urllib.error.HTTPError as error:
        detail = error.read()[:300].decode(errors='replace').replace(remote['key'], '***')
        raise ValueError(f'{remote["host"]} refused {tag} (HTTP {error.code}): {detail}')
    except OSError as error:
        raise ValueError(f'Could not reach {remote["host"]}: {error}')


def build_base_image(force=False):
    """Shared task image with every pinned agent CLI preinstalled; rebuilt only when versions change."""
    return _build_base_image(read_config()[1], force=force, env=runtime_env())


def warm_up(tag):
    """Load the model once so the first trial does not pay the weight-loading time."""
    request = urllib.request.Request('http://127.0.0.1:11434/api/generate', method='POST',
                                     data=json.dumps({'model': tag, 'prompt': 'ok', 'stream': False,
                                                      'options': {'num_predict': 1}, 'keep_alive': '30m'}).encode())
    try:
        urllib.request.urlopen(request, timeout=300).read()
    except OSError:
        pass  # warm-up is an optimisation; the campaign itself will report real errors


def execute(plan, provider_cap=None, install_only=False, progress=None, settings_override=None, resume=None, concurrency=None, provider=None):
    settings, registry = read_config()
    settings.update(settings_override or {})
    if resume:
        # Continue with the exact settings and harness versions the campaign started with.
        saved = json.loads((Path(resume)/'manifest.json').read_text())
        plan = saved
        provider = saved.get('provider')
        settings, registry = saved['configuration_snapshot']['settings'], saved['configuration_snapshot']['harnesses']
    if settings['timeout_sec'] <= 0 or not 0 < settings['max_output_tokens'] < settings['context_window']:
        raise ValueError('Use a positive timeout and output tokens below the context window.')
    paid = plan['reserved_eur'] > 0 and not install_only
    if paid:
        if provider_cap is None or not 0 < provider_cap <= settings['budget_eur']:
            raise ValueError('Paid run blocked: configure a hard provider budget first, then supply --provider-cap-eur (total across providers, <=20). This flag is an attestation, not a billing API.')
        for cell in plan['cells']:
            h = cell['harness']
            if h in registry and (not cell['model'] or not any(os.environ.get(k) for k in registry[h]['credential_env'])):
                raise ValueError(f'{h}: explicit model and a dedicated API credential are required')
            if h == 'dsh':
                from adapters.command import DSH
                DSH.model_patch(cell['model'])
    versions = runtime_versions()
    initial_bytes = folder_bytes()
    if initial_bytes/1e9 >= settings['stop_folder_gb']:
        raise ValueError('Folder near storage limit; archive your runs before continuing')
    cloud = bool(plan.get('local')) and is_cloud(plan['cells'][0]['model'])
    remote_config = {}
    if plan.get('local') and provider:
        workers_hint = int(concurrency or plan.get('concurrency') or settings.get('providers', {}).get(provider, {}).get('concurrency', 1))
        remote, remote_config = remote_provider(settings, provider, workers_hint)
        provider_check(remote, plan['cells'][0]['model'])
        plan['ollama_digest'], plan['ollama_runtime'] = None, {}
    elif plan.get('local') and cloud:
        cloud_check(plan['cells'][0]['model'])
        plan['ollama_digest'], plan['ollama_runtime'] = None, {}
    elif plan.get('local'):
        # /api/tags includes the digest of the locally installed weights.
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            installed = json.load(response)['models']
        tag = plan['cells'][0]['model']
        record = next((m for m in installed if m['name'] == tag), None)
        if not record or not record.get('size') or record.get('remote_host'):
            raise ValueError(f'Pull a local Ollama model first: ollama pull {tag}')
        if resume and plan.get('ollama_digest') != record['digest']:
            raise ValueError('The installed model differs from the one this campaign started with; start a new campaign.')
        plan['ollama_digest'] = record['digest']
        plan['ollama_runtime'] = {}
        for endpoint in ('version','ps'):
            try:
                with urllib.request.urlopen('http://127.0.0.1:11434/api/'+endpoint,timeout=5) as response:
                    plan['ollama_runtime'][endpoint] = json.load(response)
            except OSError:
                plan['ollama_runtime'][endpoint] = None
        warm_up(tag)
    if plan.get('local'):
        build_base_image()
    default = remote_config.get('concurrency') if provider else (settings.get('cloud_concurrency', 3) if cloud else 1)
    workers = max(1, int(concurrency or plan.get('concurrency') or default or 1))
    plan['concurrency'], plan['provider'] = workers, provider
    plan['model_source'] = provider or ('cloud' if cloud else 'local')
    if provider:
        remote, remote_config = remote_provider(settings, provider, workers)
    if resume:
        campaign, manifest = Path(resume), plan
        manifest['state'] = 'running'
        manifest['resumed_at'] = datetime.now(timezone.utc).isoformat()
        for relative, digest in manifest['task_file_hashes'].items():
            if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != digest:
                raise ValueError('A task changed since this campaign started; start a new campaign.')
        write_manifest(campaign, manifest)
        if progress:
            progress('campaign', {'path': campaign, 'total': len(manifest['cells'])})
    else:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        campaign = ROOT / 'runs/campaigns' / stamp
        campaign.mkdir(parents=True)
        manifest = dict(copy.deepcopy(plan), state='running', harbor_version=versions['harbor'], runtime_versions=versions, provider_cap_attested_eur=provider_cap, install_only=install_only)
        manifest['configuration_snapshot'] = {'settings':settings, 'harnesses':registry}
        manifest['task_file_hashes'] = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in {c['task'] for c in manifest['cells']}
            for p in (ROOT/'tasks'/name).rglob('*') if p.is_file()
        }
        image = subprocess.run(['docker','image','inspect','harness-bench-base:1','--format','{{.Id}}'], capture_output=True, text=True, timeout=15, env=runtime_env())
        manifest['base_image_id'] = image.stdout.strip() if image.returncode == 0 else None
        for i, cell in enumerate(manifest['cells']):
            cell['job'] = f'{stamp}-{i:03}-{cell["harness"]}'
            metadata = tomllib.loads((ROOT/'tasks'/cell['task']/'task.toml').read_text()).get('metadata',{})
            cell['category'] = metadata.get('category')
        manifest['config_hashes'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'config').glob('*.toml')}
        write_manifest(campaign, manifest)
        if progress:
            progress('campaign', {'path': campaign, 'total': len(manifest['cells'])})
    static_bytes = initial_bytes - folder_bytes(ROOT/'runs')
    local = bool(plan.get('local'))
    ports = [settings['llm_proxy_port'] + i for i in range(workers)]
    # One proxy per worker keeps every model call attributed to its own trial. Cloud queues can reject, so retry there.
    proxies = [Proxy(port, retries=remote_config.get('retries', 6) if provider else 3 if cloud else 0,
                     remote=remote if provider else None).start() for port in ports] if local else []
    slots = queue.Queue()
    for i in range(workers):
        slots.put(i)
    lock = threading.RLock()  # guards the manifest, the report, the progress callback and the breaker
    stop = threading.Event()
    broken = Counter()

    def run_cell(cell, slot):
        for relative, digest in manifest['task_file_hashes'].items():
            if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != digest:
                raise RuntimeError('A task changed during the campaign; stopping to preserve comparability')
        jobdir = ROOT/'runs/jobs'/cell['job']
        if resume and cell.get('finished_at'):
            previous = list(jobdir.glob('*/result.json'))
            outcome = classify(read_json_object(previous[0]), started=True) if previous else None
            if outcome in ('passed','incorrect','timeout'):
                if progress:
                    with lock:
                        progress('trial_end', dict(cell, result=read_json_object(previous[0]), returncode=cell.get('returncode')))
                return
        if jobdir.exists():
            # Keep the earlier attempt's files; the retry gets a clean job folder.
            archive = ROOT/'runs/jobs/_retried'; archive.mkdir(exist_ok=True)
            jobdir.rename(archive/(cell['job']+'-'+datetime.now(timezone.utc).strftime('%H%M%S')))
        with lock:
            skipped = local and broken[cell['harness']] >= 3
            if skipped:
                cell['skipped'] = 'three consecutive technical errors for this harness'
                write_manifest(campaign, manifest)
                if progress:
                    progress('trial_end', dict(cell, result={}, returncode=None))
        if skipped:
            return
        config = job_config(cell, cell['job'], install_only, snapshot=(settings, registry), local=local, port=ports[slot])
        path = campaign / (cell['job']+'.json')
        path.write_text(json.dumps(config, indent=2))
        with lock:
            cell['started_at'] = datetime.now(timezone.utc).isoformat()
            write_manifest(campaign, manifest)
            if progress:
                progress('trial_start', cell)
            else:
                print(f'{cell["harness"]}: {cell["task"]}', flush=True)
        if proxies:
            proxies[slot].log_to(campaign/(cell['job']+'.calls.jsonl'))
        with (campaign / (cell['job']+'.log')).open('w') as log:
            credential_names = () if local or install_only else registry.get(cell['harness'],{}).get('credential_env',())
            process = subprocess.Popen([*HARBOR_COMMAND,'run','-c',str(path)], env=runtime_env(credential_names), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while process.poll() is None:
                    if stop.is_set():
                        raise InterruptedError('Campaign stopped')
                    if (static_bytes + folder_bytes(ROOT/'runs'))/1e9 >= settings['stop_folder_gb']:
                        raise RuntimeError('Storage guard reached; stopping campaign')
                    if progress:
                        native = list((ROOT/'runs/jobs'/cell['job']).glob('*/agent/*.jsonl'))
                        native += list((ROOT/'runs/jobs'/cell['job']).glob('*/agent/*.txt'))
                        active = [p for p in native if p.stat().st_size]
                        idle = min((time.time()-p.stat().st_mtime for p in active), default=None)
                        event = None
                        if active:
                            last = max(active,key=lambda p:p.stat().st_mtime)
                            with last.open('rb') as stream:
                                stream.seek(max(0,last.stat().st_size-4096))
                                for line in reversed(stream.read().decode(errors='replace').splitlines()):
                                    try:
                                        event = json.loads(line).get('type')
                                        break
                                    except (ValueError,AttributeError):
                                        continue
                        with lock:
                            progress('heartbeat', dict(cell,idle_seconds=idle,last_event=event))
                    time.sleep(2)
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        latest = list((ROOT/'runs/jobs'/cell['job']).glob('*/result.json'))
        result = read_json_object(latest[0]) if latest else {}
        with lock:
            cell['returncode'] = process.returncode
            cell['finished_at'] = datetime.now(timezone.utc).isoformat()
            if local and not cloud and not provider:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:11434/api/ps',timeout=5) as response:
                        cell['ollama_runtime_after'] = json.load(response)
                except OSError:
                    cell['ollama_runtime_after'] = None
            write_manifest(campaign, manifest)
            broken[cell['harness']] = broken[cell['harness']]+1 if classify(result, started=True) == 'technical_error' else 0
            report(campaign)  # results.csv and report.md stay current after every trial
            if progress:
                progress('trial_end', dict(cell, result=result, returncode=process.returncode))
        if process.returncode and not local:
            raise RuntimeError(f'Harbor failed; see {log.name}')
        error = read_json_object(latest[0]).get('exception_info') if latest else None
        if not local and (not latest or error):
            raise RuntimeError('Trial infrastructure/agent error; campaign stopped to avoid wasting money')

    def worker(cell):
        if stop.is_set():
            return
        slot = slots.get()
        try:
            run_cell(cell, slot)
        finally:
            slots.put(slot)

    try:
        with ThreadPoolExecutor(workers) as pool:
            futures = [pool.submit(worker, cell) for cell in manifest['cells']]
            try:
                for future in as_completed(futures):
                    future.result()
            except BaseException:
                stop.set()  # running trials are interrupted and queued ones never start
                raise
    finally:
        for proxy in proxies:
            proxy.stop()
        manifest['state'] = 'interrupted' if sys.exc_info()[0] else 'finished'
        write_manifest(campaign, manifest)
        rows = report(campaign)
        print(f'Report: {campaign / "report.md"}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('doctor','validate'):
        sub.add_parser(name)
    for name in ('plan','run','install-check'):
        p = sub.add_parser(name)
        p.add_argument('--suite', default='smoke')
        p.add_argument('--harness', action='append', default=[])
        p.add_argument('--model', action='append', default=[])
        p.add_argument('--attempts', type=int, default=1)
        p.add_argument('--provider-cap-eur', type=float)
    p = sub.add_parser('local', help='Compare harnesses using a model installed in Ollama')
    p.add_argument('--suite', default='demo')
    p.add_argument('--harness', action='append')
    p.add_argument('--model', default='lfm3:1.7b')
    p.add_argument('--attempts', type=int, default=1)
    p.add_argument('--resume', type=Path, metavar='CAMPAIGN', help='Continue an interrupted campaign; finished trials are kept')
    p.add_argument('--concurrency', type=int, help='Trials run at once (default 1 locally, 3 for Ollama cloud models)')
    p.add_argument('--provider', help='Call an API provider from config/bench.toml (for example gemini) instead of local Ollama')
    p = sub.add_parser('report'); p.add_argument('campaign', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'doctor': return doctor()
        if args.command == 'validate': validate(); return 0
        if args.command == 'report': report(args.campaign); return 0
        if args.command == 'local':
            if args.resume:
                return execute(None, resume=args.resume, concurrency=args.concurrency)
            names = args.harness or ['pi', 'opencode']
            models = dict.fromkeys(names, args.model)
            return execute(build_plan(args.suite, names, models, args.attempts, local=True), concurrency=args.concurrency, provider=args.provider)
        plan = build_plan(args.suite, args.harness or ['oracle'], parse_models(args.model), args.attempts)
        if args.command == 'plan': print(json.dumps(plan, indent=2)); return 0
        if args.command == 'install-check':
            plan['cells'] = [next(c for c in plan['cells'] if c['harness']==h) for h in (args.harness or ['oracle'])]
            plan['runs'] = len(plan['cells'])
        return execute(plan, args.provider_cap_eur, args.command=='install-check')
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
