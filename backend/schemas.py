
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Difficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


# ==================================================
# INTERNAL TEST CASE
# ==================================================

class TestCase(BaseModel):
    __test__ = False

    test_id: str
    input: dict[str, Any]
    expected_output: Any
    category: str = "normal"
    description: str = ""
    mandatory: bool = True
    visibility: str = "hidden"


# ==================================================
# INTERNAL TASK
# Contains complete benchmark information.
# Never return this directly from public task endpoints.
# ==================================================

class Task(BaseModel):
    task_id: str = Field(
        default_factory=lambda: f"TASK_{uuid4().hex[:12].upper()}"
    )

    task_version: int = 1
    category: str = "python_coding"

    difficulty: Difficulty

    title: str
    problem_statement: str

    input_specification: str
    output_specification: str

    constraints: list[str] = Field(default_factory=list)

    expected_behavior: str
    function_signature: str

    edge_case_requirements: list[str] = Field(default_factory=list)

    time_complexity: str

    metadata: dict[str, Any] = Field(default_factory=dict)

    generation_seed: int | None = None
    generation_model: str

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    golden_solution: str

    tests: list[TestCase] = Field(min_length=5)

    validation_status: str = "pending"
    quality_score: int = 0


# ==================================================
# PUBLIC TEST CASE
# Contains only information safe to expose.
# ==================================================

class PublicTestCase(BaseModel):
    test_id: str

    input: dict[str, Any]

    category: str = "normal"

    description: str = ""


# ==================================================
# PUBLIC TASK RESPONSE
# Excludes golden solutions, hidden tests,
# expected outputs, and internal metadata.
# ==================================================

class PublicTask(BaseModel):
    task_id: str

    task_version: int

    category: str

    difficulty: Difficulty

    title: str

    problem_statement: str

    input_specification: str

    output_specification: str

    constraints: list[str] = Field(default_factory=list)

    function_signature: str

    generated_at: datetime

    tests: list[PublicTestCase] = Field(
        default_factory=list
    )

    validation_status: str

    quality_score: int


# ==================================================
# GENERATION REQUEST
# ==================================================

class GenerateRequest(BaseModel):
    difficulty: Difficulty = Difficulty.medium

    count: int = Field(
        default=1,
        ge=1,
        le=10
    )

    topic: str = "lists and edge cases"


# ==================================================
# EVALUATION REQUEST
# ==================================================

class EvaluateRequest(BaseModel):
    model: str | None = None


# ==================================================
# ADAPTIVE GENERATION REQUEST
# ==================================================

class AdaptiveGenerateRequest(BaseModel):
    model: str | None = None

    difficulty: Difficulty = Difficulty.medium

    count: int = Field(
        default=1,
        ge=1,
        le=5
    )

    min_task_occurrences: int = Field(
        default=2,
        ge=2,
        le=20
    )
