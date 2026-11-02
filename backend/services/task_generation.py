
import json
import hashlib
import logging
import re
from typing import Any

from backend.config import GENERATOR_MODEL
from backend.schemas import Task
from backend.services.ollama import GENERATION_OPTIONS, OllamaProvider
from backend.services.validation import validate_task
from backend.services.quality import check_specification_coverage
from backend.services.test_repair import repair_task_tests

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

ARCHETYPES = (
    (
        "string_frequency",
        "Count character frequencies in a string, with a precise tie-breaking rule",
    ),
    (
        "intervals",
        "Merge overlapping numeric intervals, including touching endpoints",
    ),
    (
        "dictionary_aggregation",
        "Aggregate keyed records with missing keys and ties",
    ),
    (
        "stack_parsing",
        "Validate nested brackets using a stack",
    ),
    (
        "two_pointers",
        "Find a pair in a sorted list satisfying a target sum",
    ),
    (
        "sliding_window",
        "Find the longest substring with no repeated characters",
    ),
    (
        "matrix_traversal",
        "Traverse a rectangular matrix in a specified order",
    ),
    (
        "set_operations",
        "Compute unique common elements across collections",
    ),
    (
        "binary_search",
        "Find the first occurrence of a target in sorted data",
    ),
    (
        "run_length_encoding",
        "Compress consecutive equal characters into counts",
    ),
    (
        "graph_traversal",
        "Traverse a graph and compute reachability under explicit rules",
    ),
    (
        "tree_recursion",
        "Recursively inspect a tree structure and combine child results",
    ),
    (
        "dynamic_programming",
        "Optimize a sequence of decisions using overlapping subproblems",
    ),
    (
        "greedy_selection",
        "Select compatible items using a provable local choice rule",
    ),
    (
        "state_machine",
        "Process events while maintaining a finite state and transition rules",
    ),
    (
        "scheduling",
        "Assign jobs to time slots while respecting precedence and capacity",
    ),
    (
        "data_transformation",
        "Transform structured records while preserving specified invariants",
    ),
    (
        "nested_parsing",
        "Parse a small nested expression format with explicit grammar rules",
    ),
    (
        "queue_simulation",
        "Simulate arrivals and service events with first-in-first-out rules",
    ),
)

MIN_TESTS = 8
MIN_PUBLIC_TESTS = 2
MIN_HIDDEN_TESTS = 2
MIN_MANDATORY_TESTS = 2

SYSTEM_PROMPT = """
/no_think
You are an expert Python programming benchmark designer.

Return exactly one valid JSON object.
Do not return Markdown fences, explanations, comments, or text outside JSON.

Rules:
- Follow the requested JSON schema exactly.
- Every test input must be a JSON object.
- Every test input must use the function's parameter names as keys.
- Every test must have a concrete expected_output.
- The golden_solution must implement the problem specification.
- The golden_solution must pass every supplied test.
- Never invent test results.
- Use only standard-library Python.
- Do not include chain of thought.
- Verify every golden solution against every supplied test.
- Never change expected outputs just to make the golden solution pass.
- Never remove tests to hide failures.
- Follow the problem statement exactly.
- Correct logical mistakes before returning the JSON.
"""

