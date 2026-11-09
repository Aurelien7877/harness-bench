# What the tasks measure

The pack contains nine small tasks across six categories. It is a screening tool for choosing a harness on your own machine. It does not estimate a model's general intelligence or reproduce an official leaderboard.

| Task | Category | Required work | How it is graded |
|---|---|---|---|
| `startup` | Startup | Read numbers, write a reusable Python script, return count and sum. | Saved public answer, public rerun and two held-out inputs, including an empty list. |
| `humaneval-0` | Python coding | Implement `has_close_elements` in the supplied file. | Original HumanEval tests, including the strict distance threshold. |
| `humaneval-12` | Python coding | Implement `longest` in the supplied file. | Original HumanEval tests, including empty input and first-item tie behavior. |
| `ds-aggregation` | Data science | Deduplicate a CSV before filtering, preserve signed refunds and zeros, aggregate decimal amounts. | Saved public answer, public rerun and two held-out inputs. Checks include duplicate invalid first rows, new regions, decimals and zero totals. |
| `ds-retrieval` | Data science | Calculate mean recall@3 and MRR@3, then choose a retriever. | Saved public answer, public rerun and two held-out inputs. Checks include first relevant rank, top-three cutoff, no hits, short/empty rankings and ties. |
| `ds-leakage` | Data science | Audit a supplied experiment for future-information leakage and an invalid split. | Exact structured answer with separate checks for leakage columns, split, preprocessing and the accuracy claim. No training. |
| `research-evidence` | Research | Reconcile conflicting fictional sources, apply an official correction and choose a product. | Exact structured answer with source IDs, corrected RAM and delivery-cost uncertainty. This is document synthesis, not live web research. |
| `general-reconciliation` | General work | Write a reusable invoice and payment reconciliation script. | Saved public answer, public rerun and two held-out inputs. Checks include global payment deduplication, unsorted invoices, same-date ties and customer-specific unused credit. |
| `context-revisions` | Context retrieval | Recover the latest explicitly revised preferences from a file with distracting history. | Exact values and the original date of the still-valid budget revision. This tests file retrieval, not persistent memory or context compaction. |

The startup task runs first. Other tasks are shuffled with a fixed seed. Startup is a cheap way to see whether an adapter can read and write files before interpreting a harder task's failure.

## Output contracts

Every instruction names its input, the required output fields and any ordering or tie rule. JSON object key order does not matter. List order matters where the instruction requests a sorted list. The grader rejects missing or extra fields, wrong types, booleans used as numbers, nonfinite values and numeric errors larger than `0.000001`.

The four script tasks require `analyze.py INPUT_PATH OUTPUT_JSON_PATH` and a correct `answer.json` produced from the public input. Their verifier checks the saved answer, reruns the program and evaluates two additional inputs independently. A wrong public result does not suppress held-out diagnostics. Each invocation has a five-second limit; these tasks require only the Python standard library.

The other three personal tasks ask for a structured answer to a fixed evidence fixture. A reusable script is optional. Their scope is deliberately narrower than an open-ended research, memory or data-science evaluation.

## Scores and limitations

A task passes only when every required check passes. Diagnostic checks explain a failure; they do not turn a failed task into a partial success. A harness timeout remains a timeout even if some files were written. An unavailable diagnostic is unknown, not a failure or a zero.

Held-out inputs and reference solutions are published for reproducibility. They are hidden from the normal agent workspace, not secret from someone who downloads this repository. Do not treat these fixtures as resistant to benchmark contamination. Never put reference solutions or verifier files into the agent's starting workspace.

Two HumanEval tasks are retained with their upstream tests and MIT provenance. Personal tasks use synthetic data. Nine tasks and a single attempt provide limited evidence. Compare identical task versions and model settings, inspect failures, then repeat promising comparisons before choosing a harness. Historical scores from earlier task versions should not be pooled with these revised graders.

Run `python3 scripts/build_tasks.py` to regenerate the fixtures. The unit tests check reproducibility, reference answers, wrong answers, hardcoded public answers and malformed outputs. These checks do not call a model, build containers or launch a campaign.
