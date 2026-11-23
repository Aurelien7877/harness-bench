# Harnesses

## Compared harnesses

The four harnesses compared in local campaigns. The first rows come from the npm metadata of each pinned version and from tool calls observed in our trials; the rows from "Non-interactive mode" down come from the official documentation.

| | **Pi** | **OpenCode** | **Factory Droid** | **DeepSeek Harness (dsh)** |
|---|---|---|---|---|
| Pinned version | 1.5.2 | 1.19.6 | 1.14.0 | 0.2.2-rc.1 |
| npm package | `@earendil-works/pi-coding-agent` (legacy name for older versions) | `opencode-ai` | `@factory/cli` | `@deepseek-ai/dsh` |
| License | MIT | MIT | Proprietary (`UNLICENSED`) | MIT |
| Runtime declared upstream | Node ≥ 22.19 | Native binary | Node ≥ 20 | Node ≥ 24.9 |
| Integration here | Upstream Harbor adapter (`LocalPi` wrapper for local limits) | Upstream Harbor adapter | [Local CLI adapter](../adapters/command.py) | [Local CLI adapter](../adapters/command.py) |
| Local model route | OpenAI-compatible endpoint | OpenAI-compatible custom provider | Custom model, Chat Completions | Custom provider, `openai-completions` |
| Tools seen in trials | `read`, `bash`, `edit`, `write` | `read`, `bash`, `edit`, `write` | `Read`, `Execute`, `Edit`, `Create` | `read`, `glob`, `bash`, `edit`, `write` |
| Token usage reported by the harness | Yes | Yes | No | No (the proxy fills it) |
| Account needed for local use | No | No | May ask for Factory authentication | No |
| Result trace | Harbor trajectory with step timestamps | Harbor trajectory with step timestamps | Native event stream | Native event stream, profile-based config |
| Non-interactive mode | `-p` (print), `--mode json` (JSONL events) | `opencode run "<prompt>"` | `droid exec`, `--auto low\|medium\|high`, stream-json output | `--profile headless`, final answer on stdout |
| Permission model | None built in: runs with the user's rights, containerization recommended | Ordered allow/ask/deny rules per action and resource | Autonomy levels (off, low, medium, high), permission rules, secret scanning | `workspace-write` sandbox by default; reads and network not confined |
| Subagents | Not built in (add by extension) | Built in (`general`, `explore`, custom agents) | Built in (`worker`, `explorer`, custom droids) | Optional Codex / Claude Code subagent bundles |
| MCP | stdio and streamable HTTP; tools exposed through a `codemode` layer by default | stdio and remote with OAuth | stdio, HTTP and legacy SSE | Off by default; servers treated as trusted code |
| Context compaction | Automatic, plus `/compact` | Automatic, configurable | `/compress`, token limits in settings | Automatic in the `minimal` agent preset, plus `/compact` |
| Extensibility | Extensions, skills, prompt templates, Pi packages | Plugins, skills, commands, agents | Hooks, skills, plugins, custom droids | Everything is a plugin; profiles are stacks of patch layers |
| Data leaving the machine | `/share` and `/bug` only when you run them | Not stated in the pages read | Cloud session sync on by default | Session-log upload (official DeepSeek API) and OTel upload on by default; we set `DSH_TELEMETRY_DISABLED=1` |
| Maturity | Not stated (its separate Radius gateway is in early alpha) | Stable v1 pinned here; the online docs describe v2 | Commercial product | Developer preview, "compatibility-breaking changes" expected |

**Sources and caveats.** Rows from "Non-interactive mode" down come from the official documentation read on 18 November 2026: [Pi](https://github.com/earendil-works/pi), [OpenCode](https://opencode.ai/docs), [Factory Droid](https://docs.factory.com) and [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness). Not every page was read.

- **OpenCode:** the online docs describe v2 (`@opencode/cli`, a `shell` tool, `permissions`). This benchmark pins v1.19.6, which exposes `bash` and `opencode-ai`, so details may differ for the pinned version. The license row comes from npm, since no docs page stated it.
- **Droid:** the docs name the npm package `droid`; we pin `@factory/cli` 1.14.0. The docs did not confirm local OpenAI-compatible endpoints; our trials worked with a custom model entry. The docs state "All rights reserved", consistent with the proprietary license in npm.
- **dsh:** the docs do not mention the `--json`, `--permission-mode` and `--approval-policy` flags that the adapter passes to 0.2.2-rc.1, and the version itself is not stated there. The flags worked in our trials; treat them as specific to the pinned release candidate.
- **Pi:** the local-endpoint page (`models.md`) was not read; local use is confirmed by our trials, not by the pages read.

## Results

Full suite, 21 tasks, one attempt, `lfm3:1.7b`, one machine.

| | Pi | OpenCode | dsh | Droid |
|---|---:|---:|---:|---:|
| Work tasks passed | 17/20 | 16/20 | 16/20 | 14/20 |
| 95% interval | 64 to 95% | 58 to 92% | 58 to 92% | 48 to 86% |
| Median agent time | 13 s | 26 s | 48 s | 46 s |
| Model calls per task (median) | 5 | 6 | 9 | 4 |
| Input tokens, all trials | 0.61 M | 0.81 M | 3.66 M | 1.08 M |
| Time to first call | 0.8 s | 1.2 s | 1.4 s | 1.0 s |

Success rates are not distinguishable: the intervals overlap and no pair differs on the same tasks (sign test, p ≥ 0.45). Cost and speed differ clearly: dsh sends about six times the input tokens of Pi, and Pi answers each call fastest. Data-science tasks are the hardest for this model across harnesses. Three attempts per task are needed before ranking on success.

Other harnesses supported by the launcher:

| Harnesses | Integration | Inference covered by the launcher |
|---|---|---|
| Claude Code and Codex | Harbor adapters | Hosted models |
| Oh My Pi (OMP) | CLI adapter | Hosted configurations |

See the [harness registry](../config/harnesses.toml) for exact versions and credential names. You can check a CLI installation with `./bench install-check --harness droid`.

## Extend the benchmark

| To change | Start here |
|---|---|
| Local model | Pull a tool-capable Ollama model and pass its tag with `./bench local --model TAG`. |
| CLI version | Edit the pin in [harnesses.toml](../config/harnesses.toml), then run its installation check. |
| Harness | Copy the [registry example](../config/new-harness.example.toml) and select an upstream adapter or a local adapter class. |
| Task | Add a [Harbor task](../tasks), register it in a [suite](../config/bench.toml), and check it with both the reference solution and idle agent. |

See the [task catalog](tasks.md), [evaluation methodology](methodology.md) and [publication checks](../SECURITY.md). `make check` runs unit tests, configuration validation and the publication scan without a container or model. Use `make setup-python` if you only need the Python environment for those checks.
