# Harness Bench

**A very small local benchmark to find, or tune, the harness you need.**

![Abstract violet, blue and mint waves made from tiny ASCII characters](assets/harness-bench.svg)

[![MIT license](https://img.shields.io/badge/license-MIT-28785a?style=flat-square)](LICENSE)
[![Lightweight checks](https://github.com/Aurelien7877/harness-bench/actions/workflows/checks.yml/badge.svg)](https://github.com/Aurelien7877/harness-bench/actions/workflows/checks.yml)
[![Local inference with Ollama](https://img.shields.io/badge/local_inference-Ollama-16765f?style=flat-square)](#quick-start)
[![Open the Python notebook](https://img.shields.io/badge/Jupyter-open_notebook-b54f20?style=flat-square)](notebooks/local-comparison.ipynb)
[![Eight harness configurations](https://img.shields.io/badge/harnesses-8-514d9b?style=flat-square)](config/harnesses.toml)
[![Twenty-four graded tasks](https://img.shields.io/badge/graded_tasks-24-275f85?style=flat-square)](docs/tasks.md)

Same model, same tasks, same container: how much of an agent's result comes from the harness? Harness Bench runs agent CLIs (Pi, OpenCode, Factory Droid, DeepSeek Harness) on one local model, grades what they produce, and measures calls, tokens and latency with a logging proxy. It is a screening tool: samples are small, so use it to decide which harness deserves a longer test on your own work.

## What a harness adds

`bare` is the model alone: one call, no tools. `lfm3:1.7b`, 6 tasks × 3 attempts, 18 trials per row.

| | code-fix-stats | code-roman | code-run-seeds | math-bignum | math-count | math-word | Passed | Median time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| No harness | 3/3 | 2/3 | 0/3 | 0/3 | 0/3 | 3/3 | **8/18** | 122 s |
| OpenCode | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 76 s |
| Droid | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 3/3 | **17/18** | 104 s |
| Pi | 3/3 | 3/3 | 3/3 | 1/3 | 3/3 | 3/3 | **16/18** | 15 s |
| dsh | 2/3 | 3/3 | 3/3 | 2/3 | 0/3 | 3/3 | **13/18** | 131 s |

- Without tools the model fails all nine tasks that need a computation. With any harness it writes a few lines of Python, runs them and copies the result.
- OpenCode (p = 0.002), Droid (0.004) and Pi (0.008) beat the model alone on the same tasks and attempts; dsh does not (0.125).
- No two harnesses differ on success (p ≥ 0.06), but Pi is 5 to 9 times faster. The 21-task `full` suite agrees: [pass rates overlap, speed and tokens differ](docs/harnesses.md#results).
- Eighteen paired trials per comparison: read the p values as indicative.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker with Compose and [Ollama](https://ollama.com/), all running.

```sh
git clone https://github.com/Aurelien7877/harness-bench.git
cd harness-bench
make setup
ollama pull lfm3:1.7b
python3 scripts/local_comparison.py     # previews the command
./bench local --suite demo --harness pi --harness opencode
```

The [notebook](notebooks/local-comparison.ipynb) does the same with progress bars, figures and matched comparisons; it opens the saved `value` campaign by default. To reproduce the table above:

```sh
./bench local --suite value --harness bare --harness pi --harness opencode --harness droid --harness dsh --attempts 3
```

## Tasks

Twenty-four graded tasks, each with a reference solution and an independent check. The [catalog](docs/tasks.md) lists them all.

| Category | Tasks |
|---|---|
| Startup | Read a file, write a script, count words, write a greeting. Health check, scored separately. |
| Python coding | Three [HumanEval](https://github.com/openai/human-eval) functions; fix three bugs; run a simulation; write a Roman-numeral converter. |
| Data science | Sales aggregation, retrieval metrics, a leakage audit. |
| Research | Conflicting sources, latest release, licence lookup. |
| General work | Invoice reconciliation, expense totals, email deduplication. |
| Math | A word problem and two exact computations that need code. |
| Context retrieval | Latest revised preferences, a code in a long log, the current contact. |

Suites: `demo` 2 tasks, `smoke` 3, `math` 3, `value` 6, `quick` 8, `full` 21.

## More

- [Guide](docs/guide.md): tune your own harness, run faster (preinstalled CLIs, Ollama cloud, API providers), resume a campaign, read the results.
- [Harnesses](docs/harnesses.md): the four compared CLIs side by side, and how to add one.
- [Methodology](docs/methodology.md) and [tasks](docs/tasks.md): grading, statistics and limits.

`make test` runs the checks without a model or container. MIT licensed; the HumanEval fixtures keep their [provenance and license](vendor/humaneval).
