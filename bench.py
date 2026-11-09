"""Small campaign planner around Harbor. Harbor executes and grades every trial."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import random
import signal
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from scripts.campaign_results import classify

ROOT = Path(__file__).resolve().parent
HARBOR = ROOT / '.venv/bin/harbor'
HARBOR_COMMAND = [str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/harbor_entry.py')]


def read_config():
    return tuple(tomllib.loads((ROOT / 'config' / f'{name}.toml').read_text()) for name in ('bench', 'harnesses'))


def folder_bytes(directory=ROOT):
    size = 0
    for parent, _, names in os.walk(directory):
        for name in names:
            try:
                size += os.lstat(os.path.join(parent, name)).st_size
            except FileNotFoundError:
                continue
    return size


def runtime_env():
    # Keep normal Docker discovery. The entrypoint relocates only Harbor caches.
    env = dict(os.environ)
    env.update(PYTHONPATH=str(ROOT), LITELLM_LOCAL_MODEL_COST_MAP='True')
    for name in ('CODEX_AUTH_JSON_PATH', 'CODEX_FORCE_AUTH_JSON', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN'):
        env.pop(name, None)
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
    cells.sort(key=lambda cell: cell['task'] != 'startup')
    paid = sum(c['harness'] not in ('oracle', 'nop') for c in cells)
    if local and any(h not in ('pi', 'opencode', 'droid', 'dsh') for h in harnesses):
        raise ValueError('Local inference supports pi, opencode, droid and dsh')
    reserved = 0 if local else paid * settings['reserve_eur_per_trial']
    if reserved > settings['budget_eur']:
        raise ValueError(f'{len(cells)} runs reserve EUR {reserved:.2f}, above EUR {settings["budget_eur"]:.2f}; reduce tasks/harnesses/attempts')
    return {'local': local, 'suite': suite, 'seed': settings['seed'], 'runs': len(cells), 'reserved_eur': reserved,
            'campaign_limit_eur': settings['budget_eur'], 'budget_kind': 'planning reserve; provider hard cap required', 'cells': cells}


def job_config(cell, name, install_only=False, snapshot=None, *, local=False):
    settings, registry = snapshot or read_config()
    h = cell['harness']
    if h in ('oracle', 'nop'):
        agent = {'name': h}
    else:
        entry = registry[h]
        agent = {'model_name': cell['model'], 'kwargs': {'version': entry['version']},
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
        agent['env'] = {'BENCH_LOCAL_KEY': 'ollama'}
        if h in ('droid', 'dsh'):
            agent['skip_model_parsing'] = True
            agent['kwargs'].update(local_model=cell['model'], local_context=context, local_output=output)
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
                base_url='http://host.docker.internal:11434/v1',
                model_api_format='openai_chat_completions',
                model_api_key_name='BENCH_LOCAL_KEY',
            )
        if h == 'pi':
            agent.pop('name',None)
            agent['import_path'] = 'adapters.local_pi:LocalPi'
            agent['kwargs'].update(local_context=context, local_output=output)
        if h == 'opencode':
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
        files = list((ROOT / 'runs/jobs' / cell['job']).glob('*/result.json'))
        result = json.loads(files[0].read_text()) if files else {}
        usage = result.get('agent_result') or {}
        rewards = (result.get('verifier_result') or {}).get('rewards') or {}
        error = result.get('exception_info') or {}
        timing = result.get('agent_execution') or {}
        elapsed = None
        if timing.get('started_at') and timing.get('finished_at'):
            elapsed = (datetime.fromisoformat(timing['finished_at']) - datetime.fromisoformat(timing['started_at'])).total_seconds()
        task_meta = tomllib.loads((ROOT/'tasks'/cell['task']/'task.toml').read_text()).get('metadata', {}) if (ROOT/'tasks'/cell['task']/'task.toml').exists() else {}
        status = classify(result, installed=manifest.get('install_only',False),
                          started=(ROOT/'runs/jobs'/cell['job']).exists())
        criteria = {}
        if files:
            diagnostic = files[0].parent/'verifier/criteria.json'
            if diagnostic.exists():
                criteria = json.loads(diagnostic.read_text()).get('checks',{})
        script = None
        if files:
            workspace = files[0].parent/'artifacts/workspace'
            if workspace.exists():
                script = (workspace/'analyze.py').is_file()
        rows.append({**{k:cell[k] for k in ('harness','model','task','attempt')},
                     'category': task_meta.get('category'), 'version': (result.get('agent_info') or {}).get('version'),
                     'agent_seconds': elapsed,
                     'status': status, 'error_type':error.get('exception_type'),
                     'error_message':error.get('exception_message'),
                     'script_present':script, 'criteria_json':json.dumps(criteria),
                     'logs':str(files[0].parent) if files else '',
                     'reward': rewards.get('reward'),
                     'cost_usd': usage.get('cost_usd'), 'input_tokens': usage.get('n_input_tokens'),
                     'cached_input_tokens': usage.get('n_cache_tokens'), 'output_tokens': usage.get('n_output_tokens'),
                     'result': str(files[0]) if files else ''})
    with (campaign / 'results.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['status'])
        writer.writeheader(); writer.writerows(rows)
    if manifest.get('install_only'):
        lines = ['# Installation checks', '', 'No model calls. Installation success does not establish successful paid execution.', '', '| Harness | Status | Reported version |', '|---|---|---|']
        lines += [f'| {r["harness"]} | {r["status"]} | {r["version"] or "unknown"} |' for r in rows]
        (campaign/'report.md').write_text('\n'.join(lines)+'\n')
        return rows
    lines = ['# Campaign results', '', 'Missing costs are unknown, never zero. USD usage is not converted to EUR. Errors and incomplete trials remain in the denominator.', '', '| Harness | Passed / scheduled | Graded | Errors or incomplete | Known cost USD | Unknown cost trials |', '|---|---:|---:|---:|---:|---:|']
    for h in sorted({r['harness'] for r in rows}):
        group = [r for r in rows if r['harness']==h]
        costs = [r['cost_usd'] for r in group if r['cost_usd'] is not None]
        cost_text = f'{sum(costs):.4f}' if costs else 'unknown'
        lines.append(f'| {h} | {sum(r["reward"]==1 and r["status"] in ("passed","incorrect") for r in group)}/{len(group)} | {sum(r["status"] in ("passed","incorrect") for r in group)} | {sum(r["status"] not in ("passed","incorrect") for r in group)} | {cost_text} | {sum(r["cost_usd"] is None for r in group)} |')
    lines += ['', '| Harness | Category | Passed / scheduled |', '|---|---|---:|']
    for h, category in sorted({(r['harness'],r['category'] or 'unknown') for r in rows}):
        group = [r for r in rows if r['harness']==h and (r['category'] or 'unknown')==category]
        lines.append(f'| {h} | {category} | {sum(r["reward"]==1 and r["status"] in ("passed","incorrect") for r in group)}/{len(group)} |')
    lines += ['', '| Harness | Passed | Incorrect | Timeout | Technical error | Not run / incomplete |',
              '|---|---:|---:|---:|---:|---:|']
    for h in sorted({r['harness'] for r in rows}):
        group = [r for r in rows if r['harness']==h]
        counts = {status:sum(r['status']==status for r in group)
                  for status in ('passed','incorrect','timeout','technical_error','not_run','incomplete')}
        rates = [f"{100*counts[k]/len(group):.0f}%" for k in ('passed','incorrect','timeout','technical_error')]
        rates.append(f"{100*(counts['not_run']+counts['incomplete'])/len(group):.0f}%")
        lines.append('| '+h+' | '+' | '.join(rates)+' |')
    lines += ['', 'Small screening sample only. Do not infer a universal winner. Compare matched model configurations separately from native product configurations.']
    (campaign / 'report.md').write_text('\n'.join(lines)+'\n')
    return rows


def execute(plan, provider_cap=None, install_only=False, progress=None, settings_override=None):
    settings, registry = read_config()
    settings.update(settings_override or {})
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
    initial_bytes = folder_bytes()
    if initial_bytes/1e9 >= settings['stop_folder_gb']:
        raise ValueError('Folder near storage limit; archive your runs before continuing')
    if plan.get('local'):
        # /api/tags includes the digest of the locally installed weights.
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            installed = json.load(response)['models']
        tag = plan['cells'][0]['model']
        record = next((m for m in installed if m['name'] == tag), None)
        if not record or not record.get('size') or record.get('remote_host') or 'cloud' in tag.lower():
            raise ValueError(f'Pull a local Ollama model first: ollama pull {tag}')
        plan['ollama_digest'] = record['digest']
        plan['ollama_runtime'] = {}
        for endpoint in ('version','ps'):
            try:
                with urllib.request.urlopen('http://127.0.0.1:11434/api/'+endpoint,timeout=5) as response:
                    plan['ollama_runtime'][endpoint] = json.load(response)
            except OSError:
                plan['ollama_runtime'][endpoint] = None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    campaign = ROOT / 'runs/campaigns' / stamp
    campaign.mkdir(parents=True)
    manifest = dict(plan, harbor_version=importlib.metadata.version('harbor'), provider_cap_attested_eur=provider_cap, install_only=install_only)
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
    manifest['config_hashes'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'config').glob('*.toml')}
    (campaign / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    if progress:
        progress('campaign', {'path': campaign, 'total': len(manifest['cells'])})
    static_bytes = initial_bytes - folder_bytes(ROOT/'runs')
    manifest['state'] = 'running'
    try:
        for cell in manifest['cells']:
            for relative, digest in manifest['task_file_hashes'].items():
                if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != digest:
                    raise RuntimeError('A task changed during the campaign; stopping to preserve comparability')
            config = job_config(cell, cell['job'], install_only, snapshot=(settings, registry), local=plan.get('local', False))
            path = campaign / (cell['job']+'.json')
            path.write_text(json.dumps(config, indent=2))
            if progress:
                progress('trial_start', cell)
            else:
                print(f'{cell["harness"]}: {cell["task"]}', flush=True)
            with (campaign / (cell['job']+'.log')).open('w') as log:
                process = subprocess.Popen([*HARBOR_COMMAND,'run','-c',str(path)], env=runtime_env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    while process.poll() is None:
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
                            progress('heartbeat', dict(cell,idle_seconds=idle,last_event=event))
                        time.sleep(2)
                except BaseException:
                    os.killpg(process.pid, signal.SIGINT)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise
            latest = list((ROOT/'runs/jobs'/cell['job']).glob('*/result.json'))
            result = json.loads(latest[0].read_text()) if latest else {}
            if plan.get('local'):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:11434/api/ps',timeout=5) as response:
                        cell['ollama_runtime_after'] = json.load(response)
                except OSError:
                    cell['ollama_runtime_after'] = None
            manifest_path = campaign/'manifest.json'
            temporary = manifest_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(manifest,indent=2))
            temporary.replace(manifest_path)
            if progress:
                progress('trial_end', dict(cell, result=result, returncode=process.returncode))
            if process.returncode and not plan.get('local'):
                raise RuntimeError(f'Harbor failed; see {log.name}')
            latest = list((ROOT/'runs/jobs'/cell['job']).glob('*/result.json'))
            error = json.loads(latest[0].read_text()).get('exception_info') if latest else None
            if plan.get('local'):
                continue
            if not latest or error:
                raise RuntimeError('Trial infrastructure/agent error; campaign stopped to avoid wasting money')
    finally:
        manifest['state'] = 'interrupted' if sys.exc_info()[0] else 'finished'
        temporary = (campaign/'manifest.json').with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest,indent=2))
        temporary.replace(campaign/'manifest.json')
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
    p = sub.add_parser('report'); p.add_argument('campaign', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'doctor': return doctor()
        if args.command == 'validate': validate(); return 0
        if args.command == 'report': report(args.campaign); return 0
        if args.command == 'local':
            names = args.harness or ['pi', 'opencode']
            models = dict.fromkeys(names, args.model)
            return execute(build_plan(args.suite, names, models, args.attempts, local=True))
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
