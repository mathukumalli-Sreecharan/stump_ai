
from backend.schemas import Difficulty, Task, TestCase
from backend.services.test_repair import repair_task_tests
from backend.services.validation import validate_task

task = Task(
    difficulty=Difficulty.medium,
    title="Character Frequency with Deterministic Ordering",
    problem_statement=(
        "Count character frequencies and sort by frequency "
        "descending, then ASCII ascending."
    ),
    input_specification="A string s.",
    output_specification=(
        "Return an ordered list of character-frequency pairs."
    ),
    constraints=["1 <= len(s) <= 1000"],
    expected_behavior=(
        "Count characters and sort by frequency descending, "
        "then ASCII ascending."
    ),
    function_signature="def solve(s: str) -> list[list[str | int]]:",
    edge_case_requirements=["Repeated characters", "Tied frequencies"],
    time_complexity="O(n log n)",
    generation_model="qwen3:4b",
    golden_solution="""
def solve(s):
    freq = {}
    for char in s:
        freq[char] = freq.get(char, 0) + 1

    return [
        [char, count]
        for char, count in sorted(
            freq.items(),
            key=lambda item: (-item[1], ord(item[0]))
        )
    ]
""",
    tests=[
        TestCase(
            test_id="BASE_001",
            input={"s": "aab"},
            expected_output=[["a", 2], ["b", 1]],
            description="Higher frequency sorts first",
            visibility="public",
        ),
        TestCase(
            test_id="BASE_002",
            input={"s": "bb"},
            expected_output=[["b", 2]],
            description="Single distinct character",
            visibility="public",
        ),
        TestCase(
            test_id="BASE_003",
            input={"s": "cab"},
            expected_output=[
                ["a", 1], ["b", 1], ["c", 1]
            ],
            description="Equal counts use ASCII order",
            visibility="hidden",
        ),
        TestCase(
            test_id="BASE_004",
            input={"s": "zzxy"},
            expected_output=[
                ["z", 2], ["x", 1], ["y", 1]
            ],
            description="Frequency sorts before character order",
            visibility="hidden",
        ),
        TestCase(
            test_id="BASE_005",
            input={"s": "aA"},
            expected_output=[
                ["A", 1], ["a", 1]
            ],
            description="ASCII order distinguishes case",
            visibility="hidden",
        ),
    ],
)

coverage = {
    "missing_requirements": ["ascii_ordering"]
}

repair = repair_task_tests(task, coverage)

print("Repair:", repair["status"])
print("Added:", repair["added_test_count"])

report = validate_task(task)

print("\nValidation status:", report["status"])
print("Passed:", report["passed_tests"])
print("Total:", report["total_tests"])

for result in report.get("results", []):
    if not result.get("ok"):
        print("FAILED:", result)

assert repair["added_test_count"] == 3
assert report["status"] == "passed"
assert report["passed_tests"] == report["total_tests"]

print("\nSUCCESS: All original and repaired tests passed.")
