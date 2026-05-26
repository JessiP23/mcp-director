"""Gmail plugin for MCP tools with proper error handling and rate limiting."""

from typing import Any, Dict, Optional
import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastmcp import FastMCP

from ..base import BasePlugin


class GmailPlugin(BasePlugin):
    """Gmail API plugin for sending emails and managing messages."""

    name = "gmail"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.category = "communication"
        self.api_key = os.getenv("GMAIL_API_KEY")
        self.access_token = os.getenv("GMAIL_ACCESS_TOKEN")
        if not self.api_key and not self.access_token:
            self.enabled = False

    async def register_tools(self, mcp: FastMCP) -> None:
        """Register Gmail tools with the MCP server."""
        
        @mcp.tool(name="gmail_send_message")
        @self.with_circuit_breaker
        async def gmail_send_message(
            to: str,
            subject: str,
            body: str,
            cc: Optional[str] = None,
            bcc: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Send an email via Gmail API.
            
            Args:
                to: Recipient email address
                subject: Email subject
                body: Email body (plain text)
                cc: Optional CC recipient
                bcc: Optional BCC recipient
            
            Returns:
                Dict with message ID and success status
            """
            if not self.access_token:
                return {
                    "ok": False,
                    "error": "gmail_not_configured",
                    "message": "GMAIL_ACCESS_TOKEN environment variable is not set",
                }

            try:
                # Create message
                message = MIMEMultipart()
                message["to"] = to
                message["subject"] = subject
                if cc:
                    message["cc"] = cc
                if bcc:
                    message["bcc"] = bcc
                
                message.attach(MIMEText(body, "plain"))
                
                # Encode message
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                
                client = await self.get_http_client()
                url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
                
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                }
                
                payload = {"raw": raw}
                
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                return {
                    "ok": True,
                    "id": data.get("id"),
                    "threadId": data.get("threadId"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "gmail_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="gmail_list_messages")
        @self.with_circuit_breaker
        async def gmail_list_messages(
            max_results: int = 10,
            query: Optional[str] = None,
        ) -> Dict[str, Any]:
            """List Gmail messages.
            
            Args:
                max_results: Maximum number of messages to return
                query: Optional search query (Gmail search syntax)
            
            Returns:
                Dict with list of messages
            """
            if not self.access_token:
                return {
                    "ok": False,
                    "error": "gmail_not_configured",
                    "message": "GMAIL_ACCESS_TOKEN environment variable is not set",
                }

            try:
                client = await self.get_http_client()
                url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
                
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                }
                
                params = {"maxResults": max_results}
                if query:
                    params["q"] = query
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                return {
                    "ok": True,
                    "messages": data.get("messages", []),
                    "nextPageToken": data.get("nextPageToken"),
                    "resultSizeEstimate": data.get("resultSizeEstimate"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "gmail_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="gmail_get_message")
        @self.with_circuit_breaker
        async def gmail_get_message(
            message_id: str,
            format: str = "metadata",
        ) -> Dict[str, Any]:
            """Get a specific Gmail message.
            
            Args:
                message_id: The ID of the message to retrieve
                format: Format of the message (minimal, metadata, full, raw)
            
            Returns:
                Dict with message details
            """
            if not self.access_token:
                return {
                    "ok": False,
                    "error": "gmail_not_configured",
                    "message": "GMAIL_ACCESS_TOKEN environment variable is not set",
                }

            try:
                client = await self.get_http_client()
                url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
                
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                }
                
                params = {"format": format}
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                return {
                    "ok": True,
                    "id": data.get("id"),
                    "threadId": data.get("threadId"),
                    "snippet": data.get("snippet"),
                    "payload": data.get("payload"),
                    "internalDate": data.get("internalDate"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "gmail_request_failed",
                    "message": str(e),
                }

        @mcp.tool(name="gmail_search_messages")
        @self.with_circuit_breaker
        async def gmail_search_messages(
            query: str,
            max_results: int = 10,
        ) -> Dict[str, Any]:
            """Search Gmail messages using Gmail search syntax.
            
            Args:
                query: Gmail search query (e.g., "from:john@example.com", "subject:urgent")
                max_results: Maximum number of messages to return
            
            Returns:
                Dict with list of matching messages
            """
            if not self.access_token:
                return {
                    "ok": False,
                    "error": "gmail_not_configured",
                    "message": "GMAIL_ACCESS_TOKEN environment variable is not set",
                }

            try:
                client = await self.get_http_client()
                url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
                
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                }
                
                params = {
                    "q": query,
                    "maxResults": max_results,
                }
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                return {
                    "ok": True,
                    "messages": data.get("messages", []),
                    "resultSizeEstimate": data.get("resultSizeEstimate"),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": "gmail_request_failed",
                    "message": str(e),
                }
