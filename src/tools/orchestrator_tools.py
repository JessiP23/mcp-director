"""Orchestrator control tools for Director."""

from __future__ import annotations

import structlog
from fastmcp import FastMCP
from src.orchestrator import get_orchestrator, AgentMode

log = structlog.get_logger(__name__)


def register(mcp: FastMCP) -> None:
    """Register orchestrator control tools."""

    @mcp.tool(name="director_set_mode")
    async def set_orchestrator_mode(mode: str = "ask") -> dict:
        """Set the orchestrator execution mode.

        Args:
            mode: Either "auto" (continue automatically) or "ask" (wait for confirmation)

        Returns:
            Confirmation of mode change
        """
        orchestrator = get_orchestrator()

        if mode.lower() == "auto":
            orchestrator.set_mode(AgentMode.AUTO)
            log.info("orchestrator_mode_set_to_auto")
            return {
                "ok": True,
                "mode": "auto",
                "message": "Orchestrator set to AUTO mode - will continue automatically after each action"
            }
        elif mode.lower() == "ask":
            orchestrator.set_mode(AgentMode.ASK)
            log.info("orchestrator_mode_set_to_ask")
            return {
                "ok": True,
                "mode": "ask",
                "message": "Orchestrator set to ASK mode - will wait for confirmation before continuing"
            }
        else:
            return {
                "ok": False,
                "error": f"Invalid mode: {mode}. Use 'auto' or 'ask'"
            }

    @mcp.tool(name="director_get_status")
    async def get_orchestrator_status() -> dict:
        """Get the current orchestrator status and state.

        Returns:
            Current mode, stage, registered agents, and state summary
        """
        orchestrator = get_orchestrator()
        summary = orchestrator.get_summary()

        log.info("orchestrator_status_requested", summary=summary)

        return {
            "ok": True,
            "status": summary
        }

    @mcp.tool(name="director_reset")
    async def reset_orchestrator(mode: str = "ask") -> dict:
        """Reset the orchestrator state (clears all state and pending actions).

        Use this to start fresh with a new project.

        Args:
            mode: Either "auto" or "ask" (default: "ask")

        Returns:
            Confirmation of reset
        """
        from src.orchestrator import reset_orchestrator as reset

        if mode.lower() == "auto":
            new_orchestrator = reset(AgentMode.AUTO)
        elif mode.lower() == "ask":
            new_orchestrator = reset(AgentMode.ASK)
        else:
            return {
                "ok": False,
                "error": f"Invalid mode: {mode}. Use 'auto' or 'ask'"
            }

        # Re-register agents
        from src.agents import CastingAgent, StoryboardAgent, VideoAgent, ReferenceManager

        new_orchestrator.register_agent("casting", CastingAgent())
        new_orchestrator.register_agent("storyboard", StoryboardAgent())
        new_orchestrator.register_agent("video", VideoAgent())
        new_orchestrator.register_agent("reference_manager", ReferenceManager())

        # Set orchestrator reference for each agent
        for agent in new_orchestrator.agents.values():
            agent.set_orchestrator(new_orchestrator)

        log.info("orchestrator_reset", mode=mode)

        return {
            "ok": True,
            "mode": mode,
            "message": f"Orchestrator reset to {mode.upper()} mode with fresh state"
        }

    @mcp.tool(name="director_store_character")
    async def store_character(
        name: str,
        image_url: str,
        profile: dict | None = None
    ) -> dict:
        """Store a character reference in the orchestrator state.

        This is called automatically after studio_casting, but can also be called manually.

        Args:
            name: Character name
            image_url: URL to the character image
            profile: Optional character profile dict

        Returns:
            Confirmation of storage
        """
        orchestrator = get_orchestrator()
        reference_manager = orchestrator.get_agent("reference_manager")

        if not reference_manager:
            return {
                "ok": False,
                "error": "Reference manager not found"
            }

        result = await reference_manager.handle({
            "action": "store_character",
            "name": name,
            "image_url": image_url,
            "profile": profile or {}
        })

        log.info("director_store_character", name=name, result=result)

        return result

    @mcp.tool(name="director_list_characters")
    async def list_characters() -> dict:
        """List all stored character references.

        Returns:
            List of all characters with their image URLs
        """
        orchestrator = get_orchestrator()
        reference_manager = orchestrator.get_agent("reference_manager")

        if not reference_manager:
            return {
                "ok": False,
                "error": "Reference manager not found"
            }

        result = await reference_manager.handle({
            "action": "list_characters"
        })

        log.info("director_list_characters", result=result)

        return result
