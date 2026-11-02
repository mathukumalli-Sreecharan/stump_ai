
from backend.main import serialize_public_task
from backend.schemas import Task, TestCase, Difficulty


def test_public_task_excludes_private_data():

    task = Task(
        task_id="TASK_PUBLIC_TEST",
        task_version=1,
        difficulty=Difficulty.easy,
        title="Test public serialization",
        problem_statement="Return the sum of two integers.",
        input_specification="Two integers.",
        output_specification="An integer.",
        expected_behavior="Return their sum.",
        function_signature="def solve(a: int, b: int) -> int:",
        time_complexity="O(1)",
        generation_model="test-model",
        golden_solution="def solve(a, b): return a + b",

        tests=[
            TestCase(
                test_id="PUBLIC_001",
                input={"a": 1, "b": 2},
                expected_output=3,
                visibility="public",
            ),
            TestCase(
                test_id="PUBLIC_002",
                input={"a": 5, "b": 7},
                expected_output=12,
                visibility="public",
            ),
            TestCase(
                test_id="HIDDEN_001",
                input={"a": 10, "b": 20},
                expected_output=30,
                visibility="hidden",
            ),
            TestCase(
                test_id="HIDDEN_002",
                input={"a": 0, "b": 0},
                expected_output=0,
                visibility="hidden",
            ),
            TestCase(
                test_id="HIDDEN_003",
                input={"a": -5, "b": 5},
                expected_output=0,
                visibility="hidden",
            ),
        ],
    )

    # Serialize the task for public API access.
    result = serialize_public_task(task)

    # Verify that only public tests are returned.
    assert len(result["tests"]) == 2

    public_ids = [
        test["test_id"]
        for test in result["tests"]
    ]

    assert public_ids == [
        "PUBLIC_001",
        "PUBLIC_002",
    ]

    # Verify private task fields are excluded.
    assert "golden_solution" not in result
    assert "expected_behavior" not in result
    assert "metadata" not in result

    # Verify expected outputs are excluded.
    for test in result["tests"]:
        assert "expected_output" not in test

    # Verify hidden tests are not exposed.
    result_text = str(result)

    assert "HIDDEN_001" not in result_text
    assert "HIDDEN_002" not in result_text
    assert "HIDDEN_003" not in result_text

    print("\nPUBLIC TASK SERIALIZATION TEST")
    print("--------------------------------")
    print("Task serialization: PASSED")
    print("Public tests returned: 2")
    print("Hidden tests exposed: 0")
    print("Golden solution exposed: False")
    print("Expected outputs exposed: False")
    print("--------------------------------")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    test_public_task_excludes_private_data()
