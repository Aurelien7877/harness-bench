# What the tasks measure

The pack contains twenty-four small tasks. The `full` suite uses twenty-one of them, three per category across seven categories; the `value` suite adds three coding tasks that need running code. The second and third task of each category except data science are deliberately easy, so a small local model can show a success. It is a screening tool for choosing a harness on your own machine. It does not estimate a model's general intelligence or reproduce an official leaderboard.

| Task | Category | Required work | How it is graded |
|---|---|---|---|
| `startup` | Startup | Read numbers, write a reusable Python script, return count and sum. | Saved public answer, public rerun and two held-out inputs, including an empty list. |
| `humaneval-0` | Python coding | Implement `has_close_elements` in the supplied file. | Original HumanEval tests, including the strict distance threshold. |
| `humaneval-12` | Python coding | Implement `longest` in the supplied file. | Original HumanEval tests, including empty input and first-item tie behavior. |
| `startup-wordcount` | Startup | Count words and lines of a possibly empty text file. | Saved public answer, public rerun and two held-out inputs, including an empty file. |
| `startup-greeting` | Startup | Write a greeting from a name file. | Exact structured answer. |
| `humaneval-53` | Python coding | Implement `add`. | Original HumanEval tests. |
| `research-latest` | Research | Find the latest release in three unordered notes. | Exact version and date. |
| `research-source` | Research | Find the MIT-licensed library and its source ID. | Exact library and source ID. |
| `general-expenses` | General work | Total expenses by category; tie and empty-file rules. | Saved public answer, public rerun and two held-out inputs. |
| `general-contacts` | General work | Deduplicate emails after trimming and lowercasing. | Saved public answer, public rerun and two held-out inputs. |
| `context-needle` | Context retrieval | Find one access code in a 300-line log. | Exact code. |
| `context-contact` | Context retrieval | Find the current email and the date it was set. | Exact email and date. |
| `math-word` | Math | Two-step shopping word problem (change and item count). | Exact numbers. |
| `math-bignum` | Math | Compute a 5-digit product, a modular power and the 70th Fibonacci number exactly. | Exact integers. Hard to do by head, trivial with code. |
| `math-count` | Math | Count integers by digit sum and divisibility, count primes below 100000 and find the largest twin prime below it. | Exact integers; requires running code. |
| `code-fix-stats` | Python coding | Fix three bugs in a small module until the visible test passes (chunks, median, percentage rounding). | Held-out cases for each function, plus the visible test. |
| `code-run-seeds` | Python coding | Run a deterministic simulation for three seeds and report its printed counts. | Exact counts; the answer cannot be guessed, it has to be computed. |
| `code-roman` | Python coding | Write `to_roman` and `from_roman` for 1 to 3999 and make a visible round-trip check print OK. | Known values, reverse values, full round trip and distinct outputs. |
| `ds-aggregation` | Data science | Deduplicate a CSV before filtering, preserve signed refunds and zeros, aggregate decimal amounts. | Saved public answer, public rerun and two held-out inputs. Checks include duplicate invalid first rows, new regions, decimals and zero totals. |
| `ds-retrieval` | Data science | Calculate mean recall@3 and MRR@3, then choose a retriever. | Saved public answer, public rerun and two held-out inputs. Checks include first relevant rank, top-three cutoff, no hits, short/empty rankings and ties. |
| `ds-leakage` | Data science | Audit a supplied experiment for future-information leakage and an invalid split. | Exact structured answer with separate checks for leakage columns, split, preprocessing and the accuracy claim. No training. |
| `research-evidence` | Research | Reconcile conflicting fictional sources, apply an official correction and choose a product. | Exact structured answer with source IDs, corrected RAM and delivery-cost uncertainty. This is document synthesis, not live web research. |
| `general-reconciliation` | General work | Write a reusable invoice and payment reconciliation script. | Saved public answer, public rerun and two held-out inputs. Checks include global payment deduplication, unsorted invoices, same-date ties and customer-specific unused credit. |
| `context-revisions` | Context retrieval | Recover the latest explicitly revised preferences from a file with distracting history. | Exact values and the original date of the still-valid budget revision. This tests file retrieval, not persistent memory or context compaction. |

The startup task runs first. Other tasks are shuffled with a fixed seed. Startup is a cheap way to see whether an adapter can read and write files before interpreting a harder task's failure.

## Output contracts

Every instruction names its input, the required output fields and any ordering or tie rule. JSON object key order does not matter. List order matters where the instruction requests a sorted list. The grader rejects missing or extra fields, wrong types, booleans used as numbers, nonfinite values and numeric errors larger than `0.000001`.

The script tasks require `analyze.py INPUT_PATH OUTPUT_JSON_PATH` and a correct `answer.json` produced from the public input. Their verifier checks the saved answer, reruns the program and evaluates two additional inputs independently. A wrong public result does not suppress held-out diagnostics. Each invocation has a five-second limit; these tasks require only the Python standard library.

The other personal tasks ask for a structured answer to a fixed evidence fixture. A reusable script is optional. Their scope is deliberately narrower than an open-ended research, memory or data-science evaluation.

## Scores and limitations

A task passes only when every required check passes. Diagnostic checks explain a failure; they do not turn a failed task into a partial success. A harness timeout remains a timeout even if some files were written. An unavailable diagnostic is unknown, not a failure or a zero.

Held-out inputs and reference solutions are published for reproducibility. They are hidden from the normal agent workspace, not secret from someone who downloads this repository. Do not treat these fixtures as resistant to benchmark contamination. Never put reference solutions or verifier files into the agent's starting workspace.

Three HumanEval tasks are retained with their upstream tests and MIT provenance. Personal tasks use synthetic data. Twenty-one tasks and a single attempt provide limited evidence. Compare identical task versions and model settings, inspect failures, then repeat promising comparisons before choosing a harness. Historical scores from earlier task versions should not be pooled with these revised graders.

Run `python3 scripts/build_tasks.py` to regenerate the fixtures. The unit tests check reproducibility, reference answers, wrong answers, hardcoded public answers and malformed outputs. These checks do not call a model, build containers or launch a campaign.
