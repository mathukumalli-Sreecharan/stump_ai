"""SQLite-backed thread-pool jobs for long local pipeline requests."""

import asyncio
import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Awaitable, Callable, Any

from backend.database.db import JobRecord, SessionLocal

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="modelstump-job")
_active: dict[str, Future] = {}


def _update(job_id: str, **values: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(JobRecord, job_id)
        if row is not None:
            for key, value in values.items():
                setattr(row, key, value)


def _run(job_id: str, work: Callable[[], Awaitable[dict]]) -> None:
    _update(job_id, status="running", progress=1)
    try:
        result = asyncio.run(work())
        _update(
            job_id,
            status="completed",
            progress=100,
            result_json=json.dumps(result, ensure_ascii=False),
            detail_json=None,
        )
    except Exception as exc:
        logger.exception("Background job failed: %s", job_id)
        _update(
            job_id,
            status="failed",
            progress=100,
            detail_json=json.dumps({
                "message": "Background job failed",
                "error_type": type(exc).__name__,
            }),
        )
    finally:
        logger.debug("Background job worker exited: %s", job_id)


def submit_job(job_id: str, work: Callable[[], Awaitable[dict]]) -> None:
    with SessionLocal.begin() as db:
        db.add(JobRecord(job_id=job_id, status="queued", progress=0))
    future = _executor.submit(_run, job_id, work)
    _active[job_id] = future
    future.add_done_callback(lambda _future: _active.pop(job_id, None))


def get_job(job_id: str) -> dict | None:
    with SessionLocal() as db:
        row = db.get(JobRecord, job_id)
        if row is None:
            return None
        result = {
            "job_id": row.job_id,
            "status": row.status,
            "progress": row.progress,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        if row.result_json is not None:
            result["result"] = json.loads(row.result_json)
        if row.detail_json is not None:
            result["detail"] = json.loads(row.detail_json)
        return result


def cancel_job(job_id: str) -> bool:
    future = _active.get(job_id)
    if future is None or not future.cancel():
        return False
    _update(
        job_id,
        status="cancelled",
        progress=0,
        detail_json=json.dumps({"message": "Job cancelled before it started"}),
    )
    _active.pop(job_id, None)
    return True


def mark_orphaned_jobs_failed() -> int:
    """Close jobs left queued/running after an unclean process restart."""
    count = 0
    with SessionLocal.begin() as db:
        rows = db.query(JobRecord).filter(
            JobRecord.status.in_(("queued", "running"))
        ).all()
        for row in rows:
            row.status = "failed"
            row.progress = 100
            row.detail_json = json.dumps({
                "message": "Job interrupted by application restart",
            })
            count += 1
    return count
