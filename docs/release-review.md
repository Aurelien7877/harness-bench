# Publication review, 9 November 2026

This review concerns the repository and its lightweight checks. No model,
container, paid inference or benchmark campaign was run for the review.

## Evaluation checks

- Nine tasks across six categories, with clear deliverables and pass rules.
- Four script tasks check a saved answer, a public rerun and two held-out inputs.
- Regression checks reject sample-only code, changed saved answers, malformed
  numbers, booleans used as numbers and missing or extra fields.
- Task generation is reproducible. HumanEval data retains its original license.
- Startup is separate from work success. Tables show trial counts, measurement
  coverage and missing values. Models are not silently pooled.
- Configuration validation covers seven harness integrations. This is not a
  claim that every harness and model combination successfully runs end to end.

## Publication checks

The release gate checks tracked files, reachable branch/tag/remote history,
commit messages and author/committer email metadata. It looks for known secret
formats, private paths, runtime files, notebook outputs, oversized files and
active or external SVG resources. Local stashes and private run folders are
excluded from normal publication. The GitHub inventory contained one branch,
with no tags, pull requests, releases, issues or Actions artifacts at review time.

Host credentials are allowlisted. The execution subprocess uses an isolated
home. CI has read-only repository permission, pinned action revisions and no
provider credentials. CI runs unit checks, not benchmark campaigns.

The OSV advisory database was queried for all 95 pinned Python packages.
It identified advisories affecting the original filelock pin. The lockfile now
uses filelock 4.2.1 and the compatible LiteLLM 1.108.3 patch. The revised pins
returned no known advisories in that query. Their dependency constraints and
the unit checks were validated using temporary test packages without changing
the user's environment. See an example [upstream advisory](https://osv.dev/vulnerability/GHSA-v4x8-3wr5-3wq8).

These are bounded checks, not a guarantee that every secret format or future
vulnerability is absent. The advisory query covered Python packages, not the
Docker base image, operating-system packages or downloaded agent binaries.
Container installation and model execution still require separate validation.
