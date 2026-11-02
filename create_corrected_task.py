
from copy import deepcopy

from backend.services.validation import validate_task
from backend.schemas import Task, TestCase
from backend.database.db import SessionLocal, TaskRecord
import json


ORIGINAL_TASK_ID = "TASK_42D73854D896"

db = SessionLocal()

try:
    record = (
        db.query(TaskRecord)
        .filter(TaskRecord.task_id == ORIGINAL_TASK_ID)
        .order_by(TaskRecord.task_version.desc())
        .first()
    )

    if not record:
        raise RuntimeError("Original task not found")

    data = json.loads(record.record_json)

    # Preserve the original task and create a new version.
    data["task_version"] = record.task_version + 1

    data["title"] = "Character Frequency with Deterministic Ordering"

    data["problem_statement"] = (
        "Count the frequency of each character in a string. "
        "Return character-frequency pairs ordered by descending "
        "frequency. When frequencies are equal, order characters "
        "by ascending ASCII value."
    )

    data["output_specification"] = (
        "Return a list of [character, frequency] pairs. "
        "Sort by frequency descending, then ASCII value ascending."
    )

    data["function_signature"] = (
        "def solve(s: str) -> list[list[str | int]]:"
    )

    data["expected_behavior"] = (
        "Count each character. Sort characters by descending "
        "frequency, using ascending ASCII value to break ties."
    )

    data["golden_solution"] = '''def solve(s: str) -> list[list[str | int]]:
    freq = {}

    for char in s:
        freq[char] = freq.get(char, 0) + 1

    return [
        [char, count]
        for char, count in sorted(
            freq.items(),
            key=lambda item: (-item[1], ord(item[0]))
        )
    ]'''

    data["metadata"] = {
        **data.get("metadata", {}),
        "generation_type": "corrected_version",
        "parent_task_id": ORIGINAL_TASK_ID,
        "correction": "Explicit deterministic frequency ordering",
    }

    data["tests"] = [
        {
            "test_id": "TC001",
            "input": {"s": "hello"},
            "expected_output": [
                ["l", 2],
                ["e", 1],
                ["h", 1],
                ["o", 1],
            ],
            "category": "normal",
            "description": "Frequency ordering with different counts",
            "mandatory": True,
            "visibility": "public",
        },
        {
            "test_id": "TC002",
            "input": {"s": ""},
            "expected_output": [],
            "category": "edge",
            "description": "Empty string",
            "mandatory": True,
            "visibility": "public",
        },
        {
            "test_id": "TC003",
            "input": {"s": "bbaa"},
            "expected_output": [["a", 2], ["b", 2]],
            "category": "adversarial",
            "description": "ASCII ordering for tied frequencies",
            "mandatory": True,
            "visibility": "hidden",
        },
        {
            "test_id": "TC004",
            "input": {"s": "ccbbaa"},
            "expected_output": [
                ["a", 2],
                ["b", 2],
                ["c", 2],
            ],
            "category": "adversarial",
            "description": "Three characters with tied frequencies",
            "mandatory": True,
            "visibility": "hidden",
        },
        {
            "test_id": "TC005",
            "input": {"s": "Bbaa"},
            "expected_output": [
                ["a", 2],
                ["B", 1],
                ["b", 1],
            ],
            "category": "adversarial",
            "description": "Frequency ordering and ASCII tie-breaking",
            "mandatory": True,
            "visibility": "hidden",
        },
        {
            "test_id": "TC006",
            "input": {"s": "a"},
            "expected_output": [["a", 1]],
            "category": "edge",
            "description": "Single character",
            "mandatory": True,
            "visibility": "public",
        },
        {
            "test_id": "TC007",
            "input": {"s": "zzzyyyxxx"},
            "expected_output": [
                ["x", 3],
                ["y", 3],
                ["z", 3],
            ],
            "category": "adversarial",
            "description": "Multiple tied frequencies",
            "mandatory": True,
            "visibility": "hidden",
        },
        {
            "test_id": "TC008",
            "input": {"s": "aabbccc"},
            "expected_output": [
                ["c", 3],
                ["a", 2],
                ["b", 2],
            ],
            "category": "normal",
            "description": "Frequency priority takes precedence over ASCII",
            "mandatory": True,
            "visibility": "public",
        },
    ]

    task = Task.model_validate(data)

    report = validate_task(task)

    print("Validation:", report["status"])
    print(
        f"Golden solution: "
        f'{report["passed_tests"]}/{report["total_tests"]}'
    )

    if report["status"] != "passed":
        raise RuntimeError("Corrected task failed golden validation")

    task.validation_status = "passed"

    db.add(
        TaskRecord(
            task_id=task.task_id,
            task_version=task.task_version,
            record_json=task.model_dump_json(),
        )
    )

    db.commit()

    print("Corrected task saved successfully")
    print("Task ID:", task.task_id)
    print("Version:", task.task_version)

except Exception:
    db.rollback()
    raise

finally:
    db.close()
