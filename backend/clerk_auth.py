from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import Header, HTTPException

JWKS_CACHE_TTL_SECONDS = 3600
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass
class ClerkUser:
    id: str
    email: str
    first_name: str
    last_name: str
    image_url: str
    claims: dict[str, Any]


def _extract_bearer_token(authorization: Optional[str]) -> str:
    raw_value = (authorization or "").strip()
    if not raw_value:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    if not raw_value.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer token.")
    token = raw_value[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return token


def _require_allowed_issuer(claimed_issuer: str) -> str:
    configured = os.environ.get("CLERK_ISSUER", "").strip().rstrip("/")
    normalized_claim = claimed_issuer.strip().rstrip("/")
    if not normalized_claim:
        raise HTTPException(status_code=401, detail="Token issuer is missing.")

    if not configured:
        raise HTTPException(
            status_code=503,
            detail="CLERK_ISSUER is not configured on the server.",
        )

    parsed = urlparse(normalized_claim)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=401, detail="Token issuer is invalid.")
    if normalized_claim != configured:
        raise HTTPException(status_code=401, detail="Token issuer does not match configured Clerk issuer.")
    return configured


def _get_jwks_url(issuer: str) -> str:
    configured = os.environ.get("CLERK_JWKS_URL", "").strip()
    if configured:
        return configured
    return f"{issuer}/.well-known/jwks.json"


def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    cached = _JWKS_CACHE.get(jwks_url)
    if cached and (time.time() - cached[0]) < JWKS_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        response = httpx.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to load Clerk JWKS: {exc}") from exc

    _JWKS_CACHE[jwks_url] = (time.time(), payload)
    return payload


def _get_signing_key(token: str, issuer: str) -> Any:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token header: {exc}") from exc

    key_id = str(header.get("kid") or "").strip()
    if not key_id:
        raise HTTPException(status_code=401, detail="Token header is missing key id.")

    jwks = _fetch_jwks(_get_jwks_url(issuer))
    for key in jwks.get("keys", []):
        if str(key.get("kid")) == key_id:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))

    raise HTTPException(status_code=401, detail="Unable to match Clerk signing key.")


def verify_clerk_token(token: str) -> ClerkUser:
    try:
        unverified_claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
            },
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Clerk token: {exc}") from exc

    issuer = _require_allowed_issuer(str(unverified_claims.get("iss") or ""))
    audience = os.environ.get("CLERK_AUDIENCE", "").strip()
    decode_options = {
        "require": ["sub", "exp", "iat", "iss"],
        "verify_aud": bool(audience),
    }

    try:
        claims = jwt.decode(
            token,
            key=_get_signing_key(token, issuer),
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience or None,
            options=decode_options,
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Clerk token verification failed: {exc}") from exc

    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Clerk token does not include a user id.")

    email = (
        claims.get("email")
        or claims.get("email_address")
        or ""
    )
    first_name = claims.get("first_name") or ""
    last_name = claims.get("last_name") or ""
    image_url = claims.get("image_url") or claims.get("picture") or ""

    return ClerkUser(
        id=user_id,
        email=str(email),
        first_name=str(first_name),
        last_name=str(last_name),
        image_url=str(image_url),
        claims=claims,
    )


async def require_clerk_user(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> ClerkUser:
    token = _extract_bearer_token(authorization)
    return verify_clerk_token(token)
