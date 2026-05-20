"""Local orchestration for deterministic agent-system research cycles."""

__all__ = ["run_stub_research_cycle"]


def __getattr__(name: str):
    if name == "run_stub_research_cycle":
        from agent_system.orchestration.run_research_cycle import run_stub_research_cycle

        return run_stub_research_cycle
    raise AttributeError(name)
