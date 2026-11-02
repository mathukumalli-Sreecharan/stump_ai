
from backend.schemas import Difficulty, Task, TestCase
from backend.services.test_repair import repair_task_tests

task = Task(
    difficulty=Difficulty.medium,
    title="Character Frequency with Deterministic Ordering",
    problem_statement="Count character frequencies and sort by frequency descending, then ASCII ascending.",
    input_specification="A string s.",
    output_specification="Return an ordered list of character-frequency pairs.",
    constraints=["1 <= len(s) <= 1000"],
    expected_behavior="Count characters and sort by frequency descending, then ASCII ascending.",
    function_signature="def solve(s: str) -> list[list[str | int]]:",
    edge_case_requirements=["Repeated characters", "Tied frequencies"],
    time_complexity="O(n log n)",
    generation_model="qwen3:4b",
    golden_solution="""
def solve(s):
    freq = {}
    for char in s:
        freq[char] = freq.get(char, 0) + 1
    return sorted(freq.items(), key=lambda item: (-item[1], ord(item[0])))
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
            expected_output=[["a", 1], ["b", 1], ["c", 1]],
            description="Tied single counts use ASCII order",
            visibility="hidden",
        ),
        TestCase(
            test_id="BASE_004",
            input={"s": "zzxy"},
            expected_output=[["z", 2], ["x", 1], ["y", 1]],
            description="Frequency takes priority over character order",
            visibility="hidden",
        ),
        TestCase(
            test_id="BASE_005",
            input={"s": "aA"},
            expected_output=[["A", 1], ["a", 1]],
            description="ASCII order is case-sensitive",
            visibility="hidden",
        ),
    ],
)

coverage_report = {
    "missing_requirements": ["ascii_ordering"]
}

result = repair_task_tests(task, coverage_report)

print("Repair status:", result["status"])
print("Added tests:", result["added_test_count"])
print("Total task tests:", len(task.tests))

for test in task.tests:
    print(test.test_id, test.input, test.expected_output)
