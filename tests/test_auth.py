"""OAuth metadata and token flow tests."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets

import pytest
from fakeredis import aioredis
from httpx import ASGITransport
from httpx import AsyncClient
from jose import jwt

from fastapi import FastAPI

from src.auth import (
    build_oauth_router,
    create_test_token,
    mcp_upstream_token_key,
    validate_mcp_token,
    verify_pkce,
)
from src.config import get_settings


def _s256_challenge(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).decode().rstrip("=")


@pytest.mark.asyncio
async def test_protected_resource_metadata():
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].endswith("/mcp")
    await fake.aclose()


@pytest.mark.asyncio
async def test_authorize_without_state_400():
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/oauth/authorize",
            params={
                "client_id": "c1",
                "redirect_uri": "http://localhost/cb",
                "code_challenge": "x",
                "code_challenge_method": "S256",
            },
        )
    assert r.status_code == 400
    await fake.aclose()


@pytest.mark.asyncio
async def test_authorize_valid_redirects_supabase():
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/oauth/authorize",
            params={
                "client_id": "c1",
                "redirect_uri": "http://localhost/cb",
                "state": "csrf-client",
                "code_challenge": "chal",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "supabase.co/auth/v1/authorize" in r.headers["location"]
    await fake.aclose()


@pytest.mark.asyncio
async def test_token_wrong_verifier_401():
    fake = aioredis.FakeRedis(decode_responses=True)
    code = "dir-code-xyz"
    await fake.setex(
        f"oauth:code:{code}",
        600,
        json.dumps(
            {
                "user_id": "u1",
                "code_challenge": _s256_challenge("right-verifier"),
                "redirect_uri": "http://localhost/cb",
                "client_id": "c1",
                "scopes": ["pipeline:read"],
            }
        ),
    )
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": "wrong-verifier",
            },
        )
    assert r.status_code == 401
    await fake.aclose()


@pytest.mark.asyncio
async def test_token_valid_returns_jwt():
    fake = aioredis.FakeRedis(decode_responses=True)
    verifier = secrets.token_urlsafe(32)
    challenge = _s256_challenge(verifier)
    code = "dir-code-good"
    await fake.setex(
        f"oauth:code:{code}",
        600,
        json.dumps(
            {
                "user_id": "u1",
                "code_challenge": challenge,
                "redirect_uri": "http://localhost/cb",
                "client_id": "c1",
                "scopes": ["pipeline:read"],
            }
        ),
    )
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body.get("token_type") == "Bearer"
    assert "access_token" in body
    claims = await validate_mcp_token(body["access_token"], redis=fake)
    assert claims["user_id"] == "u1"
    await fake.aclose()


@pytest.mark.asyncio
async def test_token_valid_stores_supabase_upstream_in_redis():
    fake = aioredis.FakeRedis(decode_responses=True)
    verifier = secrets.token_urlsafe(32)
    challenge = _s256_challenge(verifier)
    code = "dir-code-upstream"
    await fake.setex(
        f"oauth:code:{code}",
        600,
        json.dumps(
            {
                "user_id": "u1",
                "code_challenge": challenge,
                "redirect_uri": "http://localhost/cb",
                "client_id": "c1",
                "scopes": ["pipeline:read"],
                "supabase_access": "supa-jwt-xyz",
            }
        ),
    )
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
        )
    assert r.status_code == 200
    body = r.json()
    at = body["access_token"]
    key = mcp_upstream_token_key(at)
    stored = await fake.get(key)
    assert stored == "supa-jwt-xyz"
    await fake.aclose()


@pytest.mark.asyncio
async def test_validate_mcp_token_expired():
    token = create_test_token(user_id="x", expires_in=-10)
    with pytest.raises(ValueError):
        await validate_mcp_token(token)


@pytest.mark.asyncio
async def test_validate_mcp_token_wrong_audience():
    settings = get_settings()
    now = __import__("time").time()
    bad = jwt.encode(
        {
            "sub": "u",
            "aud": "other",
            "iat": int(now),
            "exp": int(now) + 3600,
            "scopes": [],
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ValueError):
        await validate_mcp_token(bad)


def test_verify_pkce_roundtrip():
    v = secrets.token_urlsafe(48)
    c = _s256_challenge(v)
    assert verify_pkce(v, c)
