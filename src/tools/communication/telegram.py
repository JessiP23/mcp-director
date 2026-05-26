"""Telegram plugin for MCP tools with proper error handling and rate limiting."""

from typing import Any, Dict, Optional
import os
from fastmcp import FastMCP

from ..base import BasePlugin


class TelegramPlugin(BasePlugin):
    """Telegram Bot API plugin for sending messages and managing chats."""

    name = "telegram"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.category = "communication"
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            self.enabled = False

    async def register_tools(self, mcp: FastMCP) -> None:
        """Register Telegram tools with the MCP server."""
        
        @mcp.tool(name="telegram_send_message")
        @self.with_circuit_breaker
        async def telegram_send_message(
            chat_id: str,
            message: str,
            parse_mode: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Send a message via Telegram Bot API.
            
            Args:
                chat_id: Unique identifier for the target chat or username of the target channel
                message: Text of the message to be sent
                parse_mode: Optional parse mode (HTML, Markdown, MarkdownV2)
            
            Returns:
                Dict with message_id, chat_id, and success status
            """
            if not self.bot_token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "TELEGRAM_BOT_TOKEN environment variable is not set",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                }
                
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "telegram_api_error",
                        "description": data.get("description", "Unknown error"),
                    }
                
                result = data.get("result", {})
                return {
                    "ok": True,
                    "message_id": result.get("message_id"),
                    "chat_id": result.get("chat", {}).get("id"),
                    "date": result.get("date"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "telegram_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="telegram_get_me")
        @self.with_circuit_breaker
        async def telegram_get_me() -> Dict[str, Any]:
            """Get basic information about the bot.
            
            Returns:
                Dict with bot id, username, first_name, etc.
            """
            if not self.bot_token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "TELEGRAM_BOT_TOKEN environment variable is not set",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
                
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "telegram_api_error",
                        "description": data.get("description", "Unknown error"),
                    }
                
                result = data.get("result", {})
                return {
                    "ok": True,
                    "id": result.get("id"),
                    "is_bot": result.get("is_bot"),
                    "first_name": result.get("first_name"),
                    "username": result.get("username"),
                    "language_code": result.get("language_code"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "telegram_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="telegram_get_updates")
        @self.with_circuit_breaker
        async def telegram_get_updates(
            offset: Optional[int] = None,
            limit: int = 100,
            timeout: int = 0,
        ) -> Dict[str, Any]:
            """Get incoming updates using long polling.
            
            Args:
                offset: Identifier of the first update to be returned
                limit: Limits the number of updates to be retrieved (1-100)
                timeout: Timeout in seconds for long polling
            
            Returns:
                Dict with list of updates
            """
            if not self.bot_token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "TELEGRAM_BOT_TOKEN environment variable is not set",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                
                params = {
                    "limit": min(max(1, limit), 100),
                    "timeout": timeout,
                }
                
                if offset is not None:
                    params["offset"] = offset
                
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "telegram_api_error",
                        "description": data.get("description", "Unknown error"),
                    }
                
                return {
                    "ok": True,
                    "result": data.get("result", []),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "telegram_request_failed",
                    "message": str(e),
                }
