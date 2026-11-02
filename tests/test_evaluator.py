import asyncio

from backend.schemas import Difficulty, Task, TestCase
from backend.services import evaluator


def make_eval_task():
    return Task(
        task_id="TASK_EVALUATOR_TEST",
        difficulty=Difficulty.easy,
        title="Count values",
        problem_statement="Return the number of values.",
        input_specification="A list named values.",
        output_specification="Return an integer.",
        expected_behavior="Return the list length.",
        function_signature="def solve(values):",
        time_complexity="O(n)",
        generation_model="mock-generator",
        golden_solution="SECRET_GOLDEN_SOLUTION",
        tests=[
            TestCase(
                test_id="PUBLIC_1",
                input={"values": [1]},
                expected_output=1,
                visibility="public",
            ),
            TestCase(
                test_id="PUBLIC_2",
                input={"values": [1, 2]},
                expected_output=2,
                visibility="public",
            ),
            TestCase(
                test_id="HIDDEN_1",
                input={"values": [1, 2, 3], "marker": "SECRET_INPUT"},
                expected_output="SECRET_EXPECTED",
                visibility="hidden",
            ),
            TestCase(
                test_id="HIDDEN_2",
                input={"values": []},
                expected_output=0,
                visibility="hidden",
            ),
            TestCase(
                test_id="HIDDEN_3",
                input={"values": [4]},
                expected_output=1,
                visibility="hidden",
            ),
        ],
    )


def test_target_prompt_excludes_private_data_and_runs_hidden_tests(monkeypatch):
    prompts = []

    class FakeProvider:
        def __init__(self, _model): pass
        async def available(self): return True
        async def generate_text(self, prompt, system=""):
            prompts.append((prompt, system))
            return "```python\ndef solve(values, **kwargs):\n    return len(values)\n```"

    monkeypatch.setattr(evaluator, "OllamaProvider", FakeProvider)
    result = asyncio.run(evaluator.evaluate_task(make_eval_task(), "mock-target"))

    prompt = " ".join(prompts[0])
    for secret in ("SECRET_GOLDEN_SOLUTION", "SECRET_INPUT", "SECRET_EXPECTED", "HIDDEN_1"):
        assert secret not in prompt
    assert result["task_passed"] is False
    assert result["test_summary"] == {
        "public": {"total": 2, "passed": 2},
        "hidden": {"total": 3, "passed": 2},
    }
    assert result["failure_reports"][0]["failure_type"] == "incorrect_algorithm"
    assert result["failure_reports"][0]["evidence"]["expected_output"] == "SECRET_EXPECTED"


def test_target_syntax_error_is_classified(monkeypatch):
    class FakeProvider:
        def __init__(self, _model): pass
        async def available(self): return True
        async def generate_text(self, _prompt, system=""):
            return "```python\ndef solve(:\n    pass\n```"

    monkeypatch.setattr(evaluator, "OllamaProvider", FakeProvider)
    result = asyncio.run(evaluator.evaluate_task(make_eval_task(), "mock-target"))
    assert result["status"] == "syntax_error"
    assert result["failure_reports"][0]["failure_type"] == "syntax_error"
