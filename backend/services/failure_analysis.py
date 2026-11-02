
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def get_value(obj: Any, key: Any, default=None):
    if key is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def get_category(test: Any) -> str:
    value = get_value(test, "category", "unknown")
    return str(getattr(value, "value", value)).lower()


def normalize_text(value: Any) -> str:
    """Normalize task text for semantic pattern matching."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).lower()).strip()


def infer_semantic_weakness(task: Any) -> dict:
    """
    Infer a task-level algorithmic concept from the specification.

    This is a deterministic heuristic, not an LLM-based diagnosis.
    Unknown concepts remain explicitly unclassified.
    """
    fields = [
        get_value(task, "title", ""),
        get_value(task, "problem_statement", ""),
        get_value(task, "expected_behavior", ""),
        get_value(task, "input_specification", ""),
        get_value(task, "output_specification", ""),
    ]

    text = normalize_text(" ".join(str(x or "") for x in fields))

    patterns = [
        (
            "consecutive_sequence_validation",
            "Consecutive sequence validation",
            [
                r"consecutive integers",
                r"consecutive sequence",
                r"exactly one more",
                r"without gaps",
                r"no gaps",
                r"previous element.*\+ ?1",
                r"strictly increasing with consecutive",
            ],
            "Check the exact relationship between adjacent elements, "
            "not merely whether they are increasing.",
        ),
        (
            "duplicate_detection",
            "Duplicate detection",
            [
                r"duplicate",
                r"repeated elements",
                r"unique elements",
                r"distinct values",
            ],
            "Check whether repeated values are allowed and handle "
            "duplicate elements explicitly.",
        ),
        (
            "sorting_and_ordering",
            "Sorting and ordering",
            [
                r"sorted",
                r"ascending order",
                r"descending order",
                r"non-decreasing",
                r"non-increasing",
                r"ordering",
            ],
            "Verify the required ordering relation, including equality "
            "and boundary cases.",
        ),
        (
            "palindrome_validation",
            "Palindrome validation",
            [
                r"palindrome",
                r"reads the same forward and backward",
                r"same forwards and backwards",
            ],
            "Compare the appropriate mirrored positions and account "
            "for the task's character-handling rules.",
        ),
        (
            "frequency_counting",
            "Frequency counting",
            [
                r"frequency",
                r"occurrences",
                r"count of each",
                r"how many times",
            ],
            "Check counting logic and ensure every relevant element "
            "is included exactly as required.",
        ),
        (
            "boundary_and_range_validation",
            "Boundary and range validation",
            [
                r"within the range",
                r"minimum value",
                r"maximum value",
                r"between .* and",
                r"out of bounds",
            ],
            "Check inclusive and exclusive bounds and test values "
            "at both limits.",
        ),
    ]

    for weakness_id, label, expressions, recommendation in patterns:
        if any(re.search(pattern, text) for pattern in expressions):
            return {
                "underlying_weakness": weakness_id,
                "weakness_label": label,
                "semantic_confidence": "high",
                "recommendation": recommendation,
            }

    return {
        "underlying_weakness": "unclassified_algorithmic_failure",
        "weakness_label": "Unclassified algorithmic failure",
        "semantic_confidence": "low",
        "recommendation": (
            "Inspect the task specification, failing input, expected "
            "output, actual output, and generated code before assigning "
            "a specific algorithmic weakness."
        ),
    }


def analyze_failures(task, evaluation: dict) -> list[dict]:
    reports = []

    tests = list(get_value(task, "tests", []) or [])
    results = evaluation.get("results", []) or []
    status: str = evaluation.get("status") or "unknown"

    semantic = infer_semantic_weakness(task)

    # Execution timeout
    if status == "timeout":
        return [{
            "failure_type": "timeout",
            "description": (
                "The target model's solution exceeded the execution time limit."
            ),
            "failed_tests": [
                str(get_value(test, "test_id", f"test_{i}"))
                for i, test in enumerate(tests)
            ],
            "severity": "high",
            "evidence": {
                "execution_status": status,
                "elapsed_seconds": evaluation.get("elapsed_seconds"),
            },
            "underlying_weakness": "execution_time",
            "weakness_label": "Execution time and complexity",
            "semantic_confidence": "high",
            "recommendation": (
                "Investigate algorithmic complexity and test the solution "
                "with larger inputs."
            ),
        }]

    # Code parsing, syntax, and execution-environment failures.
    if status in {
        "execution_error",
        "invalid_response",
        "validation_error",
        "syntax_error",
        "parsing_error",
        "environment_error",
    } and not results:
        failure_type: str = {
            "syntax_error": "syntax_error",
            "parsing_error": "parsing_error",
            "environment_error": "environment_failure",
            "execution_error": "environment_failure",
        }.get(status, status)
        return [{
            "failure_type": failure_type,
            "description": evaluation.get(
                "error",
                "The solution could not be evaluated."
            ),
            "failed_tests": [],
            "severity": "high",
            "evidence": {
                "execution_status": status,
                "error": evaluation.get("error"),
            },
            "underlying_weakness": failure_type,
            "weakness_label": {
                "syntax_error": "Syntax errors",
                "parsing_error": "Invalid model response",
                "environment_failure": "Execution environment failure",
            }.get(failure_type, "Execution or response handling"),
            "semantic_confidence": "high",
            "recommendation": (
                "Inspect generated code and execution environment before "
                "drawing conclusions about model reasoning."
            ),
        }]

    # Analyze individual test failures
    for index, test in enumerate(tests):
        test_id = str(
            get_value(test, "test_id", f"test_{index}")
        )

        description = str(
            get_value(test, "description", "")
        )

        category = get_category(test)

        visibility_value = get_value(test, "visibility", "unknown")
        visibility = str(
            getattr(visibility_value, "value", visibility_value)
        ).lower()

        test_input = get_value(test, "input", {})
        expected_output = get_value(test, "expected_output")

        if index >= len(results):
            reports.append({
                "failure_type": "missing_test_result",
                "description": f"No execution result was returned for {test_id}",
                "failed_tests": [test_id],
                "severity": "high",
                "evidence": {
                    "test_index": index,
                    "test_input": test_input,
                    "expected_output": expected_output,
                    "visibility": visibility,
                    "category": category,
                },
                "underlying_weakness": "incomplete_execution",
                "weakness_label": "Incomplete test execution",
                "semantic_confidence": "high",
                "recommendation": (
                    "Inspect runner output and verify that all test "
                    "cases completed."
                ),
            })
            continue

        result = results[index]

        if not isinstance(result, dict):
            result = {"error": "Invalid runner result format"}

        if result.get("ok"):
            continue

        if result.get("error"):
            failure_type = "runtime_exception"
            weakness_id = "runtime_error_handling"
            weakness_label = "Runtime error handling"
            confidence = "high"
            recommendation = (
                "Inspect the exception and generated code. Do not classify "
                "a runtime exception as an algorithmic misconception "
                "without additional evidence."
            )
            severity = "high"

        else:
            failure_type = (
                "boundary_condition_failure"
                if category in {"boundary", "edge", "adversarial"}
                else "incorrect_algorithm"
            )

            weakness_id = semantic["underlying_weakness"]
            weakness_label = semantic["weakness_label"]
            confidence = semantic["semantic_confidence"]
            recommendation = semantic["recommendation"]
            severity = "medium"

        reports.append({
            "failure_type": failure_type,
            "description": f"Failed {test_id}: {description}",
            "failed_tests": [test_id],
            "severity": severity,
            "evidence": {
                **result,
                "test_id": test_id,
                "test_index": index,
                "test_input": test_input,
                "expected_output": expected_output,
                "visibility": visibility,
                "category": category,
            },
            "underlying_weakness": weakness_id,
            "weakness_label": weakness_label,
            "semantic_confidence": confidence,
            "recommendation": recommendation,
        })

    if len(results) > len(tests):
        logger.warning(
            "Runner returned more results than tests | Results: %s | Tests: %s",
            len(results),
            len(tests),
        )

    return reports
