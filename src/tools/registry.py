"""Plugin registry for lazy loading and discovery of MCP tool plugins."""

import importlib
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import structlog

from .base import BasePlugin

log = structlog.get_logger(__name__)


class PluginRegistry:
    """Registry for managing MCP tool plugins with lazy loading."""

    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}
        self._plugin_classes: Dict[str, type[BasePlugin]] = {}
        self._categories: Dict[str, Set[str]] = {}
        self._enabled_plugins: Set[str] = set()

    def register_plugin_class(self, plugin_class: type[BasePlugin]) -> None:
        """Register a plugin class for lazy loading."""
        plugin_name = plugin_class.name
        self._plugin_classes[plugin_name] = plugin_class
        log.info("plugin_class_registered", name=plugin_name, version=plugin_class.version)

    def load_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """Load a plugin by name (lazy loading)."""
        if plugin_name in self._plugins:
            return self._plugins[plugin_name]

        if plugin_name not in self._plugin_classes:
            log.warning("plugin_class_not_found", name=plugin_name)
            return None

        try:
            plugin = self._plugin_classes[plugin_name]()
            self._plugins[plugin_name] = plugin
            
            # Register category
            category = plugin.category
            if category not in self._categories:
                self._categories[category] = set()
            self._categories[category].add(plugin_name)
            
            log.info("plugin_loaded", name=plugin_name, category=category)
            return plugin
        except Exception as e:
            log.error("plugin_load_failed", name=plugin_name, error=str(e))
            return None

    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """Get a loaded plugin by name."""
        return self._plugins.get(plugin_name)

    def get_plugins_by_category(self, category: str) -> List[BasePlugin]:
        """Get all loaded plugins in a category."""
        if category not in self._categories:
            return []
        
        plugins = []
        for plugin_name in self._categories[category]:
            plugin = self.get_plugin(plugin_name)
            if plugin and plugin.enabled:
                plugins.append(plugin)
        return plugins

    def enable_plugin(self, plugin_name: str) -> bool:
        """Enable a plugin."""
        plugin = self.get_plugin(plugin_name)
        if plugin:
            plugin.enabled = True
            self._enabled_plugins.add(plugin_name)
            log.info("plugin_enabled", name=plugin_name)
            return True
        return False

    def disable_plugin(self, plugin_name: str) -> bool:
        """Disable a plugin."""
        plugin = self.get_plugin(plugin_name)
        if plugin:
            plugin.enabled = False
            self._enabled_plugins.discard(plugin_name)
            log.info("plugin_disabled", name=plugin_name)
            return True
        return False

    def get_enabled_plugins(self) -> List[BasePlugin]:
        """Get all enabled plugins."""
        return [p for p in self._plugins.values() if p.enabled]

    def get_all_categories(self) -> List[str]:
        """Get all available categories."""
        return list(self._categories.keys())

    async def register_all_tools(self, mcp: Any, categories: Optional[List[str]] = None) -> None:
        """Register tools from all enabled plugins, optionally filtered by category."""
        plugins = self.get_enabled_plugins()
        
        if categories:
            # Filter by categories
            filtered_plugins = []
            for category in categories:
                filtered_plugins.extend(self.get_plugins_by_category(category))
            plugins = filtered_plugins
        
        for plugin in plugins:
            try:
                await plugin.register_tools(mcp)
                log.info("plugin_tools_registered", name=plugin.name, category=plugin.category)
            except Exception as e:
                log.error("plugin_tools_registration_failed", name=plugin.name, error=str(e))

    async def close_all(self) -> None:
        """Close all plugins and cleanup resources."""
        for plugin in self._plugins.values():
            try:
                await plugin.close()
            except Exception as e:
                log.error("plugin_close_failed", name=plugin.name, error=str(e))
        self._plugins.clear()
        log.info("all_plugins_closed")

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all plugins."""
        status = {
            "total_plugins": len(self._plugins),
            "enabled_plugins": len(self._enabled_plugins),
            "categories": {},
            "plugins": {},
        }
        
        for category, plugin_names in self._categories.items():
            status["categories"][category] = {
                "count": len(plugin_names),
                "plugins": list(plugin_names),
            }
        
        for plugin_name, plugin in self._plugins.items():
            status["plugins"][plugin_name] = await plugin.health_check()
        
        return status

    def discover_plugins(self, tools_dir: Path = Path(__file__).parent) -> None:
        """Discover and register plugin classes from the tools directory."""
        # Skip __pycache__ and __init__.py
        for module_path in tools_dir.rglob("*.py"):
            if module_path.name.startswith("_") or module_path.name == "base.py" or module_path.name == "registry.py":
                continue
            
            # Calculate module path relative to tools_dir
            relative_path = module_path.relative_to(tools_dir.parent.parent)
            module_name = str(relative_path.with_suffix("")).replace("/", ".").replace("\\", ".")
            
            try:
                module = importlib.import_module(module_name)
                
                # Find all BasePlugin subclasses in the module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, BasePlugin)
                        and obj is not BasePlugin
                        and hasattr(obj, "name")
                    ):
                        self.register_plugin_class(obj)
                        log.info(
                            "plugin_discovered",
                            module=module_name,
                            class_name=name,
                            plugin_name=obj.name,
                        )
            except Exception as e:
                log.warning("plugin_discovery_failed", module=module_name, error=str(e))


# Global registry instance
registry = PluginRegistry()
