import json
from pathlib import Path

from backend.schemas import PublicTask, PublicTestCase, Task


def export_jsonl(
    tasks: list[Task],
    path: Path,
    include_solution: bool = False,
) -> int:
    """Export allowlisted public tasks by default; internal mode is explicit."""
    count = 0
    with path.open("x", encoding="utf-8") as output:
        for task in tasks:
            if include_solution:
                row = task.model_dump(mode="json")
                row["tests"] = [
                    test
                    for test in row["tests"]
                    if str(test.get("visibility", "")).lower() == "public"
                ]
            else:
                row = PublicTask(
                    task_id=task.task_id,
                    task_version=task.task_version,
                    category=task.category,
                    difficulty=task.difficulty,
                    title=task.title,
                    problem_statement=task.problem_statement,
                    input_specification=task.input_specification,
                    output_specification=task.output_specification,
                    constraints=task.constraints,
                    function_signature=task.function_signature,
                    generated_at=task.generated_at,
                    tests=[
                        PublicTestCase(
                            test_id=test.test_id,
                            input=test.input,
                            category=test.category,
                            description=test.description,
                        )
                        for test in task.tests
                        if str(test.visibility).lower() == "public"
                    ],
                    validation_status=task.validation_status,
                    quality_score=task.quality_score,
                ).model_dump(mode="json")
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count
