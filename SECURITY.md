# Security and private results

The repository contains synthetic fixtures and public HumanEval examples.
Campaigns, notebooks with execution outputs, account credentials and model
weights do not belong in a public commit.

The launcher gives Harbor an isolated home and a small environment allowlist.
Hosted runs forward only the selected harness's registered API variables.
Local runs forward no provider credentials. Personal subscription logins are
not mounted. Docker's host configuration is used for container discovery;
it is not mounted into the trial workspace.

Agents execute programs in Docker containers. Docker is not a complete security
boundary for hostile code. Trial containers can reach the network and the local
Ollama server. Use synthetic data, dedicated provider credentials and a trusted
machine. Do not mount private folders into benchmark containers.

## Before sharing changes

```sh
python3 scripts/check_publication.py
```

This lightweight check inspects tracked files and reachable Git history for
common credential patterns, private paths, notebook outputs and runtime files.
It reports locations and rule names without printing matching secret values.
It does not prove the absence of every secret, and it is not a dependency
vulnerability audit. Review changes yourself as well. Never push local stashes
or publish raw campaign logs without reviewing them.

Keep the GitHub account's security contact private when reporting a credential
exposure. If a credential was committed, revoke it at its provider; deleting
the current file does not remove it from history.
