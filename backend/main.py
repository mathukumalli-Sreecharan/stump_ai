
import json
import logging
import inspect
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import GENERATOR_MODEL, TARGET_MODEL, ROOT
from backend.execution.service import execution_status
from backend.database.db import (
    SessionLocal,
    TaskRecord,
    EvaluationRecord,
)
from backend.schemas import (
    Task,
    GenerateRequest,
    EvaluateRequest,
    PublicTask,
    PublicTestCase,
)
from backend.services.validation import validate_task
from backend.services.quality import score_task
from backend.services.evaluator import evaluate_task
from backend.services.dataset_exporter import export_jsonl
from backend.services.weakness_analyzer import analyze_weaknesses
from backend.services.job_manager import (
    cancel_job,
    get_job as read_job,
    mark_orphaned_jobs_failed,
    submit_job,
)

try:
    import backend.services.task_generation as task_generation
except ImportError:
    task_generation = None


# ==================================================
# REQUEST SCHEMAS
# ==================================================

class AdaptiveGenerateRequest(BaseModel):
    model: str | None = None
    difficulty: str = "medium"
    count: int = Field(default=1, ge=1, le=5)
    min_task_occurrences: int = Field(default=2, ge=2, le=20)


# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("modelstump")


@asynccontextmanager
async def lifespan(_app):
    count = mark_orphaned_jobs_failed()
    if count:
        logger.warning("Marked %s interrupted background jobs as failed", count)
    yield


# ==================================================
# FASTAPI
# ==================================================

app = FastAPI(
    title="ModelStump API",
    version="0.3.0",
    description="Local LLM benchmark generation and evaluation",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_request_limits: dict[tuple[str, str], list[float]] = {}


@app.middleware("http")
async def protect_api(request: Request, call_next):
    """Apply request-size and process-local rate limits to API requests."""
    path = request.url.path
    if not path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)

    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
    if content_length > 1_000_000:
        return JSONResponse(status_code=413, content={"detail": "Request body is too large"})

    client_ip = request.client.host if request.client else "unknown"
    limit_key = (client_ip, path)
    now = time.monotonic()
    recent = [stamp for stamp in _request_limits.get(limit_key, []) if now - stamp < 60]
    expensive = request.method == "POST" and (
        path in {
            "/api/tasks/generate",
            "/api/pipeline/run",
            "/api/adaptive-generation/run",
        }
        or path.endswith("/evaluate")
    )
    cap = 4 if expensive else 120
    if len(recent) >= cap:
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    recent.append(now)
    _request_limits[limit_key] = recent
    if len(_request_limits) > 1000:
        for old_key, timestamps in list(_request_limits.items()):
            fresh = [stamp for stamp in timestamps if now - stamp < 60]
            if fresh:
                _request_limits[old_key] = fresh
            else:
                _request_limits.pop(old_key, None)

    return await call_next(request)


# ==================================================
# GENERATION SERVICE
# ==================================================

async def generate_task(*args, **kwargs):
    if task_generation is None:
        raise RuntimeError("Task generation service is unavailable")

    generate_fn = getattr(task_generation, "generate_task", None)

    if generate_fn is None:
        raise RuntimeError("generate_task function is unavailable")

    result = generate_fn(*args, **kwargs)

    if inspect.isawaitable(result):
        return await result

    return result


# ==================================================
# DATABASE HELPERS
# ==================================================

def save_task(task):
    try:
        with SessionLocal() as db:
            row = db.get(
                TaskRecord,
                {
                    "task_id": task.task_id,
                    "task_version": task.task_version,
                },
            )

            if row is None:
                row = TaskRecord(
                    task_id=task.task_id,
                    task_version=task.task_version,
                    record_json=task.model_dump_json(),
                )
                db.add(row)
            else:
                row.record_json = task.model_dump_json()

            db.commit()

        logger.info("Task saved successfully: %s", task.task_id)

    except Exception:
        logger.exception(
            "Database error while saving task: %s",
            task.task_id,
        )
        raise


def get_task(task_id: str, task_version: int | None = None):
    with SessionLocal() as db:
        query = db.query(TaskRecord).filter_by(task_id=task_id)
        if task_version is not None:
            query = query.filter_by(task_version=task_version)
        else:
            query = query.order_by(TaskRecord.task_version.desc())
        row = query.first()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        return Task.model_validate_json(row.record_json)


