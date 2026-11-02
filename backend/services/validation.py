
import ast
import logging
import textwrap

from backend.execution.service import run_candidate

logger = logging.getLogger(__name__)


def get_function_name(function_signature: str) -> str:
    """Extract and validate the required function name."""

    if (
        not isinstance(function_signature, str)
        or not function_signature.strip()
    ):
        raise ValueError("Function signature is empty")

    signature = textwrap.dedent(function_signature).strip()

    try:
        tree = ast.parse(signature)

        functions = [
            node for node in tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
        ]

        if functions:
            return functions[0].name

    except SyntaxError:
        pass

    declaration = signature.rstrip()

    if not declaration.endswith(":"):
        declaration += ":"

    try:
        tree = ast.parse(declaration + "\n    pass")

        functions = [
            node for node in tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
        ]

        if len(functions) == 1:
            return functions[0].name

    except SyntaxError:
        pass

    raise ValueError(
        f"Invalid function signature: {function_signature}"
    )


def validate_task(task) -> dict:
    """Validate a generated golden solution against its tests."""

    logger.info(
        "Starting golden solution validation: %s",
        task.task_id,
    )

    # STEP 1: Validate function signature.

    try:
        function_name = get_function_name(
            task.function_signature
        )

    except Exception as exc:
        logger.exception(
            "Function signature validation failed"
        )

        return {
            "status": "invalid_signature",
            "error": str(exc),
            "total_tests": len(task.tests),
            "passed_tests": 0,
            "failed_tests": len(task.tests),
            "results": [],
            "validation_errors": [],
        }

    # STEP 2: Validate golden solution exists.

    if (
        not task.golden_solution
        or not task.golden_solution.strip()
    ):
        return {
            "status": "invalid_solution",
            "error": "Golden solution is empty",
            "total_tests": len(task.tests),
            "passed_tests": 0,
            "failed_tests": len(task.tests),
            "results": [],
            "validation_errors": [],
        }

    # STEP 3: Convert test cases.

    test_cases = [
        test.model_dump()
        for test in task.tests
    ]

    if not test_cases:
        return {
            "status": "invalid_tests",
            "error": "No test cases provided",
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "results": [],
            "validation_errors": [],
        }

    # STEP 4: Execute golden solution.

    try:
        result = run_candidate(
            task.golden_solution,
            function_name,
            test_cases,
        )

    except Exception as exc:
        logger.exception(
            "Golden solution execution failed: %s",
            task.task_id,
        )

        return {
            "status": "execution_error",
            "error": str(exc),
            "total_tests": len(test_cases),
            "passed_tests": 0,
            "failed_tests": len(test_cases),
            "results": [],
            "validation_errors": [],
        }

    # STEP 5: Analyze execution results.

    results = result.get("results", [])

    passed = sum(
        1
        for item in results
        if item.get("ok") is True
    )

    failed = len(test_cases) - passed

    # STEP 6: Determine validation status.

    runner_status = result.get("status", "unknown")

    if runner_status != "complete":
        final_status = runner_status

    elif len(results) != len(test_cases):
        final_status = "incomplete_results"

    elif failed > 0:
        final_status = "failed"

    else:
        final_status = "passed"

    # STEP 7: Enrich results with original test information.

    enriched_results = []

    for index, item in enumerate(results):
        enriched = dict(item)

        if index < len(test_cases):
            test = test_cases[index]

            enriched.setdefault(
                "test_id",
                test.get("test_id"),
            )

            enriched.setdefault(
                "input",
                test.get("input"),
            )

            enriched.setdefault(
                "expected",
                test.get("expected_output"),
            )

            enriched.setdefault(
                "category",
                test.get("category"),
            )

            enriched.setdefault(
                "description",
                test.get("description"),
            )

        enriched_results.append(enriched)

    # STEP 8: Collect failed cases.

    validation_errors = [
        item
        for item in enriched_results
        if item.get("ok") is not True
    ]

    # STEP 9: Build validation report.

    report = {
        **result,
        "results": enriched_results,
        "status": final_status,
        "total_tests": len(test_cases),
        "passed_tests": passed,
        "failed_tests": failed,
        "function_name": function_name,
        "validation_errors": validation_errors,
    }

    logger.info(
        "Validation completed | Task: %s | Status: %s | "
        "Passed: %s/%s",
        task.task_id,
        final_status,
        passed,
        len(test_cases),
    )

    return report
