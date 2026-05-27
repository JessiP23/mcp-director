"""Telegram plugin for MCP tools with proper error handling and rate limiting."""

from typing import Any, Dict, Optional
import os
from fastmcp import FastMCP
import httpx
from fastmcp.server.dependencies import get_http_request

from ..base import BasePlugin
from src.config import get_settings


class TelegramPlugin(BasePlugin):
    """Telegram Bot API plugin for sending messages and managing chats."""

    name = "telegram"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.category = "communication"
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        # Plugin is enabled by default, but individual users need tokens
        self.enabled = True
        self.settings = get_settings()

    async def get_user_token_from_supabase(self, user_id: str) -> Optional[str]:
        """Fetch user's Telegram bot token from Supabase."""
        try:
            request = get_http_request()
            user_token = getattr(request.state, "director_bearer_token", None)
            if not user_token:
                return None
            async with httpx.AsyncClient() as client:
                headers = {
                    "apikey": self.settings.supabase_anon_key,
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json",
                }
                response = await client.get(
                    f"{self.settings.supabase_url}/rest/v1/director_connector_oauth_tokens",
                    headers=headers,
                    params={
                        "user_id": f"eq.{user_id}",
                        "service": f"eq.telegram",
                        "select": "access_token",
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    if data and len(data) > 0:
                        return data[0].get("access_token")
                else:
                    print(f"Supabase query failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Error fetching telegram token from Supabase: {e}")
        return None

    def _resolve_token(self) -> Optional[str]:
        """Helper not used directly; tools resolve token via Supabase + env fallback."""
        return self.bot_token

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
            request = get_http_request()
            user_id = getattr(request.state, "user_id", None) if request else None
            token = await self.get_user_token_from_supabase(user_id) if user_id else None
            if not token:
                token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "Telegram not configured. Please connect your Telegram account.",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                
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

        @mcp.tool(name="telegram_send_photo")
        @self.with_circuit_breaker
        async def telegram_send_photo(
            chat_id: str,
            photo_url: str,
            caption: Optional[str] = None,
            parse_mode: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Send a generated photo/asset URL to a Telegram chat.
            
            Use this to share a generated image from WM Studio. The asset stays hosted
            in WM Studio storage; Telegram fetches and renders the URL inline.
            
            Args:
                chat_id: Target chat id or @channel_username
                photo_url: Public HTTPS URL of the generated image
                caption: Optional caption (0-1024 chars)
                parse_mode: Optional parse mode (HTML, Markdown, MarkdownV2)
            
            Returns:
                Dict with message_id, chat_id, and success status
            """
            request = get_http_request()
            user_id = getattr(request.state, "user_id", None) if request else None
            token = await self.get_user_token_from_supabase(user_id) if user_id else None
            if not token:
                token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "Telegram not configured. Please connect your Telegram account.",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{token}/sendPhoto"
                payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo_url}
                if caption:
                    payload["caption"] = caption
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
                    "photo_url": photo_url,
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
            request = get_http_request()
            user_id = getattr(request.state, "user_id", None) if request else None
            token = await self.get_user_token_from_supabase(user_id) if user_id else None
            if not token:
                token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "Telegram not configured. Please connect your Telegram account.",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{token}/getMe"
                
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
            request = get_http_request()
            user_id = getattr(request.state, "user_id", None) if request else None
            token = await self.get_user_token_from_supabase(user_id) if user_id else None
            if not token:
                token = self.bot_token
            
            if not token:
                return {
                    "ok": False,
                    "error": "telegram_not_configured",
                    "message": "Telegram not configured. Please connect your Telegram account.",
                }

            try:
                client = await self.get_http_client()
                url = f"https://api.telegram.org/bot{token}/getUpdates"
                
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
