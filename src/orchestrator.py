"""Simple orchestrator for Director workflow management.

This orchestrator manages specialized agents and workflow state without
over-engineering. It provides auto-continuation and agent coordination.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Callable, Optional
import structlog

log = structlog.get_logger(__name__)


class AgentMode(str, Enum):
    """Agent execution mode."""
    AUTO = "auto"  # Continue automatically without asking
    ASK = "ask"    # Ask user before continuing


class WorkflowStage(str, Enum):
    """Workflow stages."""
    INITIALIZING = "initializing"
    CASTING = "casting"
    STORYBOARD = "storyboard"
    VIDEO = "video"
    COMPLETE = "complete"


class Orchestrator:
    """Simple orchestrator for managing Director workflow.

    This is intentionally simple - no complex state machines or DSLs.
    Just coordination between agents with auto-continuation support.
    """

    def __init__(self, mode: AgentMode = AgentMode.ASK):
        self.mode = mode
        self.current_stage = WorkflowStage.INITIALIZING
        self.agents: dict[str, Any] = {}
        self.state: dict[str, Any] = {}
        self._pending_actions: list[Callable] = []

    def register_agent(self, name: str, agent: Any) -> None:
        """Register an agent with the orchestrator."""
        self.agents[name] = agent
        log.info("orchestrator_agent_registered", name=name)

    def get_agent(self, name: str) -> Optional[Any]:
        """Get a registered agent."""
        return self.agents.get(name)

    def set_mode(self, mode: AgentMode) -> None:
        """Set the execution mode."""
        self.mode = mode
        log.info("orchestrator_mode_set", mode=mode.value)

    def set_stage(self, stage: WorkflowStage) -> None:
        """Set the current workflow stage."""
        self.current_stage = stage
        log.info("orchestrator_stage_set", stage=stage.value)

    def update_state(self, key: str, value: Any) -> None:
        """Update workflow state."""
        self.state[key] = value
        log.debug("orchestrator_state_updated", key=key)

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get workflow state value."""
        return self.state.get(key, default)

    def schedule_action(self, action: Callable) -> None:
        """Schedule an action for auto-continuation."""
        self._pending_actions.append(action)
        log.debug("orchestrator_action_scheduled", pending_count=len(self._pending_actions))

    async def execute_pending_actions(self) -> list[Any]:
        """Execute all pending actions in order."""
        results = []
        for action in self._pending_actions:
            try:
                result = await action()
                results.append(result)
            except Exception as e:
                log.error("orchestrator_action_failed", error=str(e))
                results.append({"error": str(e)})
        self._pending_actions.clear()
        return results

    def should_continue(self) -> bool:
        """Check if we should continue automatically based on mode."""
        return self.mode == AgentMode.AUTO

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of orchestrator state."""
        return {
            "mode": self.mode.value,
            "current_stage": self.current_stage.value,
            "state_keys": list(self.state.keys()),
            "registered_agents": list(self.agents.keys()),
            "pending_actions": len(self._pending_actions),
        }


# Global orchestrator instance (simplified - could be per-run in future)
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def reset_orchestrator(mode: AgentMode = AgentMode.ASK) -> Orchestrator:
    """Reset the global orchestrator with a new mode."""
    global _orchestrator
    _orchestrator = Orchestrator(mode=mode)
    log.info("orchestrator_reset", mode=mode.value)
    return _orchestrator
