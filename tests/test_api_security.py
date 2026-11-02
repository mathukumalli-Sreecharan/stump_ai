from fastapi.testclient import TestClient

from backend import main
from backend.schemas import Difficulty, Task, TestCase


def make_task(status="passed"):
    return Task(
        task_id="TASK_API_SECURITY",
        difficulty=Difficulty.easy,
        title="Count values",
        problem_statement="Count values and return the result.",
        input_specification="A list of values.",
        output_specification="A count.",
        expected_behavior="Count each value.",
        function_signature="def solve(values):",
        time_complexity="O(n)",
        generation_model="mock-model",
        golden_solution="def solve(values):\n    return len(values)",
        validation_status=status,
        tests=[
            TestCase(
                test_id=f"TC{i}",
                input={"values": [1, 2]},
                expected_output=2,
                visibility="public" if i < 2 else "hidden",
            )
            for i in range(5)
        ],
    )


def test_generate_endpoint_does_not_return_validation_evidence(monkeypatch):
    task = make_task(status="pending")

    async def fake_generate(*args, **kwargs):
        return task

    monkeypatch.setattr(main, "generate_task", fake_generate)
    monkeypatch.setattr(main, "get_existing_task_objects", lambda: [])
    monkeypatch.setattr(main, "validate_task", lambda _: {
        "status": "passed", "total_tests": 5, "passed_tests": 5,
        "failed_tests": 0,
        "results": [{"expected": "SECRET_OUTPUT", "actual": "SECRET_OUTPUT"}],
        "validation_errors": [{"input": "SECRET_INPUT", "expected": "SECRET_OUTPUT"}],
    })
    monkeypatch.setattr(main, "score_task", lambda *_args, **_kwargs: {
        "score": 91, "accepted": True,
        "dimensions": {"private_dimension": 1},
        "specification_coverage": {"evidence": "SECRET_EVIDENCE"},
    })
    monkeypatch.setattr(main, "save_task", lambda _: None)

    response = TestClient(main.app).post(
        "/api/tasks/generate",
        json={"topic": "counting", "difficulty": "easy", "count": 1},
    )
    assert response.status_code == 200
    body = response.json()
    serialized = str(body)
    assert "golden_solution" not in body["tasks"][0]["task"]
    assert "expected_output" not in serialized
    assert "SECRET_OUTPUT" not in serialized
    assert "SECRET_INPUT" not in serialized
    assert "SECRET_EVIDENCE" not in serialized


def test_evaluation_endpoint_returns_allowlisted_summary(monkeypatch):
    task = make_task()
    result = {
        "evaluation_id": "EVAL_SAFE",
        "task_id": task.task_id,
        "model": "mock-model",
        "task_passed": False,
        "status": "failed",
        "passed_tests": 4,
        "failed_tests": 1,
        "total_tests": 5,
        "elapsed_seconds": 0.1,
        "test_summary": {"public": {"total": 2, "passed": 2}, "hidden": {"total": 3, "passed": 2}},
        "failure_reports": [{
            "failure_type": "incorrect_algorithm",
            "weakness_label": "Counting",
            "severity": "medium",
            "evidence": {"expected_output": "SECRET_EXPECTED", "test_input": "SECRET_INPUT"},
        }],
        "candidate_code": "SECRET_CODE",
    }

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def add(self, _row): pass
        def commit(self): pass

    monkeypatch.setattr(main, "get_task", lambda _: task)
    async def fake_evaluate(*_args): return result
    monkeypatch.setattr(main, "evaluate_task", fake_evaluate)
    monkeypatch.setattr(main, "SessionLocal", FakeSession)

    response = TestClient(main.app).post(
        f"/api/tasks/{task.task_id}/evaluate",
        json={"model": "mock-model"},
    )
    assert response.status_code == 200
    body = response.json()
    serialized = str(body)
    assert body["test_summary"]["hidden"] == {"total": 3, "passed": 2}
    assert body["failure_summary"][0]["failure_type"] == "incorrect_algorithm"
    assert "SECRET_EXPECTED" not in serialized
    assert "SECRET_INPUT" not in serialized
    assert "SECRET_CODE" not in serialized
    assert "failure_reports" not in body


def test_evaluation_list_and_weakness_endpoints_hide_raw_evidence(monkeypatch):
    raw = [{
        "evaluation_id": "EVAL_PRIVATE",
        "task_id": "TASK_PRIVATE",
        "model": "mock-model",
        "task_passed": False,
        "status": "failed",
        "passed_tests": 0,
        "failed_tests": 1,
        "total_tests": 1,
        "elapsed_seconds": 0.1,
        "failure_reports": [{
            "failure_type": "incorrect_algorithm",
            "underlying_weakness": "counting",
            "weakness_label": "Counting",
            "severity": "medium",
            "evidence": {"expected_output": "SECRET_EXPECTED"},
            "description": "SECRET_DESCRIPTION",
        }],
    }]
    monkeypatch.setattr(main, "get_evaluation_page", lambda *_args: raw)
    client = TestClient(main.app)

    evaluation_response = client.get("/api/evaluations")
    weakness_response = client.get("/api/weaknesses?min_task_occurrences=2")
    assert evaluation_response.status_code == 200
    assert weakness_response.status_code == 200
    assert "SECRET_EXPECTED" not in evaluation_response.text
    assert "SECRET_EXPECTED" not in weakness_response.text
    assert "SECRET_DESCRIPTION" not in weakness_response.text


