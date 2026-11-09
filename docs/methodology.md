# What this benchmark can tell you

Harness Bench is a small screening tool for your own machine and tasks. It does
not measure an agent's general intelligence. The tasks are public, handpicked
and small. Keep the generated programs and read the failures alongside the scores.

## Choose a useful experiment

1. Start with two harnesses and one local model that supports tools. Keep the
   model digest, machine, context request, output limit and timeout the same.
2. Choose `quick` for six tasks across startup, coding, data science, research
   and general work. Use `full` for all nine tasks and context retrieval.
3. Use one attempt to check compatibility. Repeat promising comparisons later.
   Repeated attempts on the same task add less evidence than new tasks.
4. Review failure types and outputs before changing the model or limits. Change
   one factor at a time and keep campaigns separate.

Trials run one at a time. Their order is seeded and shuffled; startup always
runs first. This reduces predictable ordering but does not remove cache,
thermal or warmup effects. Agent time excludes CLI installation and grading;
it is not total elapsed campaign time. A timeout is an observed limit, not
the time the agent would have needed to finish.

Requested context limits configure the harnesses. They do not guarantee that
Ollama used the same context on every request. The manifest records available
Ollama metadata so you can inspect the actual loaded context when reported.
Different harnesses still have different prompts, tools and compression rules.
Those differences are part of the comparison.

## Read the statistics

| Measure | Meaning |
|---|---|
| Work success | Passed work trials divided by all scheduled work trials. Timeouts, errors and unfinished work stay in the denominator. |
| Startup | A separate read, write and Python health check. Excluded from work success. |
| Per-task score | Makes an easy success and a difficult failure visible instead of hiding both in one average. |
| Per-category score | Uses the tasks selected in that category. A category with one task remains one task's evidence. |
| 95% Wilson interval | A descriptive binomial interval for this trial sample. It does not account for correlated attempts or establish performance on future tasks. |
| Matched outcomes | Win, tie or loss for identical model, task and attempt identifiers. These are counts, not a significance test. |
| Diagnostic checks | Explain one task's failure. They are not partial credit and are not interchangeable across tasks. |
| Median agent time | Median of available measurements, including recorded timeouts. Missing measurements are not zero. |
| Cost and token coverage | Shows how many scheduled trials reported each value. A partial cost sum is not the campaign bill. |

An all-zero campaign can reflect calculation mistakes, unsupported tool use,
configuration errors or timeouts. It does not establish that the harnesses are
equally capable. No universal winner or significance claim is generated.

## Task integrity

See the [task catalog](tasks.md) for each input, deliverable and pass rule.
Pipeline tasks check the saved answer, rerun the program on the public input,
and use held-out inputs to reject sample-only programs. Static evidence tasks
check a structured answer; they do not evaluate unrestricted prose quality.
The research task uses a local source pack, not live browsing. Context retrieval
checks revised instructions in a file, not cross-session memory or compaction.
HumanEval fixtures retain their original provenance and license.

Hidden cases are not part of the initial agent inputs, but all task sources
are public. This is a functional evaluation of cooperative agents, not an
adversarial competition or a defense against test tampering.

## Reproducibility

Each campaign stores CLI version information when available, task file hashes,
configuration snapshots, key Python library versions and the Ollama digest. Trials stop if task files change
mid-campaign. Old campaigns retain their original grading. Do not pool results
across task revisions or assume that a newer grader retroactively applies to
saved outputs. Keep private runs and generated files out of commits.
