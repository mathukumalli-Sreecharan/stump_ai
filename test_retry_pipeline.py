
import asyncio
import json
from unittest.mock import patch

from backend.services.task_generation import generate_task


def make_candidate(correct: bool) -> dict:
    if correct:
        solution = """
def solve(values):
    return all(
        values[i] == values[i - 1] + 1
        for i in range(1, len(values))
    )
"""
    else:
        solution = """
def solve(values):
    return all(
        values[i] > values[i - 1]
        for i in range(1, len(values))
    )
"""

    return {
        "title": "Check consecutive integers",
        "problem_statement": (
            "Return True when every adjacent integer "
            "differs by exactly one. Otherwise return False."
        ),
        "input_specification": "A list of integers named values.",
        "output_specification": "Return a boolean.",
        "constraints": [
            "The list can be empty.",
            "The list can contain negative integers.",
        ],
        "expected_behavior": (
            "Every element after the first must equal "
            "the previous element plus one."
        ),
        "function_signature": "def solve(values: list[int]) -> bool:",
        "edge_case_requirements": [
            "Empty list",
            "Single element",
            "Negative integers",
            "Missing integers",
        ],
        "time_complexity": "O(n)",
        "golden_solution": solution,
        "tests": [
            {
                "test_id": "TC001",
                "input": {"values": [1, 2, 3]},
                "expected_output": True,
                "category": "normal",
                "description": "Consecutive integers",
                "mandatory": True,
                "visibility": "public",
            },
            {
                "test_id": "TC002",
                "input": {"values": [1, 3]},
                "expected_output": False,
                "category": "adversarial",
                "description": "Detects a missing integer",
                "mandatory": True,
                "visibility": "public",
            },
            {
                "test_id": "TC003",
                "input": {"values": []},
                "expected_output": True,
                "category": "edge",
                "description": "Empty list",
                "mandatory": True,
                "visibility": "hidden",
            },
            {
                "test_id": "TC004",
                "input": {"values": [-3, -2, -1]},
                "expected_output": True,
                "category": "edge",
                "description": "Negative consecutive integers",
                "mandatory": True,
                "visibility": "hidden",
            },
            {
                "test_id": "TC005",
                "input": {"values": [1]},
                "expected_output": True,
                "category": "edge",
                "description": "Single element",
                "mandatory": True,
                "visibility": "hidden",
            },
            {
                "test_id": "TC006",
                "input": {"values": [2, 4, 5]},
                "expected_output": False,
                "category": "adversarial",
                "description": "Gap between first two values",
                "mandatory": True,
                "visibility": "hidden",
            },
            {
                "test_id": "TC007",
                "input": {"values": [1, 2, 2, 3]},
                "expected_output": False,
                "category": "edge",
                "description": "Duplicate values",
                "mandatory": True,
                "visibility": "hidden",
            },
            {
                "test_id": "TC008",
                "input": {"values": [5, 4, 3]},
                "expected_output": False,
                "category": "normal",
                "description": "Descending values",
                "mandatory": True,
                "visibility": "hidden",
            },
        ],
    }


class MockProvider:
    def __init__(self, model):
        self.model = model
        self.call_count = 0
        self.prompts = []

    async def available(self):
        return True

    async def generate(self, prompt, system_prompt):
        self.call_count += 1
        self.prompts.append(prompt)

        candidate = make_candidate(
            correct=self.call_count >= 2
        )

        return json.dumps(candidate)


async def main():
    mock_provider = MockProvider("mock-model")

    with (
        patch(
            "backend.services.task_generation.OllamaProvider",
            return_value=mock_provider,
        ),
        patch(
            "backend.services.task_generation.check_specification_coverage",
            return_value={
                "score": 100,
                "total_requirements": 0,
                "covered_requirements": [],
                "missing_requirements": [],
                "critical_missing": [],
                "critical_requirements_satisfied": True,
                "status": "complete",
            },
        ),
        patch(
            "backend.services.task_generation.repair_task_tests",
            return_value={
                "status": "no_repair",
                "added_tests": [],
                "added_test_count": 0,
                "message": "No repair needed",
            },
        ),
        patch(
            "backend.services.task_generation.build_diversity_feedback",
            return_value={
                "similarity": 0.1,
                "status": "unique",
                "most_similar_task_id": None,
            },
        ),
    ):
        task = await generate_task(
            difficulty="easy",
            topic="consecutive integer validation",
            existing_tasks=[],
        )

    print("\nMOCKED RETRY PIPELINE RESULTS")
    print("=" * 55)

    print("Generation calls:", mock_provider.call_count)
    print("Generated task:", task.title)
    print("Golden solution validation: passed")

    # Verify two generation attempts occurred.
    assert mock_provider.call_count == 2

    # Verify that attempt 2 received actual failure feedback.
    second_prompt = mock_provider.prompts[1]

    assert "RETRY INSTRUCTIONS" in second_prompt
    assert "TC002" in second_prompt
    assert '"actual_output": true' in second_prompt
    assert '"expected_output": false' in second_prompt

    print("\nFirst attempt: failed as expected")
    print("Failed test: TC002")
    print("Second attempt: received correction feedback")
    print("Second attempt: corrected golden solution")

    # Verify retry history was saved in task metadata.
    retry_history = task.metadata.get("retry_history", [])
    generation_attempts = task.metadata.get("generation_attempts")

    assert len(retry_history) == 2, (
        f"Expected 2 retry history entries, got {len(retry_history)}"
    )

    first_attempt = retry_history[0]
    second_attempt = retry_history[1]

    assert first_attempt.get("attempt") == 1
    assert first_attempt.get("status") == "failed"
    assert first_attempt.get("archetype") == second_attempt.get("archetype"), (
        "A repair retry must keep the failed task's archetype"
    )

    assert second_attempt.get("attempt") == 2
    assert second_attempt.get("status") == "passed"

    assert generation_attempts == 2

    # Verify successful validation details were recorded.
    validation_history = second_attempt.get("validation", {})

    assert validation_history.get("status") == "passed"
    assert validation_history.get("failed_tests") == 0

    print("\nRETRY HISTORY")
    print("=" * 55)

    print(json.dumps(retry_history, indent=2))

    print("\nGeneration attempts:", generation_attempts)

    print("\nSUCCESS: Retry history and metadata verified.")


if __name__ == "__main__":
    asyncio.run(main())