def test_health_validation_and_adaptive_evidence_requirements(monkeypatch):
    client = TestClient(main.app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    invalid = client.post(
        "/api/tasks/generate",
        json={"topic": "x", "difficulty": "impossible", "count": 1},
    )
    assert invalid.status_code == 422

    monkeypatch.setattr(main, "get_all_evaluations", lambda *_args: [])
    adaptive = client.post("/api/adaptive-generation/run", json={})
    assert adaptive.status_code == 409
    assert adaptive.json()["detail"]["message"] == "Insufficient recurring failure evidence"


def test_task_list_detail_validation_and_pipeline_job(monkeypatch):
    task = make_task(status="rejected")
    data = task.model_dump(mode="json")
    monkeypatch.setattr(main, "get_task_page", lambda _limit, _offset: [data])
    monkeypatch.setattr(main, "get_task", lambda *_args: task)
    client = TestClient(main.app)

    task_list = client.get("/api/tasks")
    detail = client.get(f"/api/tasks/{task.task_id}")
    assert task_list.status_code == detail.status_code == 200
    for body in (task_list.text, detail.text):
        assert "golden_solution" not in body
        assert "expected_output" not in body
    assert len(task_list.json()[0]["tests"]) == 2

    monkeypatch.setattr(main, "validate_task", lambda _: {
        "status": "passed", "total_tests": 5, "passed_tests": 5,
        "failed_tests": 0,
        "results": [{"expected": "SECRET"}],
    })
    monkeypatch.setattr(main, "calculate_task_quality", lambda *_args: {
        "score": 60, "accepted": False,
    })
    monkeypatch.setattr(main, "save_task", lambda _: None)
    validation = client.post(f"/api/tasks/{task.task_id}/validate")
    assert validation.status_code == 200
    assert validation.json()["status"] == "rejected"
    assert validation.json()["golden_solution_status"] == "passed"
    assert "SECRET" not in validation.text

    submitted = []
    monkeypatch.setattr(main, "submit_job", lambda job_id, _work: submitted.append(job_id))
    monkeypatch.setattr(main, "read_job", lambda job_id: {
        "job_id": job_id, "status": "queued", "progress": 0,
    })
    pipeline = client.post("/api/pipeline/run", json={"topic": "demo", "count": 1})
    assert pipeline.status_code == 202
    job_id = pipeline.json()["job_id"]
    job = client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "queued"
    assert submitted == [job_id]


def test_failures_and_dataset_export_endpoints_are_allowlisted(monkeypatch):
    task = make_task()
    task.validation_status = "passed"
    monkeypatch.setattr(main, "get_all_tasks", lambda: [task.model_dump(mode="json")])
    monkeypatch.setattr(main, "get_evaluation_page", lambda *_args: [{
        "evaluation_id": "EVAL_PRIVATE",
        "task_id": task.task_id,
        "model": "mock",
        "task_passed": False,
        "status": "failed",
        "passed_tests": 1,
        "failed_tests": 1,
        "total_tests": 2,
        "failure_reports": [{
            "failure_type": "incorrect_algorithm",
            "weakness_label": "Counting",
            "severity": "medium",
            "evidence": {"expected_output": "SECRET_EXPECTED"},
        }],
    }])
    monkeypatch.setattr(main, "export_jsonl", lambda *_args, **_kwargs: 1)
    client = TestClient(main.app)

    failures = client.get("/api/failures")
    exported = client.get("/api/datasets/export")
    assert failures.status_code == exported.status_code == 200
    assert "SECRET_EXPECTED" not in failures.text
    assert exported.json()["records"] == 1
    assert exported.json()["mode"] == "public"
    assert exported.json()["file"].startswith("validated_public_")


def test_weakness_recurrence_requires_distinct_tasks():
    repeated_failures = [{
        "evaluation_id": "EVAL_A",
        "task_id": "TASK_A",
        "failure_reports": [
            {"failure_type": "incorrect_algorithm", "underlying_weakness": "counting"}
            for _ in range(5)
        ],
    }]
    assert main.analyze_weaknesses(repeated_failures, 2) == []

    repeated_failures.append({
        "evaluation_id": "EVAL_B",
        "task_id": "TASK_B",
        "failure_reports": [{
            "failure_type": "incorrect_algorithm",
            "underlying_weakness": "counting",
        }],
    })
    result = main.analyze_weaknesses(repeated_failures, 2)
    assert len(result) == 1
    assert result[0]["distinct_task_count"] == 2
    assert result[0]["task_ids"] == ["TASK_A", "TASK_B"]