TASK_PROMPT = """
Create one original {difficulty} Python programming benchmark about:
{topic}

MANDATORY PROBLEM ARCHETYPE:
{archetype_name}

ARCHETYPE DESCRIPTION:
{archetype_description}

The task must genuinely implement this archetype.
Do not replace it with a generic list validation problem.
Do not use a previously generated problem structure.

Return exactly one JSON object with these required top-level fields:

{{
  "title": "A concise task title",
  "problem_statement": "Complete problem description",
  "input_specification": "Description of function inputs",
  "output_specification": "Description of return value",
  "constraints": ["constraint 1", "constraint 2"],
  "expected_behavior": "Precise expected behavior",
  "function_signature": "def solve(values: list[int]) -> bool:",
  "edge_case_requirements": ["empty input", "negative values"],
  "time_complexity": "O(n)",
  "golden_solution": "def solve(values):\\n    return ...",
  "tests": []
}}

TEST SCHEMA:

Every test must be an object with these required fields:

{{
  "test_id": "TC001",
  "input": {{"values": [1, 2, 3]}},
  "expected_output": true,
  "category": "normal",
  "description": "Checks a normal input",
  "mandatory": true,
  "visibility": "public"
}}

IMPORTANT TEST INPUT RULES:

1. "input" MUST ALWAYS be a JSON object/dictionary.
2. The keys inside "input" MUST match the function parameters.
3. Never use a list, number, string, or null directly as "input".
4. Put lists and other values inside the parameter dictionary.
5. Every expected_output must be a valid JSON value.
6. Do not use Python-specific values such as None, True, or False
   in JSON. Use null, true, and false.
7. Do not omit any required field.

TEST REQUIREMENTS:

- Generate at least {min_tests} tests.
- At least {min_public} tests must have visibility "public".
- At least {min_hidden} tests must have visibility "hidden".
- Use exactly lowercase "public" and "hidden".
- Include normal cases.
- Include boundary cases.
- Include edge cases.
- Include adversarial cases where appropriate.
- Test empty input where meaningful.
- Test negative values where meaningful.
- Test duplicate values where meaningful.
- Test minimum and maximum constraints where meaningful.
- Ensure all test IDs are unique.

GOLDEN SOLUTION REQUIREMENTS:

- Implement the exact problem specification.
- Match the function_signature.
- Use only standard-library Python.
- Return the expected type.
- Handle all specified edge cases.
- Do not read input from stdin.
- Do not print output.
- Do not include a main block.
- Do not use external dependencies.

Before returning the JSON, independently check every test against
the golden solution.

The golden solution and all expected outputs must agree.

Return valid JSON only.
""".replace(
    "{min_tests}", str(MIN_TESTS)
).replace(
    "{min_public}", str(MIN_PUBLIC_TESTS)
).replace(
    "{min_hidden}", str(MIN_HIDDEN_TESTS)
)


