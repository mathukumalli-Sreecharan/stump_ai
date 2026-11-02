
import ast
import re
from difflib import SequenceMatcher


# =========================================================
# TEXT NORMALIZATION AND CONCEPT EXTRACTION
# =========================================================

def normalize_text(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def get_task_text(task) -> str:
    return normalize_text(
        f"{task.title} {task.problem_statement}"
    )


def extract_concepts(task) -> set[str]:
    text = get_task_text(task)

    concept_patterns = {
        "lists": ["list", "array", "sequence"],
        "strings": ["string", "substring", "character", "text"],
        "dictionaries": ["dictionary", "dict", "key", "value", "frequency"],
        "sorting": ["sort", "ascending", "descending", "ordered"],
        "searching": ["search", "find", "locate", "binary search"],
        "sequences": ["consecutive", "sequence", "adjacent"],
        "mathematics": ["prime", "factor", "number", "integer", "divisor"],
        "graphs": ["graph", "node", "edge", "path", "traversal"],
        "recursion": ["recursive", "recursion", "call itself"],
        "dynamic_programming": [
            "dynamic programming",
            "memoization",
            "subproblem",
        ],
        "sets": ["set", "unique", "distinct"],
        "stack_queue": ["stack", "queue", "fifo", "lifo"],
    }

    found = set()

    for concept, keywords in concept_patterns.items():
        if any(keyword in text for keyword in keywords):
            found.add(concept)

    return found


def solution_structure(task) -> str:
    """Normalize identifiers and literals, retaining algorithm structure."""
    source = getattr(task, "golden_solution", "") or ""
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError):
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            node.id = "NAME"
        elif isinstance(node, ast.arg):
            node.arg = "ARG"
        elif isinstance(node, ast.Constant):
            node.value = "CONST"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.name = "FUNCTION"
    return ast.dump(tree, include_attributes=False)


def task_archetype(task) -> str | None:
    metadata = getattr(task, "metadata", None) or {}
    value = metadata.get("archetype") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) else None


# =========================================================
# TASK DIVERSITY
# =========================================================

def calculate_similarity(task, existing_tasks: list) -> dict:
    candidate_text = get_task_text(task)
    candidate_concepts = extract_concepts(task)
    candidate_structure = solution_structure(task)
    candidate_archetype = task_archetype(task)

    best_similarity = 0.0
    most_similar_task = None
    concept_similarity = 0.0
    structure_similarity = 0.0
    same_archetype = False

    for existing in existing_tasks:
        existing_text = get_task_text(existing)

        text_similarity = SequenceMatcher(
            None,
            candidate_text,
            existing_text,
        ).ratio()

        existing_concepts = extract_concepts(existing)

        if candidate_concepts or existing_concepts:
            union = candidate_concepts | existing_concepts
            intersection = candidate_concepts & existing_concepts

            current_concept_similarity = (
                len(intersection) / len(union)
                if union else 0.0
            )
        else:
            current_concept_similarity = 0.0

        existing_structure = solution_structure(existing)
        current_structure_similarity = (
            SequenceMatcher(None, candidate_structure, existing_structure).ratio()
            if candidate_structure and existing_structure
            else 0.0
        )
        existing_archetype = task_archetype(existing)
        current_same_archetype = bool(
            candidate_archetype
            and existing_archetype
            and candidate_archetype == existing_archetype
        )

        combined_similarity = (
            0.40 * text_similarity
            + 0.20 * current_concept_similarity
            + 0.25 * current_structure_similarity
            + 0.15 * float(current_same_archetype)
        )

        if combined_similarity > best_similarity:
            best_similarity = combined_similarity
            most_similar_task = existing.task_id
            concept_similarity = current_concept_similarity
            structure_similarity = current_structure_similarity
            same_archetype = current_same_archetype

    if best_similarity >= 0.85:
        uniqueness_score = 0
        status = "duplicate"

    elif best_similarity >= 0.65:
        uniqueness_score = 2
        status = "too_similar"

    elif best_similarity >= 0.45:
        uniqueness_score = 4
        status = "some_similarity"

    else:
        uniqueness_score = 5
        status = "unique"

    return {
        "score": uniqueness_score,
        "status": status,
        "similarity": round(best_similarity, 3),
        "concept_similarity": round(concept_similarity, 3),
        "solution_structure_similarity": round(structure_similarity, 3),
        "same_archetype": same_archetype,
        "most_similar_task_id": most_similar_task,
    }


# =========================================================
# SPECIFICATION-TO-TEST COVERAGE
# =========================================================

