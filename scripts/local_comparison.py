"""Plan a local comparison, run it explicitly, or inspect a saved campaign."""
import argparse
import csv
import json
import os
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def comparison_command(model, harnesses, suite, attempts):
    if not model.strip() or attempts < 1:
        raise ValueError("Choose a model tag and at least one attempt.")
    command = [str(ROOT / "bench"), "local", "--model", model,
               "--suite", suite, "--attempts", str(attempts)]
    for harness in harnesses:
        command.extend(["--harness", harness])
    return command


def saved_campaigns():
    campaigns = []
    for path in sorted((ROOT / "runs/campaigns").glob("*/manifest.json"), reverse=True):
        if json.loads(path.read_text()).get("local") and (path.parent / "results.csv").is_file():
            campaigns.append(path.parent)
    return campaigns


def read_results(campaign):
    with (Path(campaign) / "results.csv").open(newline="") as source:
        return list(csv.DictReader(source))



def run_comparison(model, harnesses, suite="demo", attempts=1):
    """Run a local campaign in the notebook kernel with per-trial progress."""
    from tqdm.auto import tqdm

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import bench

    plan = bench.build_plan(
        suite, harnesses, dict.fromkeys(harnesses, model), attempts, local=True
    )
    campaign = None
    with tqdm(total=plan["runs"], desc="Harness comparison", unit="trial") as bar:
        def progress(event, data):
            nonlocal campaign
            if event == "campaign":
                campaign = data["path"]
            elif event == "trial_start":
                bar.set_postfix(harness=data["harness"], task=data["task"], status="running")
            elif event == "trial_end":
                result = data["result"]
                error = result.get("exception_info") or {}
                rewards = (result.get("verifier_result") or {}).get("rewards") or {}
                status = error.get("exception_type") or (
                    "passed" if rewards.get("reward") == 1 else
                    "failed" if rewards else "incomplete"
                )
                bar.set_postfix(harness=data["harness"], task=data["task"], status=status)
                bar.update(1)

        bench.execute(plan, progress=progress)
    return campaign


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="lfm3:1.7b")
    parser.add_argument("--harness", action="append", choices=["pi", "opencode", "droid", "dsh"])
    parser.add_argument("--suite", choices=["demo", "smoke", "quick", "full"], default="demo")
    parser.add_argument("--attempts", type=int, default=1)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Start the comparison in this terminal")
    mode.add_argument("--results", type=Path, metavar="CAMPAIGN", help="Read an existing campaign folder")
    args = parser.parse_args()
    if args.results:
        print(json.dumps(read_results(args.results), indent=2))
        return
    command = comparison_command(args.model, args.harness or ["pi", "opencode"],
                                 args.suite, args.attempts)
    if args.run:
        os.execv(command[0], command)
    print(shlex.join(command))


if __name__ == "__main__":
    main()
