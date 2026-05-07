"""Application configuration from environment."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    director_base_url: str = Field(default="http://127.0.0.1:9420", alias="DIRECTOR_BASE_URL")
    # Optional: Supabase / WM Studio access JWT for director-cut API. Only applied when
    # `ENVIRONMENT=development` (e.g. smoke tests with create_test_token). OAuth clients
    # use the Supabase token stored in Redis at token exchange instead.
    director_bearer_token: str = Field(default="", alias="DIRECTOR_BEARER_TOKEN")
    jwt_secret: str = Field(default="change-me-32-chars-minimum-for-dev-only", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    token_ttl_seconds: int = Field(default=3600, alias="TOKEN_TTL_SECONDS")

    supabase_url: str = Field(default="https://your-project.supabase.co", alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_oauth_provider: str = Field(default="google", alias="SUPABASE_OAUTH_PROVIDER")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    mcp_port: int = Field(default=8080, alias="MCP_PORT")
    mcp_base_url: str = Field(default="http://localhost:8080", alias="MCP_BASE_URL")

    rate_limit_calls_per_minute: int = Field(default=60, alias="RATE_LIMIT_CALLS_PER_MINUTE")

    environment: str = Field(default="development", alias="ENVIRONMENT")
    enforce_https: bool = Field(default=False, alias="ENFORCE_HTTPS")

    mcp_audience: str = "director-mcp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
