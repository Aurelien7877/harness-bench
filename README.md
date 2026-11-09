# Harness Bench

Give two coding agents the same model, the same files and the same job. Can both write a program that still works when the data changes?

```text
                    same task + input files
                         /          \
                +-------+            +----------+
                |   Pi  |            | OpenCode |
                +-------+            +----------+
                    |    \          /     |
                    |     [ Ollama ]      |
                    |      one model      |
                    v                     v
                output A              output B
                     \                  /
                       [ same grader ]
```

Harness Bench runs eight small tasks in Docker using [Harbor](https://github.com/harbor-framework/harbor). Each task has an executable grader. The default local demo compares **Pi and OpenCode** on one data science task. Both use the same Ollama model running on your machine.

## Try it locally

Start Docker with Compose and the Ollama app. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed. The commands below target macOS with OrbStack or Docker Desktop. Trial containers reach the host through `host.docker.internal:11434`. On Linux, configure that hostname and a reachable Ollama listener first.

```sh
git clone https://github.com/Aurelien7877/harness-bench.git
cd harness-bench
make setup
ollama pull qwen3:4b
./bench local
```

The first run downloads the Python dependencies, a shared Docker image and the model. The [Qwen3 4B weights](https://ollama.com/library/qwen3:4b) take about 2.5 GB in Ollama's model store. Each trial installs its pinned CLI in a disposable container. Local inference uses your hardware and requires no paid API key.

Open the `report.md` path printed at the end. Its sibling `results.csv` lists each planned trial, grade, duration and available token counts. The manifest records the Ollama model digest, task hashes and run configuration. Missing usage fields stay empty.

## What the agents do

| Category | Tasks | What a pass requires |
|---|---:|---|
| Python coding | 2 | Implement functions from [HumanEval](https://github.com/openai/human-eval) that pass the original tests. |
| Data science | 3 | Clean a sales table, calculate retrieval metrics, and identify leakage in an experiment. The two programming tasks also run on hidden inputs. |
| Research | 1 | Resolve a contradiction in a fixed set of dated sources and identify the supporting documents. |
| General work | 1 | Apply payments to invoices while handling duplicates and unapplied credit. |
| Context | 1 | Recover the current budget and region from a file of revised instructions. |

The local demo uses the retrieval task. It checks recall@3 and reciprocal rank@3 on two sets of rankings. A script that merely prints the visible answer fails the hidden check.

## Compare two harnesses

Start with the single-task demo. Then broaden the workload or repeat it to see whether a difference persists. Every additional attempt repeats each selected task for each harness.

```sh
./bench local --suite quick --attempts 2
./bench local --harness pi --model qwen3:4b
```

| Suite | Tasks per harness | Purpose |
|---|---:|---|
| demo | 1 | Exercise file editing, execution and verification |
| smoke | 2 | Check a coding task and a data task |
| quick | 5 | Screen candidates across four categories |
| full | 8 | Include the leakage audit and context task |

For an interpretable comparison, hold the model digest, context length, hardware and timeout fixed. Record the Ollama version and any reasoning settings you change. Look at paired task outcomes and the time spent in the agent. A timeout, an installation failure and an incorrect calculation deserve different diagnoses. Two attempts on five tasks are a starting point for choosing which failures to investigate.

## Check the graders for free

```sh
make test
./bench run --suite full --harness oracle --harness nop
```

The reference solutions should pass 8/8. The idle agent should score 0/8. Both commands work without a model key.

## Hosted models and other harnesses

Seven configurations ship in [harnesses.toml](config/harnesses.toml). Pi, OpenCode, Claude Code and Codex use Harbor adapters. OMP, Factory Droid and DeepSeek Harness use the [CLI adapters](adapters/command.py). The Ollama command is configured for Pi and OpenCode. Install a specific CLI in a disposable container with `./bench install-check --harness droid`.

To run a hosted model, export its provider key in your shell. Set a hard spending limit or prepaid balance at the provider first. The planner reserves EUR 1 per hosted trial and allows EUR 20 per campaign. The actual bill depends on provider usage. The cap flag records the external limit you set.

```sh
./bench plan --suite smoke --harness pi --model pi=anthropic/YOUR_MODEL_ID
./bench run --suite smoke --harness pi --model pi=anthropic/YOUR_MODEL_ID --provider-cap-eur 20
```

## Change a model, CLI or task

- **Model**. Pull another tool-capable Ollama model and pass its tag with `./bench local --model TAG`.
- **CLI version**. Edit its version in [harnesses.toml](config/harnesses.toml), then run `./bench install-check --harness NAME`.
- **Harness**. Copy the [registry example](config/new-harness.example.toml) and select a Harbor adapter or a local adapter class.
- **Task**. Add a Harbor task under [tasks](tasks), put its name in a [suite](config/bench.toml), then check the reference solution and idle baseline.

Runs execute sequentially and share a Docker base image. A storage check stops campaigns at 18 GB in the project folder. Docker layers and Ollama weights live in their respective stores. HumanEval attribution and the upstream license are in [vendor/humaneval](vendor/humaneval).
