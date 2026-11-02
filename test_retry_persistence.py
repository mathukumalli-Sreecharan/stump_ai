
import json

from backend.main import save_task, get_task
from backend.schemas import Task, Difficulty, TestCase
from backend.database.db import SessionLocal, TaskRecord


def main():
    test_task_id = "TASK_RETRY_PERSISTENCE_TEST"

    retry_history = [
        {
            "attempt": 1,
            "status": "failed",
            "error": "ValueError: Golden solution failed validation: 6/8 passed",
            "archetype": "string_frequency",
            "feedback_sent_to_next_attempt": {
                "failed_tests": [
                    {
                        "test_id": "TC002",
                        "expected_output": False,
                        "actual_output": True,
                    }
                ]
            },
        },
        {
            "attempt": 2,
            "status": "passed",
            "error": None,
            "archetype": "intervals",
            "validation": {
                "status": "passed",
                "passed_tests": 8,
                "failed_tests": 0,
                "total_tests": 8,
            },
            "coverage_score": 100,
        },
    ]

    task = Task(
        task_id=test_task_id,
        task_version=1,
        difficulty=Difficulty.easy,
        title="Retry persistence test",
        problem_statement="Test database persistence of retry history.",
        input_specification="No input.",
        output_specification="A boolean.",
        expected_behavior="Return True.",
        function_signature="def solve():",
        time_complexity="O(1)",
        generation_model="mock-model",
        golden_solution="def solve():\n    return True",
        tests=[
            TestCase(test_id="TC001", input={}, expected_output=True),
            TestCase(test_id="TC002", input={}, expected_output=True),
            TestCase(test_id="TC003", input={}, expected_output=True),
            TestCase(test_id="TC004", input={}, expected_output=True),
            TestCase(test_id="TC005", input={}, expected_output=True),
        ],
        metadata={
            "retry_history": retry_history,
            "generation_attempts": 2,
            "test_marker": "retry_persistence_check",
        },
    )

    try:
        # Save task to SQLite.
        save_task(task)

        print("Task saved to SQLite.")

        # Retrieve task using the existing database helper.
        restored_task = get_task(test_task_id)

        restored_history = restored_task.metadata.get(
            "retry_history",
            [],
        )

        print("\nRESTORED RETRY HISTORY")
        print("=" * 55)

        print(json.dumps(restored_history, indent=2))

        # Verify history.
        assert len(restored_history) == 2

        assert restored_history[0]["status"] == "failed"
        assert restored_history[0]["attempt"] == 1

        assert restored_history[1]["status"] == "passed"
        assert restored_history[1]["attempt"] == 2

        assert restored_task.metadata["generation_attempts"] == 2

        assert (
            restored_task.metadata["test_marker"]
            == "retry_persistence_check"
        )

        print("\nSUCCESS: Retry history survived SQLite round-trip.")

    finally:
        # Remove only the temporary test record.
        with SessionLocal() as db:
            row = db.get(
                TaskRecord,
                (test_task_id, 1),
            )

            if row is not None:
                db.delete(row)
                db.commit()

        print("Temporary test record cleaned up.")


if __name__ == "__main__":
    main()