def extract_json(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        raise ValueError("Ollama returned an empty response")

    candidate = re.sub(
        r"^\s*```(?:json)?\s*|\s*```\s*$",
        "",
        raw.strip(),
        flags=re.IGNORECASE,
    )

    try:
        result = json.loads(candidate)

        if isinstance(result, dict):
            return result

    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()

    for index, char in enumerate(candidate):
        if char != "{":
            continue

        try:
            result, _ = decoder.raw_decode(candidate[index:])

            if isinstance(result, dict):
                return result

        except json.JSONDecodeError:
            continue

    raise ValueError(
        "Could not extract valid JSON from Ollama response. "
        "Return one complete JSON object without Markdown."
    )


def validate_generated_data(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Generated task must be a JSON object")

    required = {
        "title",
        "problem_statement",
        "input_specification",
        "output_specification",
        "constraints",
        "expected_behavior",
        "function_signature",
        "edge_case_requirements",
        "time_complexity",
        "golden_solution",
        "tests",
    }

    missing = sorted(required - data.keys())

    if missing:
        raise ValueError(
            f"Generated task is missing fields: {missing}. "
            "Return every required top-level field."
        )

    text_fields = [
        "title",
        "problem_statement",
        "input_specification",
        "output_specification",
        "expected_behavior",
        "function_signature",
        "time_complexity",
        "golden_solution",
    ]

    for field in text_fields:
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(
                f"Field '{field}' must be a non-empty string"
            )

    for field in ("constraints", "edge_case_requirements"):
        if not isinstance(data[field], list):
            raise ValueError(
                f"Field '{field}' must be a JSON array"
            )

    if not isinstance(data["tests"], list):
        raise ValueError("Field 'tests' must be a JSON array")

    if len(data["tests"]) < MIN_TESTS:
        raise ValueError(
            f"Generated task must contain at least {MIN_TESTS} tests; "
            f"received {len(data['tests'])}"
        )

    required_test_fields = {
        "test_id",
        "input",
        "expected_output",
        "category",
        "description",
        "mandatory",
        "visibility",
    }

    seen_ids = set()
    seen_cases = set()
    mandatory_count = 0

    visibility_counts = {
        "public": 0,
        "hidden": 0,
    }

    for index, test in enumerate(data["tests"], start=1):

        if not isinstance(test, dict):
            raise ValueError(
                f"Test {index} must be a JSON object"
            )

        missing_test_fields = sorted(
            required_test_fields - test.keys()
        )

        if missing_test_fields:
            raise ValueError(
                f"Test {index} is missing fields: "
                f"{missing_test_fields}"
            )

        if not isinstance(test["input"], dict):
            raise ValueError(
                f"Test {index} input must be a JSON object/dictionary. "
                "Use function parameter names as keys."
            )

        test_id = test["test_id"]

        if isinstance(test_id, int) and not isinstance(test_id, bool):
            test_id = f"TC{test_id:03d}"
            test["test_id"] = test_id

        if not isinstance(test_id, str) or not test_id.strip():
            raise ValueError(
                f"Test {index} test_id must be a non-empty string"
            )

        if test_id in seen_ids:
            raise ValueError(
                f"Duplicate test_id '{test_id}'. "
                "Every test ID must be unique."
            )

        seen_ids.add(test_id)

        test_visibility = test["visibility"]

        if test_visibility not in {"public", "hidden"}:
            raise ValueError(
                f"Test {index} visibility must be exactly "
                "'public' or 'hidden'."
            )

        if not isinstance(test["mandatory"], bool):
            raise ValueError(
                f"Test {index} mandatory must be a boolean"
            )

        if test["mandatory"]:
            mandatory_count += 1

        case_signature = json.dumps(
            [test["input"], test["expected_output"]],
            sort_keys=True,
            ensure_ascii=False,
            default=repr,
        )
        if case_signature in seen_cases:
            raise ValueError(
                f"Test {index} duplicates an existing input and expected output"
            )
        seen_cases.add(case_signature)

        if not isinstance(test["category"], str):
            raise ValueError(
                f"Test {index} category must be a string"
            )

        if not isinstance(test["description"], str):
            raise ValueError(
                f"Test {index} description must be a string"
            )

        visibility_counts[test_visibility] += 1

    if visibility_counts["public"] < MIN_PUBLIC_TESTS:
        raise ValueError("Insufficient public tests")

    if visibility_counts["hidden"] < MIN_HIDDEN_TESTS:
        raise ValueError("Insufficient hidden tests")

    if mandatory_count < MIN_MANDATORY_TESTS:
        raise ValueError(
            f"At least {MIN_MANDATORY_TESTS} tests must be mandatory"
        )


def build_validation_feedback(
    task: Task,
    report: dict[str, Any],
) -> dict[str, Any]:

    failed_cases = []

    for result in report.get("validation_errors", []):
        failed_cases.append({
            "test_id": result.get("test_id"),
            "input": result.get("input"),
            "expected_output": result.get("expected"),
            "actual_output": result.get("actual"),
            "error": result.get("error"),
            "category": result.get("category"),
            "description": result.get("description"),
        })

    execution_error = report.get("error")

    if execution_error:
        failed_cases.append({
            "failure_type": "overall_execution_error",
            "error": execution_error,
        })

    return {
        "previous_task_title": task.title,
        "problem_statement": task.problem_statement,
        "function_signature": task.function_signature,
        "rejected_golden_solution": task.golden_solution,
        "validation_status": report.get("status"),
        "passed_tests": report.get("passed_tests", 0),
        "failed_tests": report.get("failed_tests", 0),
        "total_tests": report.get(
            "total_tests",
            len(task.tests),
        ),
        "failed_cases": failed_cases,
        "validation_error": execution_error,
        "correction_instructions": [
            "The previous golden solution failed validation.",
            "Inspect the execution error and every failed test.",
            "Identify the precise logical, syntax, or execution error.",
            "Correct the golden solution to match the original specification.",
            "Preserve all original tests.",
            "Do not remove failing tests.",
            "Do not weaken the problem specification.",
            "Do not change expected outputs to hide failures.",
            "Do not hardcode answers for individual test cases.",
            "Ensure the function signature remains correct.",
            "Return a complete corrected JSON task.",
            "Check every test against the corrected golden solution.",
        ],
    }


def build_adaptive_instructions(
    context: dict[str, Any],
) -> str:

    weakness = context.get("weakness", "unknown")
    examples = context.get("examples", [])
    previous_titles = context.get("previous_task_titles", [])

    return f"""

ADAPTIVE GENERATION MODE

Create a NEW programming benchmark targeting this observed weakness:

{weakness}

Previous evaluation evidence:
{json.dumps(examples, ensure_ascii=False, indent=2, default=str)}

Previously evaluated task titles to avoid:
{json.dumps(previous_titles, ensure_ascii=False, indent=2)}

Requirements:

1. Test the underlying capability, not merely the original question.
2. Use a different problem statement and algorithmic structure.
3. Do not just change numbers or variable names.
4. Include tests that directly exercise the identified weakness.
5. Include additional correctness and edge-case tests.
6. Ensure the golden solution matches the new specification.
7. Do not assume that the evidence proves a general model weakness.
8. Return a complete JSON task using the required schema.
"""


def build_format_feedback(error: Exception) -> dict[str, Any]:

    message = str(error)

    instructions = [
        "Return exactly one complete JSON object.",
        "Include every required top-level field.",
        f"Generate at least {MIN_TESTS} tests.",
        "Every test must be a JSON object.",
        "Every test input must be a JSON object/dictionary.",
        'Example input: {"values": [1, 2, 3]}',
        "Every test must contain all required fields.",
        "Use true, false, and null for JSON values.",
        "Return golden_solution as a JSON string containing Python source.",
        "Do not return Markdown or explanatory text.",
        f'At least {MIN_PUBLIC_TESTS} tests must use visibility "public".',
        f'At least {MIN_HIDDEN_TESTS} tests must use visibility "hidden".',
        'Use exactly lowercase "public" and "hidden".',
        "Keep all test IDs unique.",
    ]

    if "visibility" in message.lower():
        instructions.extend([
            "The previous candidate failed the visibility requirements.",
            'Explicitly assign "public" to at least two tests.',
            'Explicitly assign "hidden" to at least two tests.',
            "Do not assign the same visibility to every test.",
        ])

    if "input must be a json object" in message.lower():
        instructions.extend([
            "The previous candidate used an invalid test input.",
            "Every input must be a dictionary keyed by function parameters.",
            'Correct example: {"values": [1, 2, 3]}.',
        ])

    if "missing fields" in message.lower():
        instructions.append(
            "The previous candidate omitted required fields. "
            "Check the entire schema before returning."
        )

    return {
        "previous_attempt_error": (
            f"{type(error).__name__}: {message}"
        ),
        "correction_instructions": instructions,
    }


def choose_archetype(
    existing_tasks: list[Task] | None = None,
    attempt: int = 0,
) -> tuple[str, str]:

    existing_tasks = existing_tasks or []

    used_archetypes = {
        (task.metadata or {}).get("archetype")
        for task in existing_tasks
    }

    available = [
        item for item in ARCHETYPES
        if item[0] not in used_archetypes
    ]

    if not available:
        available = list(ARCHETYPES)

    return available[attempt % len(available)]


def build_diversity_feedback(
    candidate: Task,
    existing_tasks: list[Task],
) -> dict[str, Any]:

    from backend.services.quality import calculate_similarity

    similarity = calculate_similarity(
        candidate,
        existing_tasks,
    )

    return {
        "similarity": similarity.get("similarity", 0),
        "status": similarity.get("status"),
        "most_similar_task_id": similarity.get(
            "most_similar_task_id"
        ),
        "instruction": (
            "Create a structurally different problem. "
            "Do not reuse the same algorithmic objective, "
            "input structure, or solution approach."
        ),
    }


async def repair_and_validate_task(task: Task) -> dict[str, Any]:
    """
    Check specification coverage, repair supported missing tests,
    and validate the golden solution again.

    Failed validation reports are returned to generate_task
    so detailed failure evidence can be sent to Ollama.
    """

    initial_coverage = check_specification_coverage(task)

    repair_report = repair_task_tests(
        task,
        initial_coverage,
    )

    validation_report = validate_task(task)

    repair_metadata = {
        "initial_coverage": initial_coverage,
        "repair_status": repair_report.get("status"),
        "repair_message": repair_report.get("message"),
        "added_test_count": repair_report.get(
            "added_test_count",
            0,
        ),
        "added_test_ids": [
            test["test_id"]
            for test in repair_report.get("added_tests", [])
        ],
    }

    task.metadata = task.metadata or {}
    task.metadata["test_repair"] = repair_metadata

    if validation_report.get("status") != "passed":
        return {
            "validation": validation_report,
            "repair": repair_metadata,
            "coverage": initial_coverage,
        }

    final_coverage = check_specification_coverage(task)

    repair_metadata["final_coverage"] = final_coverage

    return {
        "validation": validation_report,
        "repair": repair_metadata,
        "coverage": final_coverage,
    }


async def generate_task(
    difficulty: str,
    topic: str,
    adaptive_context: dict[str, Any] | None = None,
    existing_tasks: list[Task] | None = None,
) -> Task:

    provider = OllamaProvider(GENERATOR_MODEL)

    if not await provider.available():
        raise RuntimeError(
            f"Ollama model '{GENERATOR_MODEL}' is unavailable. "
            f"Start Ollama and run: ollama pull {GENERATOR_MODEL}"
        )

    existing_tasks = existing_tasks or []

    last_error: Exception | None = None
    retry_feedback: dict[str, Any] | None = None
    archetype_name: str | None = None
    retry_archetype: str | None = None

    # Records each generation attempt for successful task metadata.
    retry_history: list[dict[str, Any]] = []

    for attempt in range(MAX_ATTEMPTS):

        specific_feedback_created = False
        prompt_sha256: str | None = None

        try:
            if retry_archetype:
                archetype = next(
                    (item for item in ARCHETYPES if item[0] == retry_archetype),
                    None,
                )
                if archetype is None:
                    archetype_name, archetype_description = choose_archetype(
                        existing_tasks,
                        attempt,
                    )
                else:
                    archetype_name, archetype_description = archetype
            else:
                archetype_name, archetype_description = choose_archetype(
                    existing_tasks,
                    attempt,
                )

            prompt = TASK_PROMPT.format(
                difficulty=difficulty,
                topic=topic,
                archetype_name=archetype_name,
                archetype_description=archetype_description,
            )

            if adaptive_context:
                prompt += build_adaptive_instructions(
                    adaptive_context
                )

            # Include feedback from the previous failed attempt.
            if retry_feedback:
                prompt += (
                    "\n\nRETRY INSTRUCTIONS:\n"
                    + json.dumps(
                        retry_feedback,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                )

            prompt_sha256 = hashlib.sha256(
                (SYSTEM_PROMPT + "\n" + prompt).encode("utf-8")
            ).hexdigest()

            raw = await provider.generate(
                prompt,
                SYSTEM_PROMPT,
            )

            data = extract_json(raw)

            validate_generated_data(data)

            metadata = data.get("metadata", {})

            if not isinstance(metadata, dict):
                metadata = {}

            metadata["archetype"] = archetype_name
            metadata["generation_config"] = {
                "prompt_version": "benchmark_task_v1",
                "prompt_sha256": prompt_sha256,
                "model": GENERATOR_MODEL,
                "parameters": dict(GENERATION_OPTIONS),
            }

            if adaptive_context:
                metadata.update({
                    "generation_type": "adaptive",
                    "parent_task_id": adaptive_context.get(
                        "parent_task_id"
                    ),
                    "parent_task_version": adaptive_context.get(
                        "parent_task_version"
                    ),
                    "parent_evaluation_id": adaptive_context.get(
                        "parent_evaluation_id"
                    ),
                    "target_weakness": adaptive_context.get(
                        "weakness"
                    ),
                    "generation_round": adaptive_context.get(
                        "generation_round",
                        1,
                    ),
                    "weakness_evidence_task_ids": adaptive_context.get(
                        "task_ids",
                        [],
                    ),
                })

            else:
                metadata.setdefault(
                    "generation_type",
                    "standard",
                )

            data.update({
                "category": "python_coding",
                "difficulty": difficulty,
                "generation_model": GENERATOR_MODEL,
                "metadata": metadata,
            })

            task = Task.model_validate(data)

            pipeline_report = await repair_and_validate_task(task)

            report = pipeline_report["validation"]
            coverage = pipeline_report["coverage"]

            # STEP 1: Golden solution validation.
            if report.get("status") != "passed":

                retry_feedback = build_validation_feedback(
                    task,
                    report,
                )
                # This feedback describes this exact task and its signature.
                # Keep the same archetype so the next prompt does not ask the
                # model to repair one task while generating an unrelated one.
                retry_archetype = archetype_name

                specific_feedback_created = True

                raise ValueError(
                    "Golden solution failed validation: "
                    f"{report.get('passed_tests', 0)}/"
                    f"{report.get('total_tests', 0)} passed"
                )

            # STEP 2: Critical specification coverage.
            if not coverage.get(
                "critical_requirements_satisfied",
                False,
            ):

                retry_feedback = {
                    "missing_requirements": coverage.get(
                        "critical_missing",
                        [],
                    ),
                    "coverage_report": coverage,
                    "repair_report": pipeline_report["repair"],
                    "instruction": (
                        "The generated task does not adequately test "
                        "all critical requirements. Generate tests that "
                        "verify every critical requirement. Do not weaken "
                        "or remove requirements from the specification."
                    ),
                }
                retry_archetype = archetype_name

                specific_feedback_created = True

                raise ValueError(
                    "Critical specification requirements remain uncovered: "
                    f"{coverage.get('critical_missing', [])}"
                )

            # STEP 3: Diversity validation.
            diversity = build_diversity_feedback(
                task,
                existing_tasks,
            )

            if diversity["status"] in {
                "duplicate",
                "too_similar",
            }:

                retry_feedback = {
                    "diversity_rejection": diversity,
                    "instruction": (
                        "The previous task was too similar to an existing "
                        "benchmark. Create a different algorithmic problem "
                        "using a different archetype and solution structure."
                    ),
                }
                retry_archetype = None

                specific_feedback_created = True

                # Record duplicate rejection before continuing.
                retry_history.append({
                    "attempt": attempt + 1,
                    "status": "rejected_duplicate",
                    "archetype": archetype_name,
                    "error": "Candidate was too similar to an existing task",
                    "diversity_report": diversity,
                    "feedback_sent_to_next_attempt": retry_feedback,
                })

                logger.warning(
                    "Duplicate candidate rejected | Attempt: %s | "
                    "Similarity: %s",
                    attempt + 1,
                    diversity["similarity"],
                )

                continue

            # STEP 4: Record successful attempt.
            retry_history.append({
                "attempt": attempt + 1,
                "status": "passed",
                "archetype": archetype_name,
                "error": None,
                "feedback_sent_to_attempt": retry_feedback,
                "prompt_sha256": prompt_sha256,
                "validation": {
                    "status": report.get("status"),
                    "passed_tests": report.get("passed_tests", 0),
                    "failed_tests": report.get("failed_tests", 0),
                    "total_tests": report.get("total_tests", 0),
                },
                "coverage_score": coverage.get("score", 0),
            })

            task.metadata = task.metadata or {}

            task.metadata["retry_history"] = retry_history
            task.metadata["generation_attempts"] = attempt + 1

            logger.info(
                "Test repair completed | Task: %s | Added tests: %s | "
                "Coverage: %s%%",
                task.task_id,
                task.metadata["test_repair"]["added_test_count"],
                coverage.get("score", 0),
            )

            logger.info(
                "Task generated | ID: %s | Archetype: %s | "
                "Tests: %s | Attempt: %s",
                task.task_id,
                archetype_name,
                len(task.tests),
                attempt + 1,
            )

            return task

        except Exception as exc:
            last_error = exc

            if not specific_feedback_created:
                retry_feedback = build_format_feedback(exc)
                retry_archetype = None

            # Record the failed attempt and the feedback prepared
            # for the next generation attempt.
            retry_history.append({
                "attempt": attempt + 1,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "prompt_sha256": prompt_sha256,
                "archetype": (
                    archetype_name
                    if "archetype_name" in locals()
                    else None
                ),
                "feedback_sent_to_next_attempt": retry_feedback,
            })

            logger.exception(
                "Task generation attempt %s/%s failed",
                attempt + 1,
                MAX_ATTEMPTS,
            )

    # All attempts failed.
    # Include history in the exception so the caller can inspect it.
    history_summary = json.dumps(
        retry_history,
        ensure_ascii=False,
        default=str,
    )

    raise RuntimeError(
        f"Task generation failed after {MAX_ATTEMPTS} attempts. "
        f"Last error: {last_error}. "
        f"Retry history: {history_summary}"
    ) from last_error
