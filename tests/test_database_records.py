import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database.db import Base, EvaluationRecord, TaskRecord


def test_task_versions_coexist_and_evaluation_duplicates_roll_back():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add_all([
                TaskRecord(task_id="TASK_VERSION_TEST", task_version=1, record_json='{"version":1}'),
                TaskRecord(task_id="TASK_VERSION_TEST", task_version=2, record_json='{"version":2}'),
                EvaluationRecord(
                    evaluation_id="EVAL_DUP_TEST", task_id="TASK_VERSION_TEST",
                    model="mock", result_json='{"task_passed":true}',
                ),
            ])
            session.commit()

            versions = session.scalars(
                select(TaskRecord).where(TaskRecord.task_id == "TASK_VERSION_TEST")
            ).all()
            assert {row.task_version for row in versions} == {1, 2}

            session.add(EvaluationRecord(
                evaluation_id="EVAL_DUP_TEST", task_id="TASK_VERSION_TEST",
                model="mock", result_json='{}',
            ))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            rows = session.scalars(select(EvaluationRecord)).all()
            assert len(rows) == 1
            assert rows[0].result_json == '{"task_passed":true}'
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
