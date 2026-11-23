"""The model alone: one chat call, no tools, no retries; the reply is saved as the file the task names.

The prompt carries the instruction and the text files already in /workspace, so the model sees
everything an agent could read. It cannot run code or check its work, which is what a harness adds.
"""
import json
import re
import shlex
import urllib.request

from harbor.agents.base import BaseAgent

LIST_FILES = r"""
import os
for name in sorted(os.listdir('.')):
    if os.path.isfile(name) and os.path.getsize(name) < 20000:
        try:
            print('--- ' + name + '\n' + open(name).read())
        except UnicodeDecodeError:
            pass
"""
TARGETS = ('answer.json', 'candidate.py', 'analyze.py')
RULES = ("You cannot run commands. Reply with the complete final content of the file to write, "
         "as one fenced code block, and nothing else.")


def target_file(instruction, workspace_text):
    """The file the task asks for: named in the instruction, else the one source file that is not a test."""
    for name in TARGETS:
        if name in instruction:
            return name
    named = re.findall(r"\b([\w-]+\.py)\b", instruction)
    return next((n for n in named if not n.startswith('test_')), named[0] if named else 'answer.json')


def extract(reply):
    """First fenced block of the reply, or the whole reply when it has none."""
    match = re.search(r"```[^\n]*\n(.*?)```", reply, re.S)
    return (match.group(1) if match else reply).strip() + "\n"


class Bare(BaseAgent):
    @staticmethod
    def name():
        return "bare"

    def __init__(self, *args, version="1", local_model=None, local_port=11434, local_output=8192, **kwargs):
        super().__init__(*args, **kwargs)
        self.local_model, self.local_port, self.local_output = local_model, local_port, local_output

    def version(self):
        return "1"

    async def setup(self, environment):
        pass

    async def run(self, instruction, environment, context):
        files = await environment.exec(command=f"cd /workspace && python3 -c {shlex.quote(LIST_FILES)}", timeout_sec=30)
        workspace = files.stdout or ""
        prompt = f"{instruction}\n\nFiles in /workspace:\n{workspace}\n{RULES}"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.local_port}/v1/chat/completions",
            json.dumps({"model": self.local_model, "max_tokens": self.local_output,
                        "messages": [{"role": "user", "content": prompt}]}).encode(),
            {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=900) as response:
            reply = json.load(response)["choices"][0]["message"].get("content") or ""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "reply.txt").write_text(reply)
        name = target_file(instruction, workspace)
        local = self.logs_dir / "output"
        local.write_text(extract(reply))
        await environment.upload_file(source_path=local, target_path=f"/workspace/{name}")
        context.metadata = {"usage_status": "unknown", "adapter": "Bare", "file": name}
