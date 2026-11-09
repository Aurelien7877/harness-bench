"""Thin adapters for CLIs not present in the pinned Harbor release.

Harbor owns environments, timeouts, verification and result storage.
No personal home directory or subscription credentials are mounted.
"""
import json
import shlex

from harbor.agents.base import BaseAgent


class CommandAgent(BaseAgent):
    package = ""
    binary = ""

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.pin = version
        self.detected_version = None

    def version(self):
        return self.detected_version or self.pin

    async def checked(self, environment, command, **kwargs):
        result = await environment.exec(command=command, **kwargs)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with (self.logs_dir/'setup.log').open('a') as log:
            log.write(command + '\n' + (result.stdout or '') + '\n' + (result.stderr or '') + '\n')
        if result.return_code != 0:
            raise RuntimeError(f"{self.name()} command failed ({result.return_code}): {((result.stdout or '') + (result.stderr or ''))[-2000:]}")
        return result

    async def setup(self, environment):
        spec = shlex.quote(f"{self.package}@{self.pin}")
        await self.checked(environment, f"npm install -g {spec}", timeout_sec=300)
        result = await self.checked(environment, f"{self.binary} --version", timeout_sec=30)
        self.detected_version = (result.stdout or "").strip()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "version.txt").write_text(self.detected_version)

    async def prepare(self, environment):
        pass

    def argv(self):
        raise NotImplementedError

    async def run(self, instruction, environment, context):
        if not self.model_name:
            raise ValueError("An explicit model is required")
        await self.prepare(environment)
        prompt = self.logs_dir / "prompt.txt"
        prompt.write_text(instruction)
        await environment.upload_file(source_path=prompt, target_path="/tmp/bench-prompt.txt")
        command = shlex.join(self.argv())
        result = await environment.exec(
            command=f"cd /workspace && {command} < /tmp/bench-prompt.txt > /logs/agent/native.jsonl 2> /logs/agent/native.stderr",
            env=self._extra_env,
        )
        context.metadata = {"usage_status": "unknown", "adapter": type(self).__name__}
        raw = self.logs_dir / "native.jsonl"
        await environment.download_file(source_path="/logs/agent/native.jsonl", target_path=raw)
        usage = parse_usage(raw.read_text(), self.name())
        for key, value in usage.items():
            setattr(context, key, value)
        if usage:
            context.metadata['usage_status'] = 'reported_by_harness'
        # Unknown usage stays null. Never estimate missing usage as zero.
        if result.return_code != 0:
            raise RuntimeError(f"{self.name()} exited {result.return_code}; see native.stderr")


def parse_usage(text, kind):
    """Only consume documented terminal events, never nested tool output."""
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except ValueError:
            pass
    if kind == 'droid':
        finals = [e for e in events if e.get('type') == 'result' and isinstance(e.get('usage'), dict)]
        if not finals:
            return {}
        event = finals[-1]
        usage = event['usage']
        result = {}
        if 'input_tokens' in usage:
            result['n_input_tokens'] = usage['input_tokens'] + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0)
        if 'output_tokens' in usage:
            result['n_output_tokens'] = usage['output_tokens']
        if 'cache_read_input_tokens' in usage:
            result['n_cache_tokens'] = usage['cache_read_input_tokens']
        if isinstance(event.get('total_cost_usd'), (int,float)):
            result['cost_usd'] = event['total_cost_usd']
        return result
    if kind == 'omp':
        messages = [e.get('message', {}) for e in events if e.get('type') == 'message_end']
        usages = [m['usage'] for m in messages if m.get('role') == 'assistant' and isinstance(m.get('usage'), dict)]
        if not usages:
            return {}
        result = {}
        if all('input' in u for u in usages):
            result['n_input_tokens'] = sum(u['input'] + u.get('cacheRead',0) + u.get('cacheWrite',0) for u in usages)
        if all('output' in u for u in usages):
            result['n_output_tokens'] = sum(u['output'] for u in usages)
        if all('cacheRead' in u for u in usages):
            result['n_cache_tokens'] = sum(u['cacheRead'] for u in usages)
        if all(isinstance(u.get('cost',{}).get('total'), (int,float)) for u in usages):
            result['cost_usd'] = sum(u['cost']['total'] for u in usages)
        return result
    return {}


class OMP(CommandAgent):
    package = "@oh-my-pi/pi-coding-agent"
    binary = "omp"

    @staticmethod
    def name():
        return "omp"

    async def setup(self, environment):
        await self.checked(environment, "npm install -g bun@1.4.4", timeout_sec=180)
        await super().setup(environment)

    def argv(self):
        return ["omp", "-p", "--mode", "json", "--no-session", "--no-title", "--model", self.model_name]


class Droid(CommandAgent):
    package = "@factory/cli"
    binary = "droid"

    @staticmethod
    def name():
        return "droid"

    def argv(self):
        return ["droid", "exec", "--auto", "medium", "--output-format", "json", "--model", self.model_name]


class DSH(CommandAgent):
    package = "@deepseek-ai/dsh"
    binary = "dsh"

    @staticmethod
    def name():
        return "dsh"

    async def setup(self, environment):
        await super().setup(environment)
        await self.checked(environment, 'dsh --profile headless --help', timeout_sec=60)
        result = await self.checked(environment, 'dsh --profile headless --dump-default-config', timeout_sec=60)
        (self.logs_dir/'default-config.yml').write_text(result.stdout or '')

    async def prepare(self, environment):
        patch = self.model_patch(self.model_name)
        path = self.logs_dir / "model.patch.yml"
        path.write_text(json.dumps(patch))
        await environment.upload_file(source_path=path, target_path="/tmp/bench-model.patch.yml")

    @staticmethod
    def model_patch(model_name):
        provider, sep, model = model_name.partition("/")
        if not sep or not model:
            raise ValueError("DSH model must be provider/model")
        if provider == 'deepseek':
            provider = 'deepseek-official'
        patch = [{"id": "agent-default-model", "config": {"provider": provider, "model": model}}]
        if provider != 'deepseek-official':
            keys = {'anthropic':'ANTHROPIC_API_KEY', 'openai':'OPENAI_API_KEY'}
            if provider not in keys:
                raise ValueError('Add this DSH provider route explicitly before benchmarking it')
            patch.append({'id':'llm-pi-ai', 'config':{'providers':{provider:{'apiKeyEnv':keys[provider], 'retryPolicy':{'mode':'normal','maxRetries':0}}}}})
        return patch

    def argv(self):
        return ["dsh", "--profile", "headless", "--patch", "/tmp/bench-model.patch.yml", "--json", "--permission-mode", "workspace-write", "--approval-policy", "never"]
