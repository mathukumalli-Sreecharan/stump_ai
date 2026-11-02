
import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from backend.config import EXECUTION_TIMEOUT, MAX_OUTPUT_BYTES


logger = logging.getLogger(__name__)

DENIED_IMPORTS = {
    "subprocess",
    "socket",
    "ctypes",
    "shutil",
    "requests",
    "httpx",
}

DENIED_CALLS = {
    "eval",
    "exec",
    "__import__",
    "compile",
    "open",
    "input",
}


def validate_source(source: str, function_name: str) -> Optional[str]:
    """
    Validate the generated Python source before execution.

    This is a basic static check, not a secure sandbox.
    """

    if not isinstance(source, str) or not source.strip():
        return "Golden solution is empty"

    if not isinstance(function_name, str) or not function_name.strip():
        return "Function name is empty"

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return (
            f"SyntaxError: {exc.msg} "
            f"at line {exc.lineno}, column {exc.offset}"
        )

    # Check prohibited imports.
    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            names = [
                alias.name.split(".")[0]
                for alias in node.names
            ]

            blocked = set(names) & DENIED_IMPORTS

            if blocked:
                return (
                    "Prohibited import detected: "
                    + ", ".join(sorted(blocked))
                )

        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]

            if module in DENIED_IMPORTS:
                return f"Prohibited import detected: {module}"

        # Check prohibited function calls.
        if isinstance(node, ast.Call):

            if (
                isinstance(node.func, ast.Name)
                and node.func.id in DENIED_CALLS
            ):
                return f"Prohibited call detected: {node.func.id}"

    # Require the requested top-level function.
    functions = [
        node
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef)
        )
    ]

    matching_function = next(
        (
            node
            for node in functions
            if node.name == function_name
        ),
        None,
    )

    if matching_function is None:
        available = [node.name for node in functions]

        return (
            f"Required function '{function_name}' is missing. "
            f"Found functions: {available}"
        )

    return None


