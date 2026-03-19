from __future__ import annotations

import logging
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

SHORTMAKER_SECRET_KEY_ENV = "SHORTMAKER_SECRET_KEY"
YOUTUBE_REFRESH_TOKEN_ENV = "YOUTUBE_REFRESH_TOKEN"
ENCRYPTED_SECRETS_KEY = "_encrypted_secrets"
ENCRYPTED_REFRESH_TOKEN_KEY = "_youtube_refresh_token"
PLACEHOLDER_SECRET_KEY_VALUES = {
    "replace_with_fernet_key",
    "replace-me",
    "changeme",
}

_FERNET_CACHE_KEY: str | None = None
_FERNET_CACHE_VALUE: Fernet | None = None
_LAST_INVALID_KEY_LOGGED: str | None = None

SECRET_FIELD_ENV_MAP: dict[str, str] = {
    "gemini_api_key": "GEMINI_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "firecrawl_api_key": "FIRECRAWL_API_KEY",
    "youtube_client_id": "YOUTUBE_CLIENT_ID",
    "youtube_client_secret": "YOUTUBE_CLIENT_SECRET",
}


def _get_fernet() -> Fernet | None:
    global _FERNET_CACHE_KEY, _FERNET_CACHE_VALUE, _LAST_INVALID_KEY_LOGGED

    raw_key = os.environ.get(SHORTMAKER_SECRET_KEY_ENV, "").strip()
    normalized_key = raw_key.lower()
    if not raw_key or normalized_key in PLACEHOLDER_SECRET_KEY_VALUES:
        _FERNET_CACHE_KEY = raw_key
        _FERNET_CACHE_VALUE = None
        return None

    if raw_key == _FERNET_CACHE_KEY:
        return _FERNET_CACHE_VALUE

    try:
        fernet = Fernet(raw_key.encode("utf-8"))
        _FERNET_CACHE_KEY = raw_key
        _FERNET_CACHE_VALUE = fernet
        return fernet
    except Exception:
        _FERNET_CACHE_KEY = raw_key
        _FERNET_CACHE_VALUE = None
        if raw_key != _LAST_INVALID_KEY_LOGGED:
            logger.warning(
                "%s is not a valid Fernet key. Secret persistence is disabled until a valid key is configured.",
                SHORTMAKER_SECRET_KEY_ENV,
            )
            _LAST_INVALID_KEY_LOGGED = raw_key
        return None


def has_secret_storage_key() -> bool:
    return _get_fernet() is not None


def _encrypt_value(value: str) -> str:
    fernet = _get_fernet()
    if not fernet:
        raise RuntimeError(
            f"{SHORTMAKER_SECRET_KEY_ENV} must be configured to persist secrets outside environment variables."
        )
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_value(value: str) -> str:
    fernet = _get_fernet()
    if not fernet:
        return ""
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("Unable to decrypt stored secret value. Check %s.", SHORTMAKER_SECRET_KEY_ENV)
        return ""


def apply_runtime_secrets(config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(config)
    encrypted_secrets = merged.get(ENCRYPTED_SECRETS_KEY)
    if not isinstance(encrypted_secrets, dict):
        encrypted_secrets = {}

    for field, env_name in SECRET_FIELD_ENV_MAP.items():
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            merged[field] = env_value
            continue

        encrypted_value = str(encrypted_secrets.get(field) or "").strip()
        if encrypted_value:
            merged[field] = _decrypt_value(encrypted_value)

    oauth_record = merged.get("youtube_oauth")
    if not isinstance(oauth_record, dict):
        oauth_record = {}
    else:
        oauth_record = dict(oauth_record)

    refresh_token = os.environ.get(YOUTUBE_REFRESH_TOKEN_ENV, "").strip()
    if refresh_token:
        oauth_record["refresh_token"] = refresh_token
    else:
        encrypted_refresh_token = str(merged.get(ENCRYPTED_REFRESH_TOKEN_KEY) or "").strip()
        if encrypted_refresh_token:
            decrypted_refresh_token = _decrypt_value(encrypted_refresh_token)
            if decrypted_refresh_token:
                oauth_record["refresh_token"] = decrypted_refresh_token

    if oauth_record:
        merged["youtube_oauth"] = oauth_record
    return merged


def sanitize_persisted_config(config: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(config)
    encrypted_secrets: dict[str, str] = {}

    existing_encrypted = sanitized.get(ENCRYPTED_SECRETS_KEY)
    if isinstance(existing_encrypted, dict):
        encrypted_secrets.update(
            {
                str(key): str(value)
                for key, value in existing_encrypted.items()
                if str(key).strip() and str(value).strip()
            }
        )

    for field in SECRET_FIELD_ENV_MAP:
        raw_value = str(config.get(field) or "").strip()
        sanitized.pop(field, None)
        if os.environ.get(SECRET_FIELD_ENV_MAP[field], "").strip():
            encrypted_secrets.pop(field, None)
            continue
        if raw_value:
            encrypted_secrets[field] = _encrypt_value(raw_value)
        else:
            encrypted_secrets.pop(field, None)

    if encrypted_secrets:
        sanitized[ENCRYPTED_SECRETS_KEY] = encrypted_secrets
    else:
        sanitized.pop(ENCRYPTED_SECRETS_KEY, None)

    oauth_record = sanitized.get("youtube_oauth")
    if not isinstance(oauth_record, dict):
        oauth_record = {}
    else:
        oauth_record = dict(oauth_record)

    refresh_token = str((config.get("youtube_oauth") or {}).get("refresh_token") or "").strip()
    oauth_record.pop("refresh_token", None)
    if oauth_record:
        sanitized["youtube_oauth"] = oauth_record
    else:
        sanitized.pop("youtube_oauth", None)

    if os.environ.get(YOUTUBE_REFRESH_TOKEN_ENV, "").strip():
        sanitized.pop(ENCRYPTED_REFRESH_TOKEN_KEY, None)
    elif refresh_token:
        sanitized[ENCRYPTED_REFRESH_TOKEN_KEY] = _encrypt_value(refresh_token)
    else:
        sanitized.pop(ENCRYPTED_REFRESH_TOKEN_KEY, None)

    return sanitized