def serialize_public_task(task: Task) -> dict:
    """
    Return only fields safe for public task access.

    Golden solutions, expected outputs, and hidden tests
    are deliberately excluded.
    """

    public_tests = [
        PublicTestCase(
            test_id=test.test_id,
            input=test.input,
            category=test.category,
            description=test.description,
        )
        for test in task.tests
        if str(
            getattr(test.visibility, "value", test.visibility)
        ).lower() == "public"
    ]

    public_task = PublicTask(
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
        tests=public_tests,
        validation_status=task.validation_status,
        quality_score=task.quality_score,
    )

    return public_task.model_dump(mode="json")


def serialize_validation_summary(
    report: dict,
    task_status: str | None = None,
) -> dict:
    """Expose aggregate validation results without test evidence."""
    return {
        "status": task_status or report.get("status", "unknown"),
        "golden_solution_status": report.get("status", "unknown"),
        "total_tests": report.get("total_tests", 0),
        "passed_tests": report.get("passed_tests", 0),
        "failed_tests": report.get("failed_tests", 0),
    }


def serialize_quality_summary(quality: dict) -> dict:
    """Expose benchmark quality separately from target performance."""
    return {
        "score": quality.get("score", 0),
        "accepted": bool(quality.get("accepted", False)),
    }


def serialize_evaluation(result: dict) -> dict:
    """Allowlist evaluation data safe for API clients."""
    summary = {
        key: result[key]
        for key in (
            "evaluation_id", "task_id", "task_version", "model", "evaluated_at", "task_passed",
            "status", "passed_tests", "failed_tests", "total_tests",
            "elapsed_seconds", "test_summary",
        )
        if key in result
    }
    summary["failure_summary"] = [
        {
            "failure_type": report.get("failure_type", "unknown"),
            "weakness_label": report.get("weakness_label"),
            "severity": report.get("severity"),
        }
        for report in result.get("failure_reports", [])
    ]
    return summary


def serialize_weakness(weakness: dict) -> dict:
    """Return aggregate weakness data without internal failure evidence."""
    return {
        key: value
        for key, value in weakness.items()
        if key not in {"examples", "evidence"}
    }


def get_all_tasks():
    with SessionLocal() as db:
        records = db.query(TaskRecord).all()

        return [
            json.loads(record.record_json)
            for record in records
        ]


