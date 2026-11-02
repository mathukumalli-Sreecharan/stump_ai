"""Evaluate target-model solutions against benchmark test cases."""
import logging
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from backend.services.ollama import GENERATION_OPTIONS
from backend.execution.service import run_candidate
from backend.execution.runner import validate_source
from backend.services.failure_analysis import analyze_failures
from backend.services.code_extract import extract_python
from backend.services.ollama import OllamaProvider
from backend.services.validation import get_function_name

logger = logging.getLogger(__name__)


async def evaluate_task(task, model: str) -> dict:
    """Generate a candidate solution, run all task tests, and report failures."""
    if not model or not model.strip():
        raise ValueError("Evaluation model name must not be empty")

    function_name = get_function_name(task.function_signature)
    prompt = (
        "Solve this Python programming task. Return only a complete Python "
        "implementation, with no explanation or tests.\n\n"
        f"Title: {task.title}\nProblem:\n{task.problem_statement}\n\n"
        f"Input specification:\n{task.input_specification}\n\n"
        f"Output specification:\n{task.output_specification}\n\n"
        "Constraints:\n"
        + "\n".join(f"- {item}" for item in task.constraints)
        + f"\n\nRequired function signature:\n{task.function_signature}"
    )

    provider = OllamaProvider(model)
    if not await provider.available():
        raise RuntimeError(f"Ollama model is unavailable: {model}")

    response = await provider.generate_text(
        prompt,
        system="You are a Python coding assistant. Follow the requested signature exactly.",
    )
    candidate = extract_python(response)
    cases = [test.model_dump(mode="json") for test in task.tests]
    source_error = validate_source(candidate, function_name)
    if source_error:
        if source_error.startswith("SyntaxError:"):
            status = "syntax_error"
        elif "Required function" in source_error or "Golden solution is empty" in source_error:
            status = "parsing_error"
        else:
            status = "invalid_response"
        execution = {
            "status": status,
            "error": source_error,
            "total_tests": len(cases),
            "passed_tests": 0,
            "failed_tests": len(cases),
            "results": [],
        }
    else:
        execution = run_candidate(candidate, function_name, cases)

    failures = analyze_failures(task, execution)

    passed = execution.get("passed_tests", 0)
    total = execution.get("total_tests", len(task.tests))
    public_indexes = [
        index for index, test in enumerate(task.tests)
        if str(getattr(test.visibility, "value", test.visibility)).lower() == "public"
    ]
    hidden_indexes = [
        index for index, test in enumerate(task.tests)
        if str(getattr(test.visibility, "value", test.visibility)).lower() != "public"
    ]
    results = execution.get("results", [])
    test_summary = {
        "public": {
            "total": len(public_indexes),
            "passed": sum(index < len(results) and results[index].get("ok") is True for index in public_indexes),
        },
        "hidden": {
            "total": len(hidden_indexes),
            "passed": sum(index < len(results) and results[index].get("ok") is True for index in hidden_indexes),
        },
    }
    test_results = []
    for index, test in enumerate(task.tests):
        result = results[index] if index < len(results) else {}
        visibility = str(getattr(test.visibility, "value", test.visibility)).lower()
        test_results.append({
            "test_id": test.test_id,
            "visibility": visibility,
            "passed": result.get("ok") is True,
            "input": test.input,
            "expected_output": test.expected_output,
            "actual_output": result.get("actual"),
            "error": result.get("error"),
        })
    evaluation_id = f"EVAL_{uuid4().hex[:12].upper()}"
    task_passed = execution.get("status") == "complete" and passed == total
    logger.info("Evaluation %s finished for %s: %s/%s passed", evaluation_id, model, passed, total)
    return {
        "evaluation_id": evaluation_id,
        "task_id": task.task_id,
        "task_version": task.task_version,
        "model": model,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_version": "target_solve_v1",
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "model_parameters": dict(GENERATION_OPTIONS),
        "target_response": response,
        "candidate_code": candidate,
        "task_passed": task_passed,
        "status": execution.get("status"),
        "passed_tests": passed,
        "failed_tests": execution.get("failed_tests", max(0, total - passed)),
        "total_tests": total,
        "elapsed_seconds": execution.get("elapsed_seconds"),
        "failure_reports": failures,
        "test_summary": test_summary,
        "test_results": test_results,
        "execution_error": execution.get("error"),
    }
