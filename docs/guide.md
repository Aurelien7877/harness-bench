# Guide

Tuning a harness, running faster, resuming and reading results.

## Tune your own harness

The best harness is the one tuned on *your* work, not the one that tops someone else's leaderboard. Harness Bench is built to be that loop on your own machine: your tasks, a local model, no account and no data leaving the laptop (an Ollama cloud model is optional, see [Run faster](../README.md#quick-start)).

1. **Write your tasks.** Copy a [task](../tasks) folder: an instruction, input files, a reference solution and a check script. Five to ten real chores of yours beat twenty-one generic ones. Register them in a [suite](../config/bench.toml).
2. **Get a baseline.** Run `./bench local --suite mine --harness pi` (or any harness above) and read the pass rate, calls and latency.
3. **Make your harness a registry entry.** Your *self harness* is a CLI plus the choices around it: system prompt, tools, step limit, model, version. Add it from the [registry example](../config/new-harness.example.toml), either as a Harbor adapter or as a small class in [adapters/command.py](../adapters/command.py) that implements `argv()` and, if needed, `prepare()`.
4. **Change one thing at a time.** Give each variant its own registry name (`mine-short-prompt`, `mine-no-edit-tool`, `mine-8-steps`) and run the same suite with the same model. The notebook's matched comparison shows which variant wins on the same task and attempt.
5. **Keep what wins, then check it.** Hold a few tasks back from tuning and run them last. A variant that only improves the tasks you tuned on is overfitting, not progress.

The repository includes one worked example. `droid-tuned` is Droid plus a short `AGENTS.md` profile ([profiles/droid.md](../profiles/droid.md)) and an output check: after each run, the adapter verifies that `answer.json` is valid JSON and that a requested `analyze.py` exists, and re-runs the agent with the problem if not. Each change is logged by root cause in [profiles/droid.sim.json](../profiles/droid.sim.json), with the predicted and observed outcome, so later tuning builds on what was already tried. A guidance file alone did not move the pass rate with this small model; the output check is the part to measure. Compare them on held-back tasks:

```bash
./bench local --suite tune-test --harness droid --harness droid-tuned --attempts 3
```

Harness Bench measures and compares; you decide what to change. The measures it adds to a pass rate (calls, tool calls, time to first call, tokens) tell you *why* a variant is better, for instance fewer wasted calls or a faster start, so you can tune toward the failure you actually have.

## Run faster

- **Preinstalled CLIs.** `make setup` (or the first campaign) builds one image with Pi, OpenCode, Droid and DeepSeek Harness at the versions in `config/harnesses.toml`. It rebuilds only when a version changes. In our `full` campaign, installing the CLIs took 27% of the time (about 32 s per trial); it now takes 1 to 2 s.
- **Ollama cloud models.** Use a tag such as `glm-5.3-flash:cloud` after `ollama signin`. Calls go through your local Ollama, so the measuring proxy is unchanged. Cloud trials run up to 3 at once, the concurrent-request limit of the pay-as-you-go and Pro plans (`--concurrency` raises it, for example on Max), each with its own proxy. The proxy retries a busy service (429, 502, 503) before any reply byte. Cloud inference is billed per token, and prompts leave your machine; the tasks here are synthetic. Compare latency across harnesses within one campaign only: it measures the network and the service, not your hardware.
- **API providers.** `./bench local --provider gemini --model MODEL` sends calls to a provider defined in `config/bench.toml`. The key is read from `GEMINI_API_KEY` (environment or the git-ignored `.env`); the proxy adds it, so containers only hold a dummy value. Check the plan first: Google's free tier allowed 20 requests per day for `gemini-3.6-flash` when we tried it, far below one campaign, and Gemini 3 models reject multi-step tool use from clients that do not echo back a `thought_signature`. Use a paid plan, or a provider whose limits you have read.
- **Housekeeping.** `make prune` frees Docker build cache older than a week. Trials of a local model stay sequential on purpose, because parallel runs would share one GPU and distort timings.

## Resume an interrupted campaign

 Every trial is saved as soon as it ends, and `results.csv` and `report.md` are refreshed after each one. Resume with `./bench local --resume runs/campaigns/CAMPAIGN_ID`: finished trials are kept, interrupted or technically failed ones are rerun (their earlier files move to `runs/jobs/_retried`). A resumed campaign keeps its original settings and harness versions, and refuses to continue if a task or the model weights changed. A harness with three consecutive technical errors is skipped for the rest of the campaign instead of wasting hours.

## Read the results

**Startup is a health check, not part of the work score.** A passing work trial must satisfy every required check. Diagnostics explain failures without turning them into partial successes.

Open the `report.md` path printed when the campaign finishes. Use `results.csv` to compare the same task and attempt across harnesses. It includes the grade, status, agent time, tokens, LLM calls, tool calls, time to first call, call latency and time to first token. Blank fields mean the value was not measured. Local campaigns route every harness through a logging proxy (`llm_proxy_port` in `config/bench.toml`, default 11436), so calls, latency and tokens are measured the same way for all harnesses. Token counts come from the harness when it reports them, otherwise from the proxy (`tokens_source`; `proxy_partial` means some calls reported no usage, so the total is a lower bound). Time to first call runs from the start of the agent phase and includes harness start-up. The manifest records the task hashes, model digest for Ollama runs, and configuration used for the campaign.

The notebook includes a compact summary table, 0% labels, exploratory 95% intervals, category and task heatmaps, and same-model matched outcomes with an exact sign test. Token and cost totals show their measurement coverage. Unknown values stay unknown. See [how to interpret the statistics](methodology.md).

If one agent passes and another fails, open both workspaces. Check whether the failing agent misunderstood the metric, wrote a program that only handles the sample, or ran out of time. Repeat promising comparisons with the same model digest, hardware, context length and timeout before drawing conclusions.

<details>
<summary><strong>Run a hosted model with a spending limit</strong></summary>

Set a hard spending limit or prepaid balance at your provider and export its API key. The planner reserves EUR 1 per hosted trial and allows EUR 20 per campaign. The provider controls the actual billing limit. Replace the example model ID with one available on your account.

```sh
./bench plan --suite smoke --harness pi --model pi=anthropic/YOUR_MODEL_ID
./bench run --suite smoke --harness pi --model pi=anthropic/YOUR_MODEL_ID --provider-cap-eur 20
```

</details>

<details>
<summary><strong>Verify the graders and inspect disk usage</strong></summary>

```sh
make test
./bench run --suite full --harness oracle --harness nop
./bench doctor
```

The reference solutions should score 21/21 and the idle agent 0/21. These checks use no model key. Local trials run sequentially and share a Docker base image. The project’s storage guard stops campaigns at 18 GB in the project folder. Docker layers and Ollama weights live in their own stores.

</details>