def run_cases(
    source: str,
    function_name: str,
    cases: list[dict],
) -> dict:
    """
    Execute a candidate Python function against benchmark cases.

    Each case must have this structure:

    {
        "input": {"arg_name": value},
        "expected_output": value
    }

    Returns execution status and individual test results.
    """

    started = time.monotonic()

    logger.info(
        "Starting code execution | Function: %s | Tests: %s",
        function_name,
        len(cases) if isinstance(cases, list) else "invalid",
    )

    # Validate input.
    if not isinstance(cases, list):
        return {
            "status": "invalid_response",
            "error": "Test cases must be a list",
            "results": [],
        }

    if not cases:
        return {
            "status": "invalid_response",
            "error": "No test cases supplied",
            "results": [],
        }

    # Validate source code.
    error = validate_source(source, function_name)

    if error:
        logger.warning(
            "Golden solution rejected: %s",
            error,
        )

        return {
            "status": "invalid_response",
            "error": error,
            "elapsed_seconds": time.monotonic() - started,
            "results": [],
        }

    # Validate individual test cases.
    for index, case in enumerate(cases):

        if not isinstance(case, dict):
            return {
                "status": "invalid_response",
                "error": f"Test case {index} is not an object",
                "results": [],
            }

        if "input" not in case:
            return {
                "status": "invalid_response",
                "error": f"Test case {index} is missing input",
                "results": [],
            }

        if "expected_output" not in case:
            return {
                "status": "invalid_response",
                "error": (
                    f"Test case {index} is missing expected_output"
                ),
                "results": [],
            }

        if not isinstance(case["input"], dict):
            return {
                "status": "invalid_response",
                "error": (
                    f"Test case {index} input must be an object"
                ),
                "results": [],
            }

    # This harness executes separately from the candidate source.
    harness = r'''
import contextlib
import io
import json
import sys
import traceback

source_path = sys.argv[1]
cases_path = sys.argv[2]
function_name = sys.argv[3]

with open(source_path, encoding="utf-8") as file:
    source = file.read()

with open(cases_path, encoding="utf-8") as file:
    cases = json.load(file)

namespace = {}

try:
    exec(compile(source, "candidate.py", "exec"), namespace)

    if function_name not in namespace:
        raise RuntimeError(
            "Required function was not defined"
        )

    function = namespace[function_name]

except Exception as exc:
    print(json.dumps({
        "runner_error": (
            type(exc).__name__ + ": " + str(exc)
        )
    }))
    sys.exit(1)

results = []

for index, case in enumerate(cases):
    try:
        stdout_buffer = io.StringIO()

        with contextlib.redirect_stdout(stdout_buffer):
            actual = function(**case["input"])

        expected = case["expected_output"]

        results.append({
            "test_index": index,
            "ok": actual == expected,
            "actual": actual,
            "expected": expected
        })

    except Exception as exc:
        results.append({
            "test_index": index,
            "ok": False,
            "error": (
                type(exc).__name__ + ": " + str(exc)
            )
        })

try:
    print(json.dumps(results, default=repr))

except Exception as exc:
    print(json.dumps({
        "runner_error": (
            "Result serialization failed: "
            + type(exc).__name__
            + ": "
            + str(exc)
        )
    }))
    sys.exit(1)
'''

    # Create temporary execution files.
    try:
        with tempfile.TemporaryDirectory(
            prefix="modelstump-"
        ) as temp_dir:

            temp_path = Path(temp_dir)

            source_path = temp_path / "candidate.py"
            cases_path = temp_path / "cases.json"
            runner_path = temp_path / "runner.py"

            source_path.write_text(
                source,
                encoding="utf-8",
            )

            cases_path.write_text(
                json.dumps(cases, ensure_ascii=False),
                encoding="utf-8",
            )

            runner_path.write_text(
                harness,
                encoding="utf-8",
            )

            # Do not pass application secrets (API keys, database URLs, etc.)
            # into the candidate process. This reduces accidental exposure;
            # a plain subprocess is still not a secure sandbox.
            allowed_environment = {
                "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
                "TEMP", "TMP",
            }
            env = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in allowed_environment
            }
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONDONTWRITEBYTECODE"] = "1"

            try:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        str(runner_path),
                        str(source_path),
                        str(cases_path),
                        function_name,
                    ],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=EXECUTION_TIMEOUT,
                    env=env,
                )

            except subprocess.TimeoutExpired:
                logger.warning(
                    "Golden solution execution timed out"
                )

                return {
                    "status": "timeout",
                    "error": (
                        f"Execution exceeded "
                        f"{EXECUTION_TIMEOUT} seconds"
                    ),
                    "elapsed_seconds": (
                        time.monotonic() - started
                    ),
                    "results": [],
                }

            except OSError as exc:
                logger.exception(
                    "Could not start execution subprocess"
                )

                return {
                    "status": "execution_error",
                    "error": str(exc),
                    "results": [],
                }

            # Check output size.
            stdout_size = len(
                process.stdout.encode("utf-8")
            )

            stderr_size = len(
                process.stderr.encode("utf-8")
            )

            if max(stdout_size, stderr_size) > MAX_OUTPUT_BYTES:
                return {
                    "status": "execution_error",
                    "error": "Output limit exceeded",
                    "elapsed_seconds": (
                        time.monotonic() - started
                    ),
                    "results": [],
                }

            # Check subprocess exit status.
            if process.returncode != 0:

                error_text = (
                    process.stderr[-2000:]
                    if process.stderr
                    else process.stdout[-2000:]
                )

                logger.warning(
                    "Execution subprocess failed | Exit: %s | stderr bytes: %s",
                    process.returncode,
                    len(process.stderr.encode("utf-8")),
                )

                return {
                    "status": "execution_error",
                    "error": error_text or "Subprocess failed",
                    "elapsed_seconds": (
                        time.monotonic() - started
                    ),
                    "results": [],
                }

            # Parse runner response.
            try:
                response = json.loads(process.stdout)

            except json.JSONDecodeError as exc:
                logger.warning(
                    "Runner returned invalid JSON: %s",
                    exc,
                )

                return {
                    "status": "execution_error",
                    "error": (
                        "Runner returned invalid JSON: "
                        + str(exc)
                    ),
                    "stdout": process.stdout[-1000:],
                    "stderr": process.stderr[-1000:],
                    "elapsed_seconds": (
                        time.monotonic() - started
                    ),
                    "results": [],
                }

            # Detect initialization or serialization errors.
            if isinstance(response, dict):

                return {
                    "status": "execution_error",
                    "error": response.get(
                        "runner_error",
                        "Unexpected runner response",
                    ),
                    "elapsed_seconds": (
                        time.monotonic() - started
                    ),
                    "results": [],
                }

            if not isinstance(response, list):
                return {
                    "status": "execution_error",
                    "error": "Runner response must be a list",
                    "results": [],
                }

            # Verify result count.
            if len(response) != len(cases):
                return {
                    "status": "execution_error",
                    "error": (
                        f"Expected {len(cases)} results, "
                        f"received {len(response)}"
                    ),
                    "results": response,
                }

            # Calculate test statistics.
            passed = sum(
                1
                for result in response
                if isinstance(result, dict)
                and result.get("ok") is True
            )

            failed = len(response) - passed

            elapsed = time.monotonic() - started

            status = (
                "complete"
                if failed == 0
                else "failed"
            )

            logger.info(
                "Execution finished | Status: %s | Passed: %s/%s | Time: %.3fs",
                status,
                passed,
                len(cases),
                elapsed,
            )

            return {
                "status": status,
                "total_tests": len(cases),
                "passed_tests": passed,
                "failed_tests": failed,
                "elapsed_seconds": elapsed,
                "results": response,
            }

    except Exception as exc:
        logger.exception(
            "Unexpected error during code execution"
        )

        return {
            "status": "execution_error",
            "error": (
                type(exc).__name__ + ": " + str(exc)
            ),
            "elapsed_seconds": time.monotonic() - started,
            "results": [],
        }
