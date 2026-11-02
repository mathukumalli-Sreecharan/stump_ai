# ModelStump architecture

## Request and data flow

1. FastAPI exposes the local API without authentication.
2. Task generation calls the configured generator Ollama model, validates JSON and schema requirements, repairs supported test-coverage gaps, executes the golden solution, scores quality, checks diversity, and stores the full versioned task JSON.
3. Task evaluation sends only the task contract to the selected target model. It does not send tests, expected outputs, private validation reports, or the golden solution.
4. The target response is extracted and executed against all public and hidden test cases. Full response, test results, and failure evidence are stored internally; API serializers return aggregates only.
5. Failure analysis classifies evidence. Weakness aggregation counts distinct task IDs, not the number of failing tests. Adaptive generation requires recurring evidence and stores parent task/evaluation references in task metadata.
6. Public dataset exports contain allowlisted public fields. Internal exports require explicit admin selection and use separate timestamped files.

## Persistence

SQLite contains task JSON keyed by `(task_id, task_version)`, evaluation JSON, and background-job status. Existing evaluation records receive `NULL` for the new task-version column when the original version cannot be established. No record is deleted or rewritten by this additive schema change.

Pipeline jobs run in a two-worker local thread pool and are persisted before dispatch. Status is `queued`, `running`, `completed`, `failed`, or `cancelled`. A restart marks queued/running jobs failed; work is not resumed. Direct generation/evaluation endpoints still run synchronously.

## Execution boundary

Services call the execution-backend interface in `backend/execution/service.py`. Only `unsafe_subprocess` is implemented. It isolates a working directory and filters inherited environment variables but does not provide OS-level containment. Health reports `secure: false`. Do not treat it as safe for untrusted code.

## Local configuration

Configuration is loaded from the project `.env` file, while exported environment variables take precedence. See [README.md](../README.md) for PowerShell setup and startup commands.
