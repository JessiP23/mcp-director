"""Base plugin class for MCP tools with connection pooling and circuit breaker."""

from abc import ABC, abstractmethod
from typing import Any, Optional
import asyncio
import httpx
from functools import wraps
import structlog

log = structlog.get_logger(__name__)


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Circuit breaker pattern for external API calls."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Exception = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half-open

    def record_success(self):
        """Record a successful call."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            log.warning(
                "circuit_breaker_opened",
                failure_count=self.failure_count,
                threshold=self.failure_threshold,
            )

    def can_attempt(self) -> bool:
        """Check if a call can be attempted."""
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time is None:
                return False
            if asyncio.get_event_loop().time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                log.info("circuit_breaker_half_open")
                return True
            return False
        return True  # half-open allows one attempt


class BasePlugin(ABC):
    """Base class for MCP tool plugins with connection pooling."""

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._circuit_breaker = CircuitBreaker()
        self.category: str = "general"
        self.enabled: bool = True
        self._user_tokens: Dict[str, str] = {}  # user_id -> token

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version."""
        pass

    @abstractmethod
    async def register_tools(self, mcp: Any) -> None:
        """Register tools with the MCP server."""
        pass

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=100,
                    keepalive_expiry=30.0,
                ),
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client and cleanup resources."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def with_circuit_breaker(self, func):
        """Decorator to wrap function with circuit breaker."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not self._circuit_breaker.can_attempt():
                raise CircuitBreakerError(
                    f"Circuit breaker is open for {self.name}. "
                    f"Retry after {self._circuit_breaker.recovery_timeout}s"
                )

            try:
                result = await func(*args, **kwargs)
                self._circuit_breaker.record_success()
                return result
            except Exception as e:
                self._circuit_breaker.record_failure()
                log.error(
                    "plugin_call_failed",
                    plugin=self.name,
                    error=str(e),
                    failure_count=self._circuit_breaker.failure_count,
                )
                raise

        return wrapper

    async def health_check(self) -> dict[str, Any]:
        """Health check for the plugin."""
        return {
            "name": self.name,
            "version": self.version,
            "category": self.category,
            "enabled": self.enabled,
            "circuit_breaker_state": self._circuit_breaker.state,
            "failure_count": self._circuit_breaker.failure_count,
        }

    def set_user_token(self, user_id: str, token: str) -> None:
        """Set OAuth token for a specific user."""
        self._user_tokens[user_id] = token

    def get_user_token(self, user_id: str) -> Optional[str]:
        """Get OAuth token for a specific user."""
        return self._user_tokens.get(user_id)

    def has_user_token(self, user_id: str) -> bool:
        """Check if a user has a token set."""
        return user_id in self._user_tokens
