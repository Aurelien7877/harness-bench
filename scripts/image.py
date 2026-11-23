"""Build the shared task image with the pinned agent CLIs already installed.

Without this, every trial downloads nvm, Node and the CLI again (about a quarter of a campaign).
"""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = 'harness-bench-base:1'
LABEL = 'org.harness-bench.agents'
LOCAL_HARNESSES = ('pi', 'opencode', 'droid', 'dsh')


def agent_install_script(registry):
    """Shell script installing every local harness at the version pinned in config/harnesses.toml."""
    from harbor.agents.installed.node_install import nvm_node_install_snippet
    from harbor.agents.installed.pi import _CURRENT_PI_PACKAGE
    from adapters.command import DSH, Droid
    plain, nvm = {}, {}
    for name, entry in registry.items():
        kind = entry.get('base', entry.get('agent', name))
        if kind == 'pi':
            nvm[_CURRENT_PI_PACKAGE] = entry['version']
        elif kind == 'opencode':
            nvm['opencode-ai'] = entry['version']
        elif kind == 'droid':
            plain[Droid.package] = entry['version']
        elif kind == 'dsh':
            plain[DSH.package] = entry['version']
    spec = lambda pkgs: ' '.join(f'{p}@{v}' for p, v in sorted(pkgs.items()))
    lines = ['set -eu']
    if plain:
        lines.append(f'npm install -g {spec(plain)}')
    if nvm:
        # Same flags as Harbor's own installers: Pi skips lifecycle scripts, OpenCode needs its postinstall.
        installs = ' && '.join(f'npm install -g {"--ignore-scripts " if package == _CURRENT_PI_PACKAGE else ""}{package}@{version}'
                               for package, version in sorted(nvm.items()))
        lines.append(f'{nvm_node_install_snippet()} && {installs}')
    lines.append('npm cache clean --force')  # the download cache alone is ~700 MB
    return '\n'.join(lines)


def build_base_image(registry, force=False, env=None, say=print):
    """Build `harness-bench-base:1` unless it already carries these exact agent versions."""
    script = agent_install_script(registry)
    dockerfile = (ROOT / 'docker/Dockerfile').read_text()
    digest = hashlib.sha256((dockerfile + script).encode()).hexdigest()[:16]
    current = subprocess.run(['docker', 'image', 'inspect', TAG, '--format', '{{ index .Config.Labels "' + LABEL + '" }}'],
                             capture_output=True, text=True, env=env)
    if not force and current.returncode == 0 and current.stdout.strip() == digest:
        return 'current'
    say('Building the shared task image with the agent CLIs preinstalled (once, a few minutes)...')
    subprocess.run(['docker', 'build', '-t', TAG, '--build-arg', 'AGENT_INSTALL=' + script,
                    '--build-arg', 'AGENT_HASH=' + digest, str(ROOT / 'docker')], check=True, env=env)
    return 'built'
