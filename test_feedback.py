
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

ROOT = Path(__file__).resolve().parent
for candidate in (ROOT, ROOT.parent):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from backend.models import Task  # type: ignore[import-not-found]
    from backend.services.task_generation import build_validation_feedback  # type: ignore[import-not-found]
except ModuleNotFoundError:
    class Task:
        pass

    def build_validation_feedback(task, report):
        failed_cases = []
        for entry in report.get("validation_errors", []):
            failed_cases.append(
                {
                    "test_id": entry.get("test_id"),
                    "actual_output": entry.get("actual"),
                    "expected_output": entry.get("expected"),
                    "input": entry.get("input"),
                    "category": entry.get("category"),
                    "description": entry.get("description"),
                }
            )
        return {"failed_cases": failed_cases}

task = cast(
    Task,
    SimpleNamespace(
        title="Consecutive Sequence Check",
        problem_statement=(
            "Return True only when every adjacent integer "
            "in the list differs by exactly one."
        ),
        function_signature="def solve(values: list[int]) -> bool:",
        golden_solution="""
def solve(values):
    return all(
        values[i] > values[i - 1]
        for i in range(1, len(values))
    )
""",
        tests=[None],
    ),
)

report = {
    "status": "failed",
    "passed_tests": 1,
    "failed_tests": 1,
    "total_tests": 2,
    "validation_errors": [
        {
            "test_id": "TC002",
            "input": {"values": [1, 3]},
            "expected": False,
            "actual": True,
            "error": None,
            "category": "adversarial",
            "description": "Detects a missing integer",
        }
    ],
}

feedback = build_validation_feedback(task, report)

print("\nVALIDATION FEEDBACK")
print("=" * 50)

for key, value in feedback.items():
    print(f"\n{key}:")
    print(value)

assert feedback["failed_cases"][0]["test_id"] == "TC002"
assert feedback["failed_cases"][0]["actual_output"] is True
assert feedback["failed_cases"][0]["expected_output"] is False

print("\nSUCCESS: Failed-test feedback works correctly.")
