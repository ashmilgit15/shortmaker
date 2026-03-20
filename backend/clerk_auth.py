from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import jwt
import logging
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

JWKS_CACHE_TTL_SECONDS = 300
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
BASE_DIR = Path(__file__).resolve().parent.parent


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


def _normalize_issuer(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _read_env_key(path: Path, key: str) -> str:
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            raw_key, raw_value = line.split("=", 1)
            if raw_key.strip() != key:
                continue
            value = raw_value.strip()
            if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    except OSError:
        return ""
    return ""


def _derive_issuer_from_publishable_key(publishable_key: str) -> str:
    raw = str(publishable_key or "").strip()
    match = re.match(r"^pk_(?:test|live)_(.+)$", raw)
    if not match:
        return ""
    payload = match.group(1)
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8").rstrip("$")
    except Exception:
        return ""
    return _normalize_issuer(f"https://{decoded}")


def _local_frontend_issuer() -> str:
    for path in (BASE_DIR / "frontend" / ".env.local", BASE_DIR / "frontend" / ".env"):
        publishable_key = _read_env_key(path, "VITE_CLERK_PUBLISHABLE_KEY")
        if publishable_key:
            issuer = _derive_issuer_from_publishable_key(publishable_key)
            if issuer:
                return issuer
    return ""


def _allowed_issuers() -> set[str]:
    issuers = set()
    configured = _normalize_issuer(os.environ.get("CLERK_ISSUER", ""))
    if configured:
        issuers.add(configured)
    local_frontend = _local_frontend_issuer()
    if local_frontend:
        issuers.add(local_frontend)
    return issuers


def _require_allowed_issuer(claimed_issuer: str) -> str:
    configured = _normalize_issuer(os.environ.get("CLERK_ISSUER", ""))
    normalized_claim = _normalize_issuer(claimed_issuer)
    logger.debug("Issuer validation: claimed=%s configured=%s", normalized_claim, configured)
    if not normalized_claim:
        raise HTTPException(status_code=401, detail="Token issuer is missing.")

    allowed_issuers = _allowed_issuers()
    if not allowed_issuers:
        raise HTTPException(
            status_code=503,
            detail="CLERK_ISSUER is not configured on the server.",
        )

    parsed = urlparse(normalized_claim)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=401, detail="Token issuer is invalid.")
    logger.debug("Issuer check: normalized_claim=%s allowed_issuers=%s", normalized_claim, allowed_issuers)
    if normalized_claim not in allowed_issuers:
        logger.warning("Issuer mismatch: claimed=%s allowed=%s", normalized_claim, allowed_issuers)
        raise HTTPException(status_code=401, detail="Token issuer does not match configured Clerk issuer.")
    return normalized_claim if normalized_claim else configured


def _get_jwks_url(issuer: str) -> str:
    configured = os.environ.get("CLERK_JWKS_URL", "").strip()
    configured_issuer = _normalize_issuer(os.environ.get("CLERK_ISSUER", ""))
    if configured and configured_issuer == _normalize_issuer(issuer):
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

    jwks_url = _get_jwks_url(issuer)
    jwks = _fetch_jwks(jwks_url)
    logger.debug("JWKS keys from %s: %s", jwks_url, [k.get("kid") for k in jwks.get("keys", [])])
    for key in jwks.get("keys", []):
        if str(key.get("kid")) == key_id:
            return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))

    raise HTTPException(status_code=401, detail="Unable to match Clerk signing key.")


def verify_clerk_token(token: str) -> ClerkUser:
    logger.warning("DEBUG env CLERK_ISSUER=%s", os.environ.get("CLERK_ISSUER", "NOT_SET"))
    logger.warning("DEBUG env CLERK_AUDIENCE=%s", os.environ.get("CLERK_AUDIENCE", "NOT_SET"))
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
            leeway=30,
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT decode failed: %s", exc)
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
