"""Aggregate failure evidence by category across distinct tasks."""
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def analyze_weaknesses(
    evaluations: list[dict[str, Any]],
    min_task_occurrences: int = 2,
) -> list[dict[str, Any]]:
    groups = defaultdict(lambda: {
        "task_ids": set(), "evaluation_ids": set(), "failure_count": 0,
        "examples": [], "failure_types": set(), "labels": set(),
        "confidences": set(),
    })

    for evaluation in evaluations:
        task_id = evaluation.get("task_id")
        if not task_id:
            continue
        evaluation_id = evaluation.get("evaluation_id")
        for failure in evaluation.get("failure_reports", []) or []:
            weakness = str(
                failure.get("underlying_weakness")
                or failure.get("failure_type")
                or "unknown"
            ).strip().lower()
            if not weakness or weakness == "unknown":
                continue
            group = groups[weakness]
            group["task_ids"].add(task_id)
            if evaluation_id:
                group["evaluation_ids"].add(evaluation_id)
            group["failure_count"] += 1
            if failure.get("failure_type"):
                group["failure_types"].add(failure["failure_type"])
            if failure.get("weakness_label"):
                group["labels"].add(failure["weakness_label"])
            if failure.get("semantic_confidence"):
                group["confidences"].add(failure["semantic_confidence"])
            if len(group["examples"]) < 10:
                group["examples"].append({
                    "task_id": task_id,
                    "evaluation_id": evaluation_id,
                    "failure_type": failure.get("failure_type"),
                    "description": failure.get("description"),
                    "failed_tests": failure.get("failed_tests", []),
                    "severity": failure.get("severity"),
                    "evidence": failure.get("evidence", {}),
                    "recommendation": failure.get("recommendation"),
                })

    result = []
    for weakness, group in groups.items():
        task_ids = sorted(group["task_ids"])
        if len(task_ids) < min_task_occurrences:
            continue
        labels = sorted(group["labels"])
        confidences = sorted(group["confidences"])
        result.append({
            "weakness": weakness,
            "weakness_label": labels[0] if labels else weakness,
            "semantic_confidence": confidences[0] if confidences else "unknown",
            "distinct_task_count": len(task_ids),
            "failure_count": group["failure_count"],
            "task_ids": task_ids,
            "evaluation_ids": sorted(group["evaluation_ids"]),
            "failure_types": sorted(group["failure_types"]),
            "examples": group["examples"],
            "confidence": "strong" if len(task_ids) >= 4 else "moderate",
        })
    result.sort(
        key=lambda item: (item["distinct_task_count"], item["failure_count"]),
        reverse=True,
    )
    logger.info("Weakness analysis completed | Evaluations: %s | Weaknesses: %s", len(evaluations), len(result))
    return result