REQUIREMENT_PATTERNS = {
    "ascii_ordering": {
        "keywords": [
            "ascii",
            "character order",
            "character ordering",
            "ascending order",
            "alphabetical order",
            "lexicographic order",
            "tie break",
            "ties",
        ],
        "critical": True,
    },

    "frequency_counting": {
        "keywords": [
            "frequency",
            "count occurrences",
            "count each",
            "count the frequency",
            "number of times",
            "occurrences",
            "how many times",
            "frequency count",
        ],
        "critical": True,
    },

    "empty_input": {
        "keywords": [
            "empty string",
            "empty input",
            "empty list",
            "no elements",
        ],
        "critical": False,
    },

    "case_sensitivity": {
        "keywords": [
            "case sensitive",
            "uppercase",
            "lowercase",
            "capital letters",
        ],
        "critical": False,
    },

    "duplicate_handling": {
        "keywords": [
            "duplicate",
            "repeated character",
            "repeated element",
            "repetitions",
        ],
        "critical": False,
    },

    "negative_values": {
        "keywords": [
            "negative",
            "below zero",
        ],
        "critical": False,
    },

    "boundary_conditions": {
        "keywords": [
            "maximum",
            "minimum",
            "boundary",
            "limit",
            "large input",
        ],
        "critical": False,
    },
}


def get_test_text(test) -> str:
    if hasattr(test, "model_dump"):
        test = test.model_dump()

    return normalize_text(
        f"{test.get('description', '')} "
        f"{test.get('category', '')} "
        f"{test.get('input', {})} "
        f"{test.get('expected_output', '')}"
    )


def get_test_input(test) -> dict:
    return test.get("input", {}) or {}


# =========================================================
# FREQUENCY OUTPUT HELPERS
# =========================================================

def parse_frequency_output(expected):
    """
    Convert supported frequency outputs into character/count pairs.

    Supported formats:

    Dictionary:
        {"a": 2, "b": 1}

    Ordered list:
        [["a", 2], ["b", 1]]

    Returns None if the output is not a valid frequency structure.
    """

    if isinstance(expected, dict):
        pairs = list(expected.items())

    elif isinstance(expected, list):
        pairs = []

        for item in expected:
            if not isinstance(item, (list, tuple)):
                return None

            if len(item) != 2:
                return None

            pairs.append((item[0], item[1]))

    else:
        return None

    normalized = []

    for char, count in pairs:
        if not isinstance(char, str) or len(char) != 1:
            return None

        if isinstance(count, bool) or not isinstance(count, int):
            return None

        if count <= 0:
            return None

        normalized.append((char, count))

    if len({char for char, _ in normalized}) != len(normalized):
        return None

    return normalized


def frequency_counts_match_input(test, pairs) -> bool:
    """
    Verify that expected frequencies actually match the input string.
    """

    input_data = get_test_input(test)
    input_string = input_data.get("s")

    if not isinstance(input_string, str):
        return False

    actual_counts = {}

    for char in input_string:
        actual_counts[char] = actual_counts.get(char, 0) + 1

    expected_counts = dict(pairs)

    return actual_counts == expected_counts


def has_valid_frequency_test(tests) -> bool:
    for test in tests:
        expected = test.get("expected_output")
        pairs = parse_frequency_output(expected)

        if pairs is None:
            continue

        if frequency_counts_match_input(test, pairs):
            return True

    return False


# =========================================================
# ASCII ORDERING VERIFICATION
# =========================================================

def has_valid_ascii_ordering_test(tests) -> bool:
    """
    Check whether at least one test verifies a tied-frequency
    ordering requirement.

    Correct ordering:
        1. Frequency descending.
        2. ASCII value ascending for equal frequencies.
    """

    for test in tests:
        expected = test.get("expected_output")

        # A dictionary cannot reliably verify output ordering.
        if not isinstance(expected, list):
            continue

        pairs = parse_frequency_output(expected)

        if pairs is None:
            continue

        if not frequency_counts_match_input(test, pairs):
            continue

        frequencies = [count for _, count in pairs]

        # There must be at least two characters with equal frequency.
        has_tie = len(set(frequencies)) < len(frequencies)

        if not has_tie:
            continue

        # Verify the complete ordering rule.
        correctly_ordered = pairs == sorted(
            pairs,
            key=lambda item: (
                -item[1],
                ord(item[0]),
            ),
        )

        if correctly_ordered:
            return True

    return False


# =========================================================
# REQUIREMENT COVERAGE CHECKER
# =========================================================

