
from typing import Any

from backend.schemas import TestCase


def repair_ascii_ordering(task) -> list[dict[str, Any]]:
    """
    Generate additional tests for frequency-descending ordering
    with ASCII-ascending tie-breaking.
    """

    return [
        {
            "test_id": "REPAIR_ASCII_001",
            "input": {"s": "bbaa"},
            "expected_output": [["a", 2], ["b", 2]],
            "category": "adversarial",
            "description": "Checks ASCII ordering for tied frequencies",
            "mandatory": True,
            "visibility": "hidden",
        },
        {
            "test_id": "REPAIR_ASCII_002",
            "input": {"s": "ccbbaa"},
            "expected_output": [
                ["a", 2],
                ["b", 2],
                ["c", 2],
            ],
            "category": "adversarial",
            "description": "Checks ASCII ordering across three tied characters",
            "mandatory": True,
            "visibility": "hidden",
        },
        {
            "test_id": "REPAIR_ASCII_003",
            "input": {"s": "Bbaa"},
            "expected_output": [
                ["a", 2],
                ["B", 1],
                ["b", 1],
            ],
            "category": "adversarial",
            "description": "Checks frequency priority and ASCII tie-breaking",
            "mandatory": True,
            "visibility": "hidden",
        },
    ]


def repair_task_tests(
    task,
    coverage_report: dict[str, Any],
) -> dict[str, Any]:
    """
    Repair supported missing requirements without changing
    the task's input or output contract.
    """

    missing = set(
        coverage_report.get("missing_requirements", [])
    )

    added_tests: list[dict[str, Any]] = []

    if "ascii_ordering" in missing:
        output_spec = (
            task.output_specification or ""
        ).lower()

        signature = (
            task.function_signature or ""
        ).lower()

        # Ordering can only be meaningfully tested when the
        # task contract explicitly returns an ordered list.
        if (
            "ordered list" not in output_spec
            or "list[" not in signature
        ):
            return {
                "status": "contract_conflict",
                "added_tests": [],
                "added_test_count": 0,
                "message": (
                    "ASCII ordering requires an ordered-list output "
                    "contract. The current task specifies an "
                    "incompatible output format."
                ),
            }

        existing_ids = {
            test.test_id for test in task.tests
        }

        for candidate in repair_ascii_ordering(task):
            if candidate["test_id"] not in existing_ids:
                added_tests.append(candidate)

    for test_data in added_tests:
        task.tests.append(
            TestCase.model_validate(test_data)
        )

    return {
        "status": "repaired" if added_tests else "no_repair",
        "added_tests": added_tests,
        "added_test_count": len(added_tests),
        "message": (
            "Additional tests generated."
            if added_tests
            else "No compatible automatic repair was available."
        ),
    }
