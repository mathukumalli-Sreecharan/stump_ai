"""Select the configured candidate execution backend.

Only ``unsafe_subprocess`` is currently implemented. It is intended for
trusted local development and is explicitly reported as not secure.
"""

from backend.config import EXECUTION_BACKEND
from backend.execution.runner import run_cases


def execution_status() -> dict[str, object]:
    if EXECUTION_BACKEND == "unsafe_subprocess":
        return {
            "backend": EXECUTION_BACKEND,
            "secure": False,
            "limitations": [
                "No OS sandbox or restricted identity",
                "No filesystem or network isolation",
                "No memory, file-size, or process-count limit",
                "Child process tree is not reliably constrained",
            ],
        }
    return {
        "backend": EXECUTION_BACKEND,
        "secure": False,
        "available": False,
        "limitations": ["No verified secure execution backend is installed"],
    }


def run_candidate(source: str, function_name: str, cases: list[dict]) -> dict:
    if EXECUTION_BACKEND != "unsafe_subprocess":
        raise RuntimeError(
            f"Execution backend {EXECUTION_BACKEND!r} is unavailable; refusing to execute code"
        )
    return run_cases(source, function_name, cases)
