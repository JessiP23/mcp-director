"""Test plugin architecture functionality."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.tools.registry import registry
from src.tools.communication.telegram import TelegramPlugin
from src.tools.communication.slack import SlackPlugin
from src.tools.communication.gmail import GmailPlugin
from src.tools.base import CircuitBreakerError


@pytest.mark.asyncio
async def test_plugin_discovery():
    """Test that plugins are discovered correctly."""
    registry.discover_plugins()
    assert "telegram" in registry._plugin_classes
    assert "slack" in registry._plugin_classes
    assert "gmail" in registry._plugin_classes
    print("✓ Plugin discovery works")


@pytest.mark.asyncio
async def test_plugin_loading():
    """Test that plugins load correctly."""
    registry.discover_plugins()
    plugin = registry.load_plugin("telegram")
    assert plugin is not None
    assert plugin.name == "telegram"
    assert plugin.category == "communication"
    print("✓ Plugin loading works")


@pytest.mark.asyncio
async def test_circuit_breaker():
    """Test circuit breaker functionality."""
    plugin = TelegramPlugin()
    
    # Initially should be closed
    assert plugin._circuit_breaker.state == "closed"
    assert plugin._circuit_breaker.can_attempt() is True
    
    # Record failures to open circuit
    for _ in range(5):
        plugin._circuit_breaker.record_failure()
    
    assert plugin._circuit_breaker.state == "open"
    assert plugin._circuit_breaker.can_attempt() is False
    
    # Test circuit breaker decorator
    @plugin.with_circuit_breaker
    async def test_func():
        raise Exception("Test error")
    
    with pytest.raises(CircuitBreakerError):
        await test_func()
    
    print("✓ Circuit breaker works")


@pytest.mark.asyncio
async def test_http_client_pooling():
    """Test HTTP client connection pooling."""
    plugin = TelegramPlugin()
    
    # Get client
    client1 = await plugin.get_http_client()
    assert client1 is not None
    assert not client1.is_closed
    
    # Get client again (should reuse)
    client2 = await plugin.get_http_client()
    assert client1 is client2
    
    # Close plugin
    await plugin.close()
    assert client1.is_closed
    
    print("✓ HTTP client pooling works")


@pytest.mark.asyncio
async def test_telegram_tools_without_token():
    """Test Telegram tools return proper error when token is missing."""
    from fastmcp import FastMCP
    
    plugin = TelegramPlugin()
    mcp = FastMCP("test")
    
    # Register tools - this should not error
    await plugin.register_tools(mcp)
    print("✓ Telegram tools registered successfully")
    
    # Test that plugin is disabled when token is missing
    assert plugin.enabled is False
    print("✓ Telegram plugin disabled when token missing")


@pytest.mark.asyncio
async def test_plugin_health_check():
    """Test plugin health check."""
    plugin = TelegramPlugin()
    health = await plugin.health_check()
    
    assert health["name"] == "telegram"
    assert health["version"] == "1.0.0"
    assert health["category"] == "communication"
    assert "circuit_breaker_state" in health
    assert "failure_count" in health
    
    print("✓ Plugin health check works")


@pytest.mark.asyncio
async def test_plugin_registry_categories():
    """Test that plugins are categorized correctly."""
    registry.discover_plugins()
    plugin = registry.load_plugin("telegram")
    
    communication_plugins = registry.get_plugins_by_category("communication")
    # Check that the plugin name is in the category's plugin set
    assert plugin.name in registry._categories.get("communication", set())
    
    all_categories = registry.get_all_categories()
    assert "communication" in all_categories
    
    print("✓ Plugin categories work")


if __name__ == "__main__":
    asyncio.run(test_plugin_discovery())
    asyncio.run(test_plugin_loading())
    asyncio.run(test_circuit_breaker())
    asyncio.run(test_http_client_pooling())
    asyncio.run(test_telegram_tools_without_token())
    asyncio.run(test_plugin_health_check())
    asyncio.run(test_plugin_registry_categories())
    
    # Test Slack plugin
    print("\n--- Testing Slack Plugin ---")
    slack_plugin = SlackPlugin()
    assert slack_plugin.name == "slack"
    assert slack_plugin.category == "communication"
    print("✓ Slack plugin structure correct")
    
    # Test Gmail plugin
    print("\n--- Testing Gmail Plugin ---")
    gmail_plugin = GmailPlugin()
    assert gmail_plugin.name == "gmail"
    assert gmail_plugin.category == "communication"
    print("✓ Gmail plugin structure correct")
    
    print("\n✅ All plugin tests passed!")
