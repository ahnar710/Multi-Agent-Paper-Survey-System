"""Explicit legal state transitions for research runs."""

from __future__ import annotations

from paper_agents.schemas import RunStatus


class InvalidStateTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.SEARCHING, RunStatus.FAILED},
    RunStatus.SEARCHING: {RunStatus.SCREENING, RunStatus.FAILED},
    RunStatus.SCREENING: {RunStatus.READING, RunStatus.FAILED},
    RunStatus.READING: {RunStatus.VERIFYING, RunStatus.FAILED},
    RunStatus.VERIFYING: {
        RunStatus.READING,
        RunStatus.SYNTHESIZING,
        RunStatus.FAILED,
    },
    RunStatus.SYNTHESIZING: {RunStatus.COMPLETED, RunStatus.FAILED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
}


def ensure_transition(current: RunStatus, target: RunStatus) -> None:
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(
            f"非法任务状态跳转: {current.value} -> {target.value}"
        )
