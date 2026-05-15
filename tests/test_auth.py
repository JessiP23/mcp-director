"""OAuth metadata and token flow tests."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, unquote, urlparse

import httpx
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
    assert body["resource"].endswith("/mcp/")
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
    loc = r.headers["location"]
    assert "test.supabase.co/auth/v1/authorize" in loc
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query)
    assert "state" not in qs, "passing state to Supabase authorize breaks GoTrue/Google flow state"
    assert qs.get("code_challenge_method") == ["S256"]
    assert "code_challenge" in qs and len(qs["code_challenge"][0]) >= 43
    redirect_to = unquote(qs["redirect_to"][0])
    assert "/oauth/idp-callback" in redirect_to
    assert "mcp_oauth=" in redirect_to
    await fake.aclose()


@pytest.mark.asyncio
async def test_idp_callback_token_exchange_sends_server_code_verifier(respx_mock):
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))

    supa_access = jwt.encode(
        {"sub": "11111111-1111-1111-1111-111111111111"},
        "unused",
        algorithm="HS256",
    )
    token_url = "https://test.supabase.co/auth/v1/token?grant_type=pkce"
    respx_mock.post(token_url).mock(
        return_value=httpx.Response(200, json={"access_token": supa_access})
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ar = await ac.get(
            "/oauth/authorize",
            params={
                "client_id": "c1",
                "redirect_uri": "http://localhost/cb",
                "state": "claude-state-xyz",
                "code_challenge": _s256_challenge("mcp-verifier"),
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    assert ar.status_code == 302
    loc = ar.headers["location"]
    qs = parse_qs(urlparse(loc).query)
    bridge = parse_qs(urlparse(unquote(qs["redirect_to"][0])).query)["mcp_oauth"][0]
    raw_pending = await fake.get(f"oauth:pkce:pending:{bridge}")
    assert raw_pending
    supa_verifier = json.loads(raw_pending)["supabase_code_verifier"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        cb = await ac.get(
            "/oauth/idp-callback",
            params={"mcp_oauth": bridge, "code": "supabase-auth-code-from-google"},
            follow_redirects=False,
        )

    assert cb.status_code == 302
    loc = urlparse(cb.headers["location"])
    qcb = parse_qs(loc.query)
    assert qcb.get("state") == ["claude-state-xyz"]

    assert respx_mock.calls.call_count == 1
    sent = respx_mock.calls.last.request
    sent_json = json.loads(sent.content.decode())
    assert sent_json["auth_code"] == "supabase-auth-code-from-google"
    assert sent_json["code_verifier"] == supa_verifier

    await fake.aclose()


@pytest.mark.asyncio
async def test_legacy_oauth_callback_matches_idp_handler(respx_mock):
    """GET /oauth/callback is an alias; Supabase allowlists should prefer /oauth/idp-callback."""
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))

    supa_access = jwt.encode(
        {"sub": "11111111-1111-1111-1111-111111111111"},
        "unused",
        algorithm="HS256",
    )
    token_url = "https://test.supabase.co/auth/v1/token?grant_type=pkce"
    respx_mock.post(token_url).mock(
        return_value=httpx.Response(200, json={"access_token": supa_access})
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ar = await ac.get(
            "/oauth/authorize",
            params={
                "client_id": "c1",
                "redirect_uri": "http://localhost/cb",
                "state": "claude-state-xyz",
                "code_challenge": _s256_challenge("mcp-verifier"),
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    qs = parse_qs(urlparse(ar.headers["location"]).query)
    bridge = parse_qs(urlparse(unquote(qs["redirect_to"][0])).query)["mcp_oauth"][0]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        cb = await ac.get(
            "/oauth/callback",
            params={"mcp_oauth": bridge, "code": "supabase-auth-code"},
            follow_redirects=False,
        )
    assert cb.status_code == 302
    assert respx_mock.calls.call_count == 1
    await fake.aclose()


@pytest.mark.asyncio
async def test_idp_callback_pending_miss_400(respx_mock):
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/oauth/idp-callback",
            params={"mcp_oauth": "missing-bridge", "code": "x"},
        )
    assert r.status_code == 400
    assert respx_mock.calls.call_count == 0
    await fake.aclose()


@pytest.mark.asyncio
async def test_idp_callback_supabase_error_no_redirect_to_mcp_client(respx_mock):
    fake = aioredis.FakeRedis(decode_responses=True)
    app = FastAPI()
    app.include_router(build_oauth_router(redis_factory=lambda: fake))
    token_url = "https://test.supabase.co/auth/v1/token?grant_type=pkce"
    respx_mock.post(token_url).mock(return_value=httpx.Response(400, text="nope"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ar = await ac.get(
            "/oauth/authorize",
            params={
                "client_id": "c1",
                "redirect_uri": "http://localhost/cb",
                "state": "s",
                "code_challenge": _s256_challenge(secrets.token_urlsafe(32)),
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    qs = parse_qs(urlparse(ar.headers["location"]).query)
    bridge = parse_qs(urlparse(unquote(qs["redirect_to"][0])).query)["mcp_oauth"][0]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        cb = await ac.get("/oauth/idp-callback", params={"mcp_oauth": bridge, "code": "bad"})
    assert cb.status_code == 401
    assert respx_mock.calls.call_count == 1
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
    # New storage shape: JSON `{access, refresh, exp}` to enable transparent
    # refresh of expired Supabase access tokens. Plain access token is nested.
    parsed = json.loads(stored)
    assert parsed["access"] == "supa-jwt-xyz"
    assert "refresh" in parsed
    assert parsed["exp"] > 0
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
