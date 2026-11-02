from backend.services.quality import check_specification_coverage
from backend.schemas import Task
import json

with open("task_test.json", "r", encoding="utf-8") as f:
    data = json.load(f)

task = Task.model_validate(data)

result = check_specification_coverage(task)

print(json.dumps(result, indent=4))
