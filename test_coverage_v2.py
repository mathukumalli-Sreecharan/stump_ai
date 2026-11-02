
import json
from pathlib import Path

from backend.database.db import SessionLocal, TaskRecord
from backend.schemas import Task
from backend.services.quality import check_specification_coverage

TASK_ID = "TASK_42D73854D896"

task = None
with SessionLocal() as db:
    record = (
        db.query(TaskRecord)
        .filter(
            TaskRecord.task_id == TASK_ID,
            TaskRecord.task_version == 2,
        )
        .first()
    )
    if record:
        task = Task.model_validate_json(record.record_json)

# Keep this standalone diagnostic repeatable on a fresh checkout. The named
# historical record is optional; task_test.json is the checked-in fixture.
if task is None:
    fixture = Path(__file__).with_name("task_test.json")
    task = Task.model_validate_json(fixture.read_text(encoding="utf-8"))
    print(f"Historical task {TASK_ID} v2 not found; using {fixture.name}.")

result = check_specification_coverage(task)
print(json.dumps(result, indent=4))
