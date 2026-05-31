"""Background runner for frontend-submitted research cycles."""
from __future__ import annotations

import traceback
from concurrent.futures import ProcessPoolExecutor
from uuid import uuid4


_executor = ProcessPoolExecutor(max_workers=1)


def submit_cycle(user_inputs: list[str]) -> str:
    """
    Kick off a cycle in the background and return its id immediately.
    """
    cycle_id = str(uuid4())
    _executor.submit(_run_cycle_in_process, cycle_id, list(user_inputs))
    return cycle_id


def _run_cycle_in_process(cycle_id: str, user_inputs: list[str]) -> None:
    """
    Worker-process entry point. All durable progress is written to disk.
    """
    from src.agent_system.orchestration.cycle_status import CycleStatusEmitter
    from src.agent_system.orchestration.run_research_cycle import run_cycle_with_inputs

    emitter = CycleStatusEmitter(cycle_id, user_inputs=user_inputs)
    try:
        run_cycle_with_inputs(
            user_inputs=user_inputs,
            cycle_id=cycle_id,
            emitter=emitter,
        )
    except Exception:
        emitter.fail_cycle(traceback.format_exc())
