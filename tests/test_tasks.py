"""Grader regression checks using tiny fixture programs, never a model or Docker."""
import ast
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_tasks

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = ["startup", "ds-aggregation", "ds-retrieval", "general-reconciliation"]


def prepare(name, directory):
    task = ROOT / "tasks" / name
    shutil.copytree(task / "environment/inputs", directory, dirs_exist_ok=True)
    subprocess.run([sys.executable, str(task / "solution/solve.py")], cwd=directory,
                   check=True, capture_output=True, timeout=5)
    return task


def grade(task, directory):
    return subprocess.run([sys.executable, str(task / "tests/check.py")], cwd=directory,
                          capture_output=True, timeout=10)


@pytest.mark.parametrize("name", PIPELINES)
def test_hardcoded_public_output_fails_all_held_out_checks(name, tmp_path):
    task = prepare(name, tmp_path)
    public = json.loads((tmp_path / "answer.json").read_text())
    (tmp_path / "analyze.py").write_text(
        "import json,sys\nfrom pathlib import Path\n"
        + "Path(sys.argv[2]).write_text(" + repr(json.dumps(public)) + ")\n")
    assert grade(task, tmp_path).returncode != 0
    checks = json.loads((tmp_path / "criteria.json").read_text())["checks"]
    assert all(value for key, value in checks.items() if key.startswith("public_"))
    assert any(not value for key, value in checks.items() if key.startswith("hidden_"))
    # Both held-out cases run even when the first case fails.
    assert any(key.startswith("hidden_2_") for key in checks)


@pytest.mark.parametrize("name", PIPELINES)
def test_saved_answer_is_required_and_checked_independently(name, tmp_path):
    task = prepare(name, tmp_path)
    (tmp_path / "answer.json").write_text("{}")
    assert grade(task, tmp_path).returncode != 0
    checks = json.loads((tmp_path / "criteria.json").read_text())["checks"]
    assert checks["saved_public_schema"] is False
    assert all(value for key, value in checks.items() if key.startswith(("public_", "hidden")))


@pytest.mark.parametrize("actual,wanted", [(False, 0), (True, 1), (float("nan"), 0),
                                           (float("inf"), 1), ("0", 0), ({"a": 1, "extra": 0}, {"a": 1})])
def test_pipeline_comparison_rejects_invalid_numeric_values_and_extra_fields(actual, wanted):
    tree = ast.parse((ROOT / "scripts/templates/pipeline_check.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "compare")
    namespace = {"math": math}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "grader", "exec"), namespace)
    assert namespace["compare"](actual, wanted) is False


def test_task_generation_is_reproducible_and_matches_checked_in_files(tmp_path, monkeypatch):
    for relative in ("scripts/templates", "vendor/humaneval"):
        shutil.copytree(ROOT / relative, tmp_path / relative)
    monkeypatch.setattr(build_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(build_tasks, "TASKS", tmp_path / "tasks")
    build_tasks.main()
    first = {str(p.relative_to(tmp_path / "tasks")): p.read_bytes()
             for p in (tmp_path / "tasks").rglob("*") if p.is_file()}
    build_tasks.main()
    second = {str(p.relative_to(tmp_path / "tasks")): p.read_bytes()
              for p in (tmp_path / "tasks").rglob("*") if p.is_file()}
    assert first == second
    checked_in = {str(p.relative_to(ROOT / "tasks")): p.read_bytes()
                  for p in (ROOT / "tasks").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert first == checked_in
