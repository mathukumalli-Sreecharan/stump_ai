import json
import asyncio
from pathlib import Path
import pytest
from backend.schemas import Task, TestCase
from backend.execution.runner import run_cases, validate_source
from backend.services.quality import score_task
from backend.services.dataset_exporter import export_jsonl
from backend.services.validation import get_function_name
from backend.services import task_generation
from backend.services.task_generation import build_validation_feedback, validate_generated_data

def make_task():
    cases = [([1], 1), ([], 0), ([1, 2], 3), ([-1, 2], 1), ([2, 2], 4), ([0], 0), ([3, -3], 0), ([8, 9, 10], 27)]
    return Task(difficulty="easy",title="Sum",problem_statement="Sum values",input_specification="values list",output_specification="int",expected_behavior="sum",function_signature="def solve(values):",time_complexity="O(n)",generation_model="test",golden_solution="def solve(values): return sum(values)",tests=[TestCase(test_id=f"T{i}",input={"values":v},expected_output=o,visibility="public" if i<2 else "hidden") for i,(v,o) in enumerate(cases)])

def test_ast_signature_and_execution():
    assert validate_source("def solve(x): return x", "solve") is None
    assert validate_source("def other(x): return x", "solve")
    result=run_cases("def solve(values): return sum(values)","solve",[{"input":{"values":[2,3]},"expected_output":5}])
    assert result["status"]=="complete"

def test_validation_rejects_syntax_and_imports():
    assert validate_source("def solve(:", "solve").startswith("SyntaxError")
    assert validate_source("import socket\ndef solve(x): return x", "solve")

def test_candidate_runner_does_not_inherit_application_secrets(monkeypatch):
    monkeypatch.setenv("MODELSTUMP_AUDIT_SECRET", "do-not-pass")
    result = run_cases(
        "import os\ndef solve():\n    return 'MODELSTUMP_AUDIT_SECRET' in os.environ",
        "solve",
        [{"input": {}, "expected_output": False}],
    )
    assert result["status"] == "complete"
    assert result["results"][0]["ok"] is True

def test_signature_name_accepts_omitted_trailing_colon():
    assert get_function_name("def solve(values, k=1)") == "solve"
    assert get_function_name("def solve(values, k=1):") == "solve"

def test_generated_numeric_test_ids_are_normalized():
    record = {
        "title": "Example", "problem_statement": "Do something", "input_specification": "x",
        "output_specification": "y", "constraints": [], "expected_behavior": "works",
        "function_signature": "def solve(x):", "edge_case_requirements": [],
        "time_complexity": "O(1)", "golden_solution": "def solve(x): return x",
        "tests": [
            {"test_id": i, "input": {"x": i}, "expected_output": i, "category": "normal",
             "description": "identity", "mandatory": True,
                 "visibility": "public" if i <= 2 else "hidden"}
            for i in range(1, 9)
        ],
    }
    validate_generated_data(record)
    assert record["tests"][0]["test_id"] == "TC001"

def test_generated_cases_require_mandatory_and_nonredundant_tests():
    record = make_task().model_dump(mode="json")
    for test in record["tests"]:
        test["mandatory"] = False
    with pytest.raises(ValueError, match="must be mandatory"):
        validate_generated_data(record)

    record = make_task().model_dump(mode="json")
    record["tests"][1]["input"] = record["tests"][0]["input"]
    record["tests"][1]["expected_output"] = record["tests"][0]["expected_output"]
    with pytest.raises(ValueError, match="duplicates an existing"):
        validate_generated_data(record)

def test_retry_feedback_includes_failed_case_evidence():
    task = make_task()
    report = {
        "status": "failed", "passed_tests": 7, "failed_tests": 1, "total_tests": 8,
        "validation_errors": [{"test_id": "T2", "input": {"values": [1, 2]},
                               "expected": 3, "actual": 2, "error": None,
                               "category": "normal", "description": "example mismatch"}],
    }
    feedback = build_validation_feedback(task, report)
    assert feedback["failed_cases"][0]["test_id"] == "T2"
    assert feedback["failed_cases"][0]["expected_output"] == 3
    assert feedback["failed_cases"][0]["actual_output"] == 2
    assert feedback["rejected_golden_solution"] == task.golden_solution

def test_generation_retry_sends_validation_feedback(monkeypatch):
    task = make_task()
    prompts = []
    calls = 0

    class FakeProvider:
        def __init__(self, model): pass
        async def available(self): return True
        async def generate(self, prompt, system):
            prompts.append(prompt)
            return json.dumps(task.model_dump(mode="json"))

    def fake_validate(_task):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"status":"failed", "passed_tests":7, "failed_tests":1, "total_tests":8,
                    "validation_errors":[{"test_id":"T2","input":{"values":[1,2]},
                                           "expected":3,"actual":2,"error":None}]}
        return {"status":"passed", "passed_tests":8, "failed_tests":0, "total_tests":8,
                "validation_errors":[], "results":[{"ok":True} for _ in range(8)]}

    monkeypatch.setattr(task_generation, "OllamaProvider", FakeProvider)
    monkeypatch.setattr(task_generation, "validate_task", fake_validate)
    monkeypatch.setattr(task_generation, "check_specification_coverage", lambda _task: {
        "score": 100, "critical_missing": [], "missing_requirements": [],
        "critical_requirements_satisfied": True,
    })
    monkeypatch.setattr(task_generation, "repair_task_tests", lambda *_: {
        "status": "no_repair", "added_tests": [], "added_test_count": 0,
        "message": "No repair needed",
    })
    monkeypatch.setattr(task_generation, "build_diversity_feedback", lambda *_: {
        "similarity": 0.1, "status": "unique", "most_similar_task_id": None,
    })
    result = asyncio.run(task_generation.generate_task("easy", "lists"))

    assert result.title == task.title
    assert len(prompts) == 2
    assert "RETRY INSTRUCTIONS:" in prompts[1]
    assert '"failed_cases"' in prompts[1]
    assert '"test_id": "T2"' in prompts[1]
    assert '"actual_output": 2' in prompts[1]

def test_quality_requires_valid_golden():
    task=make_task()
    assert score_task(task,{"status":"passed","failed_tests":0})["accepted"]
    assert not score_task(task,{"status":"failed","failed_tests":1})["accepted"]

def test_export_jsonl_only_public_cases(tmp_path: Path):
    task=make_task(); out=tmp_path/"tasks.jsonl"
    assert export_jsonl([task],out)==1
    data=json.loads(out.read_text(encoding="utf-8"))
    assert len(data["tests"]) == 2
    assert "golden_solution" not in data and "metadata" not in data
    assert all("expected_output" not in test for test in data["tests"])