def check_specification_coverage(task) -> dict:
    statement = normalize_text(
        f"{task.problem_statement} "
        f"{task.expected_behavior} "
        f"{task.output_specification}"
    )

    tests = [
        test.model_dump()
        if hasattr(test, "model_dump")
        else test
        for test in task.tests
    ]

    detected_requirements = []
    covered_requirements = []
    missing_requirements = []
    critical_missing = []

    for requirement, config in REQUIREMENT_PATTERNS.items():

        keywords = config["keywords"]

        mentioned = any(
            keyword in statement
            for keyword in keywords
        )

        if not mentioned:
            continue

        detected_requirements.append(requirement)

        evidence = False

        # -------------------------------------------------
        # ASCII ORDERING
        # -------------------------------------------------

        if requirement == "ascii_ordering":
            evidence = has_valid_ascii_ordering_test(tests)

        # -------------------------------------------------
        # FREQUENCY COUNTING
        # -------------------------------------------------

        elif requirement == "frequency_counting":
            evidence = has_valid_frequency_test(tests)

        # -------------------------------------------------
        # EMPTY INPUT
        # -------------------------------------------------

        elif requirement == "empty_input":
            evidence = any(
                value == "" or value == [] or value == {}
                for test in tests
                for value in get_test_input(test).values()
            )

        # -------------------------------------------------
        # CASE SENSITIVITY
        # -------------------------------------------------

        elif requirement == "case_sensitivity":
            evidence = any(
                isinstance(value, str)
                and any(char.isupper() for char in value)
                and any(char.islower() for char in value)
                for test in tests
                for value in get_test_input(test).values()
            )

        # -------------------------------------------------
        # DUPLICATE HANDLING
        # -------------------------------------------------

        elif requirement == "duplicate_handling":
            evidence = any(
                isinstance(value, (str, list))
                and len(value) != len(set(value))
                for test in tests
                for value in get_test_input(test).values()
                if isinstance(value, (str, list))
            )

        # -------------------------------------------------
        # NEGATIVE VALUES
        # -------------------------------------------------

        elif requirement == "negative_values":
            evidence = any(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value < 0
                for test in tests
                for value in get_test_input(test).values()
            )

        # -------------------------------------------------
        # BOUNDARY CONDITIONS
        # -------------------------------------------------

        elif requirement == "boundary_conditions":
            evidence = any(
                "edge" in str(test.get("category", "")).lower()
                or "boundary" in str(
                    test.get("description", "")
                ).lower()
                for test in tests
            )

        # -------------------------------------------------
        # RECORD RESULTS
        # -------------------------------------------------

        if evidence:
            covered_requirements.append(requirement)

        else:
            missing_requirements.append(requirement)

            if config["critical"]:
                critical_missing.append(requirement)

    total = len(detected_requirements)
    covered = len(covered_requirements)

    coverage_percentage = (
        round(covered / total * 100, 2)
        if total
        else 100.0
    )

    return {
        "score": coverage_percentage,
        "total_requirements": total,
        "covered_requirements": covered_requirements,
        "missing_requirements": missing_requirements,
        "critical_missing": critical_missing,
        "critical_requirements_satisfied": not critical_missing,
        "status": (
            "complete"
            if not missing_requirements
            else "incomplete"
        ),
    }


# =========================================================
# TASK QUALITY SCORING
# =========================================================

def score_task(
    task,
    validation: dict,
    existing_tasks: list | None = None,
) -> dict:

    existing_tasks = existing_tasks or []

    prompt_quality = (
        15
        if (
            task.problem_statement
            and task.input_specification
            and task.output_specification
        )
        else 0
    )

    golden_solution_validity = (
        25
        if validation.get("status") == "passed"
        else 0
    )

    test_coverage = min(20, len(task.tests) * 2)

    specification_coverage = check_specification_coverage(task)

    specification_coverage_score = round(
        10 * specification_coverage["score"] / 100
    )

    expected_output_verification = (
        15
        if (
            validation.get("status") == "passed"
            and validation.get("failed_tests") == 0
        )
        else 0
    )

    difficulty_consistency = (
        10
        if task.constraints and task.time_complexity
        else 5
    )

    uniqueness = calculate_similarity(
        task,
        existing_tasks,
    )

    reproducibility = (
        5 if task.generation_model else 0
    )

    scores = {
        "prompt_quality": prompt_quality,
        "golden_solution_validity": golden_solution_validity,
        "test_coverage": test_coverage,
        "expected_output_verification": expected_output_verification,
        "specification_coverage": specification_coverage_score,
        "difficulty_consistency": difficulty_consistency,
        "uniqueness": uniqueness["score"],
        "reproducibility": reproducibility,
    }

    total = sum(scores.values())

    accepted = (
        total >= 80
        and golden_solution_validity == 25
        and uniqueness["status"] not in {
            "duplicate",
            "too_similar",
        }
        and specification_coverage[
            "critical_requirements_satisfied"
        ]
    )

    return {
        "score": total,
        "accepted": accepted,
        "dimensions": scores,
        "diversity": uniqueness,
        "specification_coverage": specification_coverage,
    }
