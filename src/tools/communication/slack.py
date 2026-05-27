"""Slack plugin for MCP tools with proper error handling and rate limiting."""

from typing import Any, Dict, Optional
import os
from fastmcp import FastMCP

from ..base import BasePlugin


class SlackPlugin(BasePlugin):
    """Slack Web API plugin for sending messages and managing channels."""

    name = "slack"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.category = "communication"
        self.bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.enabled = True

    async def register_tools(self, mcp: FastMCP) -> None:
        """Register Slack tools with the MCP server."""
        
        @mcp.tool(name="slack_send_message")
        @self.with_circuit_breaker
        async def slack_send_message(
            channel: str,
            message: str,
        ) -> Dict[str, Any]:
            """Send a message via Slack Web API.
            
            Args:
                channel: Channel ID or name (e.g., "C1234567890" or "#general")
                message: Text of the message to be sent
            
            Returns:
                Dict with message timestamp, channel, and success status
            """
            # Use bot token
            token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "slack_not_configured",
                    "message": "Slack not configured. Please connect your Slack account.",
                }

            try:
                client = await self.get_http_client()
                url = "https://slack.com/api/chat.postMessage"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                
                payload = {
                    "channel": channel,
                    "text": message,
                }
                
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "slack_api_error",
                        "description": data.get("error", "Unknown error"),
                    }
                
                return {
                    "ok": True,
                    "ts": data.get("ts"),
                    "channel": data.get("channel"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "slack_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="slack_get_channels")
        @self.with_circuit_breaker
        async def slack_get_channels(
            limit: int = 100,
            user_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Get list of channels the bot has access to.
            
            Args:
                limit: Maximum number of channels to return
                user_id: User ID for fetching user-specific OAuth token
            
            Returns:
                Dict with list of channels
            """
            token = None
            if user_id:
                token = self.get_user_token(user_id)
            if not token:
                token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "slack_not_configured",
                    "message": "Slack not configured. Please connect your Slack account.",
                }

            try:
                client = await self.get_http_client()
                url = "https://slack.com/api/conversations.list"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                
                params = {
                    "limit": limit,
                    "types": "public_channel,private_channel,mpim,im",
                }
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "slack_api_error",
                        "description": data.get("error", "Unknown error"),
                    }
                
                return {
                    "ok": True,
                    "channels": data.get("channels", []),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "slack_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="slack_get_user_info")
        @self.with_circuit_breaker
        async def slack_get_user_info(
            user: str,
            user_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Get information about a user.
            
            Args:
                user: User ID
                user_id: User ID for fetching user-specific OAuth token
            
            Returns:
                Dict with user information
            """
            token = None
            if user_id:
                token = self.get_user_token(user_id)
            if not token:
                token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "slack_not_configured",
                    "message": "Slack not configured. Please connect your Slack account.",
                }

            try:
                client = await self.get_http_client()
                url = "https://slack.com/api/users.info"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                
                params = {"user": user}
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "slack_api_error",
                        "description": data.get("error", "Unknown error"),
                    }
                
                user_data = data.get("user", {})
                return {
                    "ok": True,
                    "id": user_data.get("id"),
                    "name": user_data.get("name"),
                    "real_name": user_data.get("real_name"),
                    "email": user_data.get("profile", {}).get("email"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "slack_request_failed",
                    "message": str(e),
                }
