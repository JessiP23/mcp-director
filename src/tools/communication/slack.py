"""Slack plugin for MCP tools with proper error handling and rate limiting."""

from typing import Any, Dict, Optional
import os
from fastmcp import FastMCP
import httpx
from fastmcp.server.dependencies import get_http_request

from ..base import BasePlugin
from src.config import get_settings


class SlackPlugin(BasePlugin):
    """Slack Web API plugin for sending messages and managing channels."""

    name = "slack"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.category = "communication"
        self.bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.enabled = True
        self.settings = get_settings()
    
    async def get_user_token_from_supabase(self, user_id: str) -> Optional[str]:
        """Fetch user's Slack OAuth token from Supabase."""
        try:
            request = get_http_request()
            # Use the user's Supabase access token from request state (set by auth_guard)
            user_token = getattr(request.state, "director_bearer_token", None)
            
            if not user_token:
                print("No user Supabase token available in request state")
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
                        "service": f"eq.slack",
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
            print(f"Error fetching token from Supabase: {e}")
        return None

    async def _get_active_token(self) -> Optional[str]:
        request = get_http_request()
        user_id = getattr(request.state, "user_id", None) if request else None
        token = await self.get_user_token_from_supabase(user_id) if user_id else None
        return token or self.bot_token

    async def _resolve_channel_id(self, client, headers, channel: str) -> str:
        if not channel.startswith("#"):
            return channel
        list_response = await client.get(
            "https://slack.com/api/conversations.list",
            params={"types": "public_channel,private_channel", "limit": 1000},
            headers=headers,
        )
        list_response.raise_for_status()
        list_data = list_response.json()
        if not list_data.get("ok"):
            return channel
        target = channel[1:]
        for item in list_data.get("channels", []):
            if item.get("name") == target:
                return item.get("id", channel)
        return channel

    async def _post_with_join_retry(self, client, headers, target_channel: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = "https://slack.com/api/chat.postMessage"
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get("error") == "not_in_channel":
            join_response = await client.post(
                "https://slack.com/api/conversations.join",
                json={"channel": target_channel},
                headers=headers,
            )
            join_response.raise_for_status()
            join_data = join_response.json()
            if join_data.get("ok") or join_data.get("error") == "already_in_channel":
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        return data

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
            # Get user_id from request state (set by auth_guard middleware)
            request = get_http_request()
            user_id = getattr(request.state, "user_id", None) if request else None
            
            # Try to get user token from Supabase first
            token = await self.get_user_token_from_supabase(user_id) if user_id else None
            
            # Fall back to bot token if user token not found
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
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                target_channel = await self._resolve_channel_id(client, headers, channel)
                payload = {"channel": target_channel, "text": message}
                data = await self._post_with_join_retry(client, headers, target_channel, payload)
                if not data.get("ok"):
                    return {
                        "ok": False,
                        "error": "slack_api_error",
                        "description": data.get("error", "Unknown error"),
                    }
                return {"ok": True, "ts": data.get("ts"), "channel": data.get("channel")}
            except Exception as e:
                return {"ok": False, "error": "slack_request_failed", "message": str(e)}

        @mcp.tool(name="slack_post_asset")
        @self.with_circuit_breaker
        async def slack_post_asset(
            channel: str,
            asset_url: str,
            caption: Optional[str] = None,
            alt_text: Optional[str] = None,
            asset_type: str = "image",
        ) -> Dict[str, Any]:
            """Post a generated asset (image or video URL) to a Slack channel using Block Kit.
            
            Use this whenever you need to share a generated asset (image, upscale, brandshot, video) in Slack.
            The asset stays hosted in WM Studio storage; Slack just renders the URL inline.
            
            Args:
                channel: Channel ID or name (e.g., "C1234567890" or "#general")
                asset_url: Public HTTPS URL of the generated asset
                caption: Optional caption shown above the asset
                alt_text: Optional accessibility text (defaults to caption or "Generated asset")
                asset_type: "image" for still images, "video" for video links
            
            Returns:
                Dict with message timestamp, channel, and success status
            """
            token = await self._get_active_token()
            if not token:
                return {
                    "ok": False,
                    "error": "slack_not_configured",
                    "message": "Slack not configured. Please connect your Slack account.",
                }

            try:
                client = await self.get_http_client()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                target_channel = await self._resolve_channel_id(client, headers, channel)

                fallback_text = caption or asset_url
                blocks: list = []
                if caption:
                    blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": caption},
                    })
                if asset_type == "image":
                    blocks.append({
                        "type": "image",
                        "image_url": asset_url,
                        "alt_text": alt_text or caption or "Generated asset",
                    })
                else:
                    blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"<{asset_url}|Open video>"},
                    })
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Generated by WM Studio · <{asset_url}|source>"},
                    ],
                })

                payload = {
                    "channel": target_channel,
                    "text": fallback_text,
                    "blocks": blocks,
                    "unfurl_links": True,
                    "unfurl_media": True,
                }
                data = await self._post_with_join_retry(client, headers, target_channel, payload)
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
                    "asset_url": asset_url,
                }
            except Exception as e:
                return {"ok": False, "error": "slack_request_failed", "message": str(e)}

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
