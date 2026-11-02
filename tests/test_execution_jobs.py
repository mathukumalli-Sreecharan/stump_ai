import asyncio
import time

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from backend.database.db import Base, JobRecord
from backend.execution import service as execution_service
from backend.services import job_manager


def test_unsafe_backend_is_never_reported_as_secure(monkeypatch):
    monkeypatch.setattr(execution_service, "EXECUTION_BACKEND", "unsafe_subprocess")
    assert execution_service.execution_status()["secure"] is False
    monkeypatch.setattr(execution_service, "EXECUTION_BACKEND", "unavailable_secure_backend")
    assert execution_service.execution_status()["available"] is False


def test_persistent_job_completes_and_orphaned_job_is_marked_failed(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    local_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(job_manager, "SessionLocal", local_sessions)

    async def work():
        await asyncio.sleep(0)
        return {"result": "ok"}

    try:
        job_manager.submit_job("JOB_TEST_COMPLETE", work)
        for _ in range(100):
            result = job_manager.get_job("JOB_TEST_COMPLETE")
            if result and result["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert result["status"] == "completed"
        assert result["progress"] == 100
        assert result["result"] == {"result": "ok"}

        with local_sessions.begin() as db:
            db.add(JobRecord(job_id="JOB_ORPHAN", status="running", progress=10))
        assert job_manager.mark_orphaned_jobs_failed() == 1
        assert job_manager.get_job("JOB_ORPHAN")["status"] == "failed"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
