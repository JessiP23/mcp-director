"""Specialized agents for Director workflow.

Each agent has a focused responsibility and system prompt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional
import structlog

log = structlog.get_logger(__name__)


class BaseAgent(ABC):
    """Base class for specialized agents."""

    def __init__(self, name: str):
        self.name = name
        self._orchestrator: Optional[Any] = None

    def set_orchestrator(self, orchestrator: Any) -> None:
        """Set the orchestrator for this agent."""
        self._orchestrator = orchestrator

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        pass

    @abstractmethod
    async def handle(self, context: dict[str, Any]) -> dict[str, Any]:
        """Handle a request with the given context."""
        pass


class CastingAgent(BaseAgent):
    """Agent specialized in character casting and actor development."""

    def __init__(self):
        super().__init__("casting")

    def get_system_prompt(self) -> str:
        return """You are the Casting Agent. Your job is to develop character sheets for video production.

REQUIREMENTS FOR CHARACTER SHEETS:
- Must generate a 3x1 grid with 3 panels: macro (close-up), side profile, and full body
- Fixed aspect ratio: 16:9 for the overall sheet
- Each panel should show the character from a different angle
- Use specific character details from the character_profile parameter

WORKFLOW:
1. When asked to develop a character, call studio_casting with the character details
2. The character sheet will be generated with the 3 required panels
3. Save the character to memory for later use in scenes

CHARACTER MEMORY:
- When you develop a character, remember their name and image reference
- When scenes are generated later, you will be asked to include specific characters
- Reference the character image in scene prompts to maintain consistency

Use studio_casting tool for character generation. Always confirm cost before generating."""

    async def handle(self, context: dict[str, Any]) -> dict[str, Any]:
        """Handle casting requests."""
        character_name = context.get("character_name")
        prompt = context.get("prompt")
        character_profile = context.get("character_profile")

        if not character_name or not prompt:
            return {"error": "character_name and prompt are required"}

        log.info("casting_agent_handling", character_name=character_name)

        # This will be called by the tool wrapper, not directly
        # Return context for the tool to use
        return {
            "action": "studio_casting",
            "params": {
                "character_name": character_name,
                "prompt": prompt,
                "character_profile": character_profile,
                "aspect_ratio": "16:9",  # Fixed 16:9 for character sheets
            }
        }


class StoryboardAgent(BaseAgent):
    """Agent specialized in storyboard frame generation."""

    def __init__(self):
        super().__init__("storyboard")

    def get_system_prompt(self) -> str:
        return """You are the Storyboard Agent. Your job is to generate frame candidates for video scenes.

WORKFLOW:
1. When asked to generate scenes, call studio_storyboard_frames
2. Generate 2-4 frame options for each scene
3. Present all options to the user
4. Wait for user to choose which frame to animate

CHARACTER INTEGRATION:
- When a scene includes previously developed characters, include their references
- Specify in the prompt: "Character X should look like [image reference]"
- Use the character_assets stored in memory to maintain consistency

ASPECT RATIO:
- Always ask the user for aspect ratio before generating
- Common options: 16:9 (cinematic), 9:16 (vertical), 1:1 (square), 21:9 (ultrawide)

Use studio_storyboard_frames tool. Always confirm cost before generating."""

    async def handle(self, context: dict[str, Any]) -> dict[str, Any]:
        """Handle storyboard requests."""
        prompt = context.get("prompt")
        aspect_ratio = context.get("aspect_ratio")
        characters = context.get("characters", [])

        if not prompt:
            return {"error": "prompt is required"}

        log.info("storyboard_agent_handling", has_characters=bool(characters))

        # Build prompt with character references if provided
        enhanced_prompt = prompt
        if characters:
            char_refs = "\n\n".join([f"- {c['name']}: [character reference {c['image_url']}]" for c in characters])
            enhanced_prompt = f"{prompt}\n\nCharacters in this scene:\n{char_refs}"

        return {
            "action": "studio_storyboard_frames",
            "params": {
                "prompt": enhanced_prompt,
                "aspect_ratio": aspect_ratio,
                "n": 3,
            }
        }


class VideoAgent(BaseAgent):
    """Agent specialized in video generation."""

    def __init__(self):
        super().__init__("video")

    def get_system_prompt(self) -> str:
        return """You are the Video Agent. Your job is to generate videos from storyboard frames.

WORKFLOW:
1. After storyboard frames are generated and a frame is selected, call studio_generate_video
2. Use the selected frame URL as the image_url parameter
3. Generate the video with the specified duration and resolution
4. Present the result to the user

REQUIREMENTS:
- NEVER call studio_generate_video without an image_url from storyboard
- Always confirm cost before generating
- Use appropriate duration based on scene complexity (2-5s for simple, 5-10s for complex)

Use studio_generate_video tool. Always confirm cost before generating."""

    async def handle(self, context: dict[str, Any]) -> dict[str, Any]:
        """Handle video generation requests."""
        prompt = context.get("prompt")
        image_url = context.get("image_url")
        duration = context.get("duration", 5)

        if not prompt or not image_url:
            return {"error": "prompt and image_url are required"}

        log.info("video_agent_handling", duration=duration)

        return {
            "action": "studio_generate_video",
            "params": {
                "prompt": prompt,
                "image_url": image_url,
                "duration": duration,
            }
        }


class ReferenceManager(BaseAgent):
    """Agent for managing character and location references."""

    def __init__(self):
        super().__init__("reference_manager")

    def get_system_prompt(self) -> str:
        return """You are the Reference Manager. Your job is to track and manage character and location references.

RESPONSIBILITIES:
- Store character references when they are generated
- Retrieve character references when needed for scenes
- Maintain consistency across the production

MEMORY:
- Characters are stored with their names and image URLs
- Locations are stored with their names and image URLs
- Props are stored with their names and image URLs

When other agents need references, provide them from memory."""

    async def handle(self, context: dict[str, Any]) -> dict[str, Any]:
        """Handle reference management requests."""
        action = context.get("action")

        if action == "store_character":
            return self._store_character(context)
        elif action == "get_character":
            return self._get_character(context)
        elif action == "list_characters":
            return self._list_characters()

        return {"error": f"Unknown action: {action}"}

    def _store_character(self, context: dict[str, Any]) -> dict[str, Any]:
        """Store a character reference."""
        name = context.get("name")
        image_url = context.get("image_url")
        profile = context.get("profile", {})

        if not name or not image_url:
            return {"error": "name and image_url are required"}

        # Store in orchestrator state
        if self._orchestrator:
            characters = self._orchestrator.get_state("characters", {})
            characters[name] = {
                "name": name,
                "image_url": image_url,
                "profile": profile,
            }
            self._orchestrator.update_state("characters", characters)
            log.info("reference_manager_stored_character", name=name)

        return {"ok": True, "name": name}

    def _get_character(self, context: dict[str, Any]) -> dict[str, Any]:
        """Get a character reference."""
        name = context.get("name")

        if not name:
            return {"error": "name is required"}

        if self._orchestrator:
            characters = self._orchestrator.get_state("characters", {})
            character = characters.get(name)
            if character:
                return {"ok": True, "character": character}

        return {"error": f"Character not found: {name}"}

    def _list_characters(self) -> dict[str, Any]:
        """List all character references."""
        if self._orchestrator:
            characters = self._orchestrator.get_state("characters", {})
            return {"ok": True, "characters": list(characters.values())}

        return {"ok": True, "characters": []}
