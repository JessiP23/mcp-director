from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
import inspect
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from redis.asyncio import Redis

from src.config import Settings, get_settings

log = structlog.get_logger(__name__)

CODE_TTL = 600
PKCE_PENDING_TTL = 1800  # 30min — covers slow IdP sign-in + 2FA without breaking the flow.
CLIENT_TTL = 86400 * 365

# Supabase GoTrue: min code_verifier length per RFC 7636 (auth enforces similar bounds).
_SUPABASE_VERIFIER_NUM_BYTES = 32

class AuthConfigError(RuntimeError):
    pass

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = _b64url_encode(digest)
    return secrets.compare_digest(expected, code_challenge)

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _opaque_prefix(value: str, n: int = 16) -> str:
    """Log correlation (state, codes) without revealing raw values."""
    return _token_hash(value)[:n]


def _http_request_id(request: Request) -> str:
    """Correlate logs with Fly / AWS / proxies without persisting secrets."""
    return (
        request.headers.get("fly-request-id")
        or request.headers.get("x-request-id")
        or secrets.token_hex(8)
    )


def _supabase_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, S256 code_challenge) for Supabase /authorize + /token PKCE."""
    verifier = secrets.token_urlsafe(_SUPABASE_VERIFIER_NUM_BYTES)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = _b64url_encode(digest)
    return verifier, challenge


def mcp_upstream_token_key(mcp_access_token: str) -> str:
    """Redis key for the director-cut (Supabase) bearer paired with an MCP access token."""
    return f"mcp:upstream:{_token_hash(mcp_access_token)}"

def create_mcp_access_token(
    *,
    settings: Settings,
    user_id: str,
    scopes: list[str],
    client_id: str | None = None,
) -> tuple[str, int]:
    now = int(time.time())
    exp = now + settings.token_ttl_seconds
    payload: dict[str, Any] = {
        "iss": settings.mcp_base_url.rstrip("/"),
        "sub": user_id,
        "aud": settings.mcp_audience,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "jti": secrets.token_urlsafe(16),
        "scopes": scopes,
    }
    if client_id:
        payload["azp"] = client_id
        payload["client_id"] = client_id
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.token_ttl_seconds

def create_test_token(
    *,
    user_id: str = "test-user",
    scopes: list[str] | None = None,
    secret: str | None = None,
    algorithm: str = "HS256",
    audience: str = "director-mcp",
    expires_in: int = 3600,
) -> str:
    """JWT helper for tests (same shape as production tokens)."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "scopes": scopes or ["pipeline:read", "pipeline:write", "assets:read"],
    }
    return jwt.encode(
        payload,
        secret or settings.jwt_secret,
        algorithm=algorithm,
    )

async def validate_mcp_token(token: str, *, redis: Redis | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.mcp_audience,
        )
    except JWTError as e:
        log.warning(
            "mcp_token_validation_failed",
            reason=str(e),
            token_prefix=token[:12] if token else "",
        )
        raise ValueError("invalid token") from e
    th = _token_hash(token)
    if redis:
        revoked = await redis.sismember("mcp:tokens:revoked", th)  # type: ignore[misc]
        if revoked:
            raise ValueError("token revoked")
    if "sub" not in claims:
        raise ValueError("invalid subject")
    scopes = claims.get("scopes")
    if isinstance(scopes, str):
        scopes_list = scopes.split()
    elif isinstance(scopes, list):
        scopes_list = [str(s) for s in scopes]
    else:
        scopes_list = []
    return {"user_id": str(claims["sub"]), "scopes": scopes_list, "raw": claims}

def _ensure_https_production(request: Request, settings: Settings) -> None:
    if settings.environment != "production" and not settings.enforce_https:
        return
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto != "https":
        raise HTTPException(status_code=400, detail="HTTPS required")