def get_task_page(limit: int, offset: int) -> list[dict]:
    with SessionLocal() as db:
        records = (
            db.query(TaskRecord)
            .order_by(TaskRecord.task_id, TaskRecord.task_version.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [json.loads(record.record_json) for record in records]


def get_all_evaluations(model: str | None = None):
    with SessionLocal() as db:
        query = db.query(EvaluationRecord)

        if model:
            query = query.filter(EvaluationRecord.model == model)

        records = query.all()

        return [
            json.loads(record.result_json)
            for record in records
        ]


def get_evaluation_page(
    model: str | None,
    limit: int,
    offset: int,
) -> list[dict]:
    with SessionLocal() as db:
        query = db.query(EvaluationRecord)
        if model:
            query = query.filter(EvaluationRecord.model == model)
        records = (
            query.order_by(EvaluationRecord.evaluation_id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [json.loads(record.result_json) for record in records]


# ==================================================
# TASK DIVERSITY HELPERS
# ==================================================

def get_existing_task_objects(exclude_task_id: str | None = None):
    """
    Return accepted tasks for diversity comparison.

    Rejected tasks remain in the database for audit purposes,
    but do not become benchmark diversity references.
    """

    existing = []

    for item in get_all_tasks():

        if exclude_task_id and item.get("task_id") == exclude_task_id:
            continue

        if item.get("validation_status") != "passed":
            continue

        try:
            existing.append(Task.model_validate(item))

        except Exception:
            logger.warning(
                "Skipping invalid stored task during diversity comparison: %s",
                item.get("task_id"),
            )

    return existing


def calculate_task_quality(task, validation):

    existing_tasks = get_existing_task_objects(
        exclude_task_id=task.task_id
    )

    return score_task(
        task,
        validation,
        existing_tasks=existing_tasks,
    )


# ==================================================
# HEALTH
# ==================================================

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "generator_model": GENERATOR_MODEL,
        "target_model": TARGET_MODEL,
        "execution": execution_status(),
    }


# ==================================================
# TASK GENERATION
# ==================================================

@app.post("/api/tasks/generate")
async def generate(req: GenerateRequest):

    logger.info(
        "Task generation requested | Topic: %s | Difficulty: %s | Count: %s",
        req.topic,
        req.difficulty,
        req.count,
    )

    generated_tasks = []

    for index in range(req.count):

        try:

            logger.info(
                "Generating task %s of %s",
                index + 1,
                req.count,
            )

            existing_tasks = get_existing_task_objects()

            task = await generate_task(
                req.difficulty.value,
                req.topic,
                existing_tasks=existing_tasks,
            )

            report = validate_task(task)

            quality = score_task(
                task,
                report,
                existing_tasks=existing_tasks,
            )

            task.validation_status = (
                "passed"
                if (
                    report.get("status") == "passed"
                    and quality.get("accepted")
                )
                else "rejected"
            )

            task.quality_score = quality["score"]

            save_task(task)

            # Return only the public task representation.
            generated_tasks.append({
                "task": serialize_public_task(task),
                "validation": serialize_validation_summary(
                    report,
                    task.validation_status,
                ),
                "quality": serialize_quality_summary(quality),
            })

            logger.info(
                "Task generated | ID: %s | Quality: %s | "
                "Accepted: %s | Diversity: %s",
                task.task_id,
                quality.get("score"),
                quality.get("accepted"),
                quality.get("diversity", {}).get("status"),
            )

        except HTTPException:
            raise

        except Exception as exc:

            logger.exception(
                "Task generation failed | Task %s",
                index + 1,
            )

            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Task generation failed",
                    "error_type": type(exc).__name__,
                    "task_number": index + 1,
                },
            ) from exc

    return {
        "tasks": generated_tasks,
        "total_generated": len(generated_tasks),
    }


# ==================================================
# TASK VALIDATION
# ==================================================

@app.post("/api/tasks/{task_id}/validate")
def validate(task_id: str):

    try:
        task = get_task(task_id)

        report = validate_task(task)

        quality = calculate_task_quality(task, report)
        task.validation_status = (
            "passed"
            if report.get("status") == "passed" and quality.get("accepted")
            else "rejected"
        )
        task.quality_score = quality["score"]

        save_task(task)

        return {
            **serialize_validation_summary(report, task.validation_status),
            "quality": serialize_quality_summary(quality),
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception("Task validation failed: %s", task_id)

        raise HTTPException(
            status_code=500,
            detail="Task validation failed",
        ) from exc


# ==================================================
# MODEL EVALUATION
# ==================================================

@app.post("/api/tasks/{task_id}/evaluate")
async def evaluate(
    task_id: str,
    req: EvaluateRequest,
):

    task = get_task(task_id)

    if task.validation_status != "passed":
        raise HTTPException(
            status_code=409,
            detail="Only validated tasks can be evaluated",
        )

    try:
        model_name = req.model
        if model_name is None:
            raise HTTPException(
                status_code=400,
                detail="Model is required",
            )

        logger.info(
            "Starting evaluation | Task: %s | Model: %s",
            task_id,
            model_name,
        )

        result = await evaluate_task(
            task,
            model_name,
        )

        with SessionLocal() as db:

            db.add(
                EvaluationRecord(
                    evaluation_id=result["evaluation_id"],
                    task_id=task_id,
                    task_version=task.task_version,
                    model=result["model"],
                    result_json=json.dumps(result),
                )
            )

            db.commit()

        logger.info(
            "Evaluation completed: %s",
            result["evaluation_id"],
        )

        return serialize_evaluation(result)

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "Model evaluation failed | Task: %s",
            task_id,
        )

        raise HTTPException(
            status_code=503,
            detail={
                "message": "Model evaluation failed",
                "error_type": type(exc).__name__,
            },
        ) from exc


# ==================================================
# GET ALL TASKS - PUBLIC RESPONSE
# ==================================================

@app.get("/api/tasks")
def tasks(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):

    all_tasks = get_task_page(limit, offset)

    public_tasks = []

    for task_data in all_tasks:

        try:
            task = Task.model_validate(task_data)
            public_tasks.append(serialize_public_task(task))

        except Exception:
            logger.exception(
                "Could not serialize public task: %s",
                task_data.get("task_id"),
            )

    return public_tasks


# ==================================================
# GET TASK DETAILS - PUBLIC RESPONSE
# ==================================================

@app.get("/api/tasks/{task_id}")
def task_detail(
    task_id: str,
    task_version: int | None = Query(default=None, ge=1),
):

    task = get_task(task_id, task_version)

    return serialize_public_task(task)


# ==================================================
# GET ALL EVALUATIONS
# ==================================================

@app.get("/api/evaluations")
def evaluations(
    model: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return [
        serialize_evaluation(item)
        for item in get_evaluation_page(model, limit, offset)
    ]


# ==================================================
# GET EVALUATION DETAILS
# ==================================================

@app.get("/api/evaluations/{evaluation_id}")
def evaluation_detail(evaluation_id: str):

    with SessionLocal() as db:

        row = db.get(
            EvaluationRecord,
            evaluation_id,
        )

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Evaluation not found",
            )

        return serialize_evaluation(json.loads(row.result_json))


# ==================================================
# FAILURE REPORTS
# ==================================================

@app.get("/api/failures")
def failures(
    model: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):

    all_evaluations = get_evaluation_page(model, limit, offset)

    return [
        failure
        for evaluation in all_evaluations
        for failure in serialize_evaluation(evaluation).get("failure_summary", [])
    ]


# ==================================================
# WEAKNESS ANALYSIS
# ==================================================

@app.get("/api/weaknesses")
def weaknesses(
    model: str | None = None,
    min_task_occurrences: int = 2,
):

    if min_task_occurrences < 2:
        raise HTTPException(
            status_code=422,
            detail="min_task_occurrences must be at least 2",
        )

    all_evaluations = get_all_evaluations(model)

    results = analyze_weaknesses(
        all_evaluations,
        min_task_occurrences,
    )

    return {
        "model": model or "all",
        "minimum_distinct_tasks": min_task_occurrences,
        "evaluations_analyzed": len(all_evaluations),
        "weakness_count": len(results),
        "weaknesses": [serialize_weakness(item) for item in results],
        "message": (
            "Recurring weaknesses found"
            if results
            else "No recurring weaknesses found. "
                 "More failed evaluations across distinct tasks are required."
        ),
    }


# ==================================================
# ANALYTICS
# ==================================================

@app.get("/api/analytics")
def analytics():

    all_tasks = get_all_tasks()
    all_evaluations = get_all_evaluations()

    total_tasks = len(all_tasks)
    total_evaluations = len(all_evaluations)

    validated_tasks = sum(
        task["validation_status"] == "passed"
        for task in all_tasks
    )

    rejected_tasks = sum(
        task["validation_status"] == "rejected"
        for task in all_tasks
    )

    target_failures = sum(
        not evaluation.get("task_passed", False)
        for evaluation in all_evaluations
    )

    average_quality = (
        round(
            sum(task["quality_score"] for task in all_tasks)
            / total_tasks,
            1,
        )
        if total_tasks
        else None
    )

    overall_pass_rate = (
        round(
            100 * sum(
                evaluation.get("task_passed", False)
                for evaluation in all_evaluations
            ) / total_evaluations,
            1,
        )
        if total_evaluations
        else None
    )

    archetype_distribution: dict[str, int] = {}
    for task in all_tasks:
        archetype = (task.get("metadata") or {}).get("archetype")
        if isinstance(archetype, str) and archetype:
            archetype_distribution[archetype] = (
                archetype_distribution.get(archetype, 0) + 1
            )

    return {
        "total_tasks": total_tasks,
        "validated_tasks": validated_tasks,
        "rejected_tasks": rejected_tasks,
        "evaluations": total_evaluations,
        "target_failures": target_failures,
        "average_quality": average_quality,
        "overall_pass_rate": overall_pass_rate,
        "archetype_distribution": archetype_distribution,
    }


# ==================================================
# DATASET MANAGEMENT
# ==================================================

@app.get("/api/datasets")
def datasets():

    return {
        "versions": [],
        "task_count": len(get_all_tasks()),
    }


# ==================================================
# JSONL EXPORT
# ==================================================

@app.get("/api/datasets/export")
def export(include_solution: bool = False):

    try:

        all_tasks = get_all_tasks()

        eligible = [
            Task.model_validate(task)
            for task in all_tasks
            if task["validation_status"] == "passed"
        ]

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        export_kind = "internal" if include_solution else "public"
        export_path = ROOT / "datasets" / f"validated_{export_kind}_{timestamp}.jsonl"

        export_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        count = export_jsonl(
            eligible,
            export_path,
            include_solution=include_solution,
        )

        logger.info(
            "Dataset exported | Records: %s | Path: %s",
            count,
            export_path,
        )

        return {
            "file": export_path.name,
            "records": count,
            "mode": export_kind,
        }

    except Exception as exc:

        logger.exception("Dataset export failed")

        raise HTTPException(
            status_code=500,
            detail="Dataset export failed",
        ) from exc


# ==================================================
# COMPLETE PIPELINE
# ==================================================

@app.post("/api/pipeline/run", status_code=202)
async def pipeline(req: GenerateRequest):
    job_id = f"JOB_{uuid4().hex[:12].upper()}"

    async def run_pipeline():
        return await generate(req)

    submit_job(job_id, run_pipeline)
    return {"job_id": job_id, "status": "queued", "progress": 0}


# ==================================================
# ADAPTIVE GENERATION
# ==================================================

@app.post("/api/adaptive-generation/run")
async def adaptive(req: AdaptiveGenerateRequest):

    model = req.model or TARGET_MODEL

    all_evaluations = get_all_evaluations(model)

    weakness_results = analyze_weaknesses(
        all_evaluations,
        req.min_task_occurrences,
    )

    if not weakness_results:

        raise HTTPException(
            status_code=409,
            detail={
                "message": "Insufficient recurring failure evidence",
                "model": model,
                "minimum_distinct_tasks": req.min_task_occurrences,
                "evaluations_analyzed": len(all_evaluations),
                "instruction": (
                    "Evaluate the model on more distinct tasks and "
                    "collect genuine failures before adaptive generation."
                ),
            },
        )

    generated_tasks = []

    try:

        for index in range(req.count):

            weakness = weakness_results[
                index % len(weakness_results)
            ]

            parent_evaluation = next(
                (
                    evaluation
                    for evaluation in reversed(all_evaluations)
                    if evaluation.get("task_id") in weakness["task_ids"]
                ),
                None,
            )
            parent_task_id = (
                parent_evaluation.get("task_id")
                if parent_evaluation else None
            )
            parent_task_version = (
                parent_evaluation.get("task_version")
                if parent_evaluation else None
            )
            parent_evaluation_id = (
                parent_evaluation.get("evaluation_id")
                if parent_evaluation else None
            )

            if not parent_task_id:
                raise RuntimeError(
                    "Could not identify a parent task for adaptive generation"
                )

            parent_task = get_task(parent_task_id, parent_task_version)

            parent_metadata = parent_task.metadata or {}

            generation_round = (
                int(parent_metadata.get("generation_round", 0)) + 1
            )

            previous_titles = []

            for task_id in weakness["task_ids"]:

                try:
                    previous_task = get_task(task_id)
                    previous_titles.append(previous_task.title)

                except HTTPException:
                    continue

            adaptive_context = {
                "weakness": weakness["weakness"],
                "weakness_label": weakness.get("weakness_label"),
                "semantic_confidence": weakness.get("semantic_confidence"),
                "examples": weakness["examples"],
                "task_ids": weakness["task_ids"],
                "parent_task_id": parent_task_id,
                "parent_task_version": parent_task_version,
                "parent_evaluation_id": parent_evaluation_id,
                "generation_round": generation_round,
                "previous_task_titles": previous_titles,
            }

            existing_tasks = get_existing_task_objects()

            task = await generate_task(
                req.difficulty,
                f"Adaptive benchmark targeting {weakness['weakness']}",
                adaptive_context=adaptive_context,
                existing_tasks=existing_tasks,
            )

            report = validate_task(task)

            quality = score_task(
                task,
                report,
                existing_tasks=existing_tasks,
            )

            task.validation_status = (
                "passed"
                if (
                    report.get("status") == "passed"
                    and quality.get("accepted")
                )
                else "rejected"
            )

            task.quality_score = quality["score"]

            save_task(task)

            generated_tasks.append({
                "task": serialize_public_task(task),
                "validation": serialize_validation_summary(
                    report,
                    task.validation_status,
                ),
                "quality": serialize_quality_summary(quality),
                "adaptive_evidence": {
                    "weakness": weakness["weakness"],
                    "weakness_label": weakness.get("weakness_label"),
                    "semantic_confidence": weakness.get("semantic_confidence"),
                    "distinct_task_count": weakness["distinct_task_count"],
                    "parent_task_id": parent_task_id,
                    "parent_task_version": parent_task_version,
                    "parent_evaluation_id": parent_evaluation_id,
                    "generation_round": generation_round,
                },
            })

        return {
            "status": "completed",
            "model": model,
            "total_generated": len(generated_tasks),
            "tasks": generated_tasks,
        }

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception("Adaptive generation failed")

        raise HTTPException(
            status_code=503,
            detail={
                "message": "Adaptive generation failed",
                "error_type": type(exc).__name__,
            },
        ) from exc


# ==================================================
# JOB STATUS
# ==================================================

@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    result = read_job(job_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )
    return result


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    current = read_job(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if current["status"] != "queued" or not cancel_job(job_id):
        raise HTTPException(
            status_code=409,
            detail="Only jobs that have not started can be cancelled",
        )
    return read_job(job_id)