def build_oauth_router(*, redis_factory: Any | None = None) -> APIRouter:
    router = APIRouter()

    async def redis_client() -> Redis:
        if redis_factory is not None:
            r = redis_factory()
            if inspect.isawaitable(r):
                return await r
            return r
        return Redis.from_url(get_settings().redis_url, decode_responses=True)

    @router.get("/.well-known/oauth-protected-resource")
    async def protected_resource_metadata(request: Request):
        settings = get_settings()
        _ensure_https_production(request, settings)
        base = settings.mcp_base_url.rstrip("/")
        # Canonical resource URL must include trailing slash so clients (e.g. Claude)
        # do not hit /mcp → 307 → /mcp/ during Streamable HTTP (breaks some clients).
        return JSONResponse(
            {
                "resource": f"{base}/mcp/",
                "authorization_servers": [base],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [
                    "pipeline:read",
                    "pipeline:write",
                    "assets:read",
                ],
            }
        )

    @router.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata(request: Request):
        settings = get_settings()
        _ensure_https_production(request, settings)
        base = settings.mcp_base_url.rstrip("/")
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "registration_endpoint": f"{base}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": [
                    "pipeline:read",
                    "pipeline:write",
                    "assets:read",
                ],
            }
        )

    async def _oauth_supabase_return(request: Request) -> RedirectResponse:
        """First-party return from Supabase OAuth (after Google / IdP). Correlation via mcp_oauth."""
        settings = get_settings()
        _ensure_https_production(request, settings)
        req_id = _http_request_id(request)
        q = request.query_params
        correlation = q.get("mcp_oauth") or q.get("state")
        code = q.get("code")
        if not code or not correlation:
            log.warning(
                "oauth_idp_callback_missing_params",
                http_request_id=req_id,
                has_code=bool(code),
                has_correlation=bool(correlation),
            )
            raise HTTPException(status_code=400, detail="invalid callback")

        redis = await redis_client()
        corr_p = _opaque_prefix(str(correlation))
        code_p = _opaque_prefix(str(code))
        raw = await redis.get(f"oauth:pkce:pending:{correlation}")
        if not raw:
            log.warning(
                "oauth_supabase_return_pending_miss",
                http_request_id=req_id,
                correlation_sha256_prefix=corr_p,
                oauth_code_sha256_prefix=code_p,
            )
            raise HTTPException(status_code=400, detail="unknown or expired state")

        pending = json.loads(raw)
        supa_verifier = pending.get("supabase_code_verifier")
        if not supa_verifier or not isinstance(supa_verifier, str):
            log.warning(
                "oauth_supabase_return_pending_malformed",
                http_request_id=req_id,
                correlation_sha256_prefix=corr_p,
            )
            raise HTTPException(status_code=400, detail="invalid oauth session")

        log.info(
            "oauth_idp_callback_pending_hit",
            http_request_id=req_id,
            correlation_sha256_prefix=corr_p,
            oauth_code_sha256_prefix=code_p,
        )

        # GoTrue exposes PKCE exchange as grant_type=pkce with JSON auth_code + code_verifier
        # (not OAuth2-style grant_type=authorization_code / "code").
        token_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/token?grant_type=pkce"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                token_url,
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Content-Type": "application/json",
                },
                json={
                    "auth_code": code,
                    "code_verifier": supa_verifier,
                },
            )
        if resp.status_code >= 400:
            err_snip = (resp.text or "")[:200]
            log.warning(
                "supabase_token_exchange_failed",
                http_request_id=req_id,
                status=resp.status_code,
                body_snippet=err_snip,
                correlation_sha256_prefix=corr_p,
            )
            raise HTTPException(status_code=401, detail="supabase code exchange failed")
        body = resp.json()
        access = body.get("access_token")
        if not access:
            raise HTTPException(status_code=401, detail="no access token from supabase")

        try:
            unverified = jwt.get_unverified_claims(access)
            user_id = str(unverified.get("sub", ""))
        except JWTError:
            user_id = ""
        if not user_id:
            raise HTTPException(status_code=401, detail="invalid supabase session")

        director_code = secrets.token_urlsafe(48)
        code_payload = {
            "user_id": user_id,
            "code_challenge": pending["code_challenge"],
            "redirect_uri": pending["redirect_uri"],
            "client_id": pending["client_id"],
            "scopes": ["pipeline:read", "pipeline:write", "assets:read"],
            "supabase_access": access,
        }
        await redis.setex(
            f"oauth:code:{director_code}",
            CODE_TTL,
            json.dumps(code_payload),
        )
        await redis.delete(f"oauth:pkce:pending:{correlation}")

        dest = urlparse(pending["redirect_uri"])
        query = f"code={quote(director_code)}&state={quote(pending['client_state'])}"
        if dest.query:
            new_query = f"{dest.query}&{query}"
        else:
            new_query = query
        loc = urlunparse(
            (dest.scheme, dest.netloc, dest.path, dest.params, new_query, dest.fragment)
        )
        log.info(
            "oauth_redirect_mcp_client",
            http_request_id=req_id,
            correlation_sha256_prefix=corr_p,
            mcp_client_redirect_host=dest.netloc or "",
        )
        return RedirectResponse(loc, status_code=302)

    @router.get("/oauth/authorize")
    async def oauth_authorize(request: Request):
        settings = get_settings()
        _ensure_https_production(request, settings)
        q = request.query_params
        client_id = q.get("client_id")
        redirect_uri = q.get("redirect_uri")
        state = q.get("state")
        code_challenge = q.get("code_challenge")
        code_challenge_method = q.get("code_challenge_method")
        if not client_id or not redirect_uri or not state or not code_challenge:
            raise HTTPException(status_code=400, detail="missing required parameters")
        if code_challenge_method != "S256":
            raise HTTPException(status_code=400, detail="only S256 is supported")
        if not settings.supabase_anon_key:
            raise HTTPException(status_code=503, detail="Supabase not configured")

        supa_verifier, supa_challenge = _supabase_pkce_pair()
        redis = await redis_client()
        bridge = secrets.token_urlsafe(32)
        pending = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "client_state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "supabase_code_verifier": supa_verifier,
        }
        await redis.setex(
            f"oauth:pkce:pending:{bridge}",
            PKCE_PENDING_TTL,
            json.dumps(pending),
        )

        public_base = settings.mcp_base_url.rstrip("/")
        idp_callback = f"{public_base}/oauth/idp-callback?mcp_oauth={quote(bridge, safe='')}"
        log.info(
            "oauth_authorize_start",
            http_request_id=_http_request_id(request),
            correlation_sha256_prefix=_opaque_prefix(bridge),
            oauth_idp_callback_url=idp_callback.split("?")[0],
            supabase_server_pkce=True,
            mcp_client_redirect_host=urlparse(redirect_uri).netloc or "",
            supabase_host=urlparse(settings.supabase_url).netloc,
        )
        # No `state` query here: GoTrue forwards unknown params to Google as OAuth `state`,
        # overriding the flow-state UUID and causing bad_oauth_state on /auth/v1/callback.
        supabase_authorize = (
            f"{settings.supabase_url.rstrip('/')}/auth/v1/authorize"
            f"?provider={quote(settings.supabase_oauth_provider)}"
            f"&redirect_to={quote(idp_callback, safe='')}"
            f"&code_challenge={quote(supa_challenge, safe='')}"
            f"&code_challenge_method=S256"
        )
        return RedirectResponse(supabase_authorize, status_code=302)

    @router.get("/oauth/idp-callback")
    async def oauth_idp_callback(request: Request):
        return await _oauth_supabase_return(request)

    @router.get("/oauth/callback")
    async def oauth_supabase_callback(request: Request):
        """Legacy path; prefer /oauth/idp-callback in Supabase redirect allowlists."""
        return await _oauth_supabase_return(request)

    @router.post("/oauth/token")
    async def oauth_token(request: Request):
        settings = get_settings()
        _ensure_https_production(request, settings)
        req_id = _http_request_id(request)
        form = await request.form()
        grant_type = form.get("grant_type")
        if grant_type != "authorization_code":
            raise HTTPException(status_code=400, detail="unsupported grant_type")
        code_verifier = str(form.get("code_verifier") or "")
        code = str(form.get("code") or "")
        if not code_verifier or not code:
            raise HTTPException(status_code=400, detail="missing code or code_verifier")

        redis = await redis_client()
        raw = await redis.get(f"oauth:code:{code}")
        if not raw:
            log.warning(
                "oauth_token_code_miss",
                http_request_id=req_id,
                code_sha256_prefix=_opaque_prefix(code),
            )
            raise HTTPException(status_code=401, detail="invalid code")
        payload = json.loads(raw)
        if not verify_pkce(code_verifier, payload["code_challenge"]):
            log.warning(
                "oauth_token_pkce_failed",
                http_request_id=req_id,
                code_sha256_prefix=_opaque_prefix(code),
            )
            raise HTTPException(status_code=401, detail="invalid code_verifier")

        await redis.delete(f"oauth:code:{code}")

        access_token, expires_in = create_mcp_access_token(
            settings=settings,
            user_id=payload["user_id"],
            scopes=list(payload.get("scopes", [])),
            client_id=payload.get("client_id"),
        )
        th = _token_hash(access_token)
        await redis.setex(
            f"oauth:token:active:{th}",
            expires_in + 60,
            payload["user_id"],
        )
        upstream = payload.get("supabase_access")
        if upstream:
            await redis.setex(
                mcp_upstream_token_key(access_token),
                expires_in + 120,
                upstream,
            )
        scope_str = " ".join(payload.get("scopes", []))
        log.info(
            "oauth_token_issued",
            http_request_id=req_id,
            mcp_token_sha256_prefix=_opaque_prefix(access_token),
        )
        # OAuth 2.1 §3.1.5: token endpoint responses MUST set Cache-Control: no-store.
        # Some clients (incl. Claude.ai) treat cached/replayed token responses as failures.
        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "scope": scope_str,
            },
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )

    @router.post("/oauth/register")
    async def oauth_register(request: Request):
        settings = get_settings()
        _ensure_https_production(request, settings)
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail="invalid json") from e

        redirect_uris = body.get("redirect_uris") or []
        if not redirect_uris:
            raise HTTPException(status_code=400, detail="redirect_uris required")

        client_id = str(uuid.uuid4())
        meta = {
            "client_id": client_id,
            "client_name": body.get("client_name", "mcp-client"),
            "redirect_uris": redirect_uris,
            "grant_types": body.get("grant_types", ["authorization_code"]),
            "token_endpoint_auth_method": body.get(
                "token_endpoint_auth_method", "none"
            ),
            "client_id_issued_at": int(time.time()),
        }
        redis = await redis_client()
        await redis.setex(
            f"oauth:client:{client_id}",
            CLIENT_TTL,
            json.dumps(meta),
        )
        return JSONResponse(meta)

    return router
