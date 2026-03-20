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

USER_YOUTUBE_ACCOUNTS_KEY = "youtube_accounts"


def apply_secret_record(
    record: dict[str, Any],
    *,
    env_field_map: dict[str, str] | None = None,
    refresh_token_env: str | None = YOUTUBE_REFRESH_TOKEN_ENV,
) -> dict[str, Any]:
    merged = dict(record)
    encrypted_secrets = merged.get(ENCRYPTED_SECRETS_KEY)
    if not isinstance(encrypted_secrets, dict):
        encrypted_secrets = {}

    for field, env_name in (env_field_map or {}).items():
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

    refresh_token = ""
    if refresh_token_env:
        refresh_token = os.environ.get(refresh_token_env, "").strip()
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

    youtube_accounts = merged.get(USER_YOUTUBE_ACCOUNTS_KEY)
    if isinstance(youtube_accounts, dict):
        hydrated_accounts: dict[str, Any] = {}
        for user_id, account in youtube_accounts.items():
            if not isinstance(account, dict):
                continue
            hydrated_account = dict(account)
            client_secret = str(hydrated_account.get("client_secret") or "").strip()
            if client_secret:
                hydrated_account["client_secret"] = _decrypt_nested_secret(client_secret)

            nested_oauth = hydrated_account.get("youtube_oauth")
            if isinstance(nested_oauth, dict):
                oauth_copy = dict(nested_oauth)
                refresh_token = str(oauth_copy.get("refresh_token") or "").strip()
                if refresh_token:
                    oauth_copy["refresh_token"] = _decrypt_nested_secret(refresh_token)
                hydrated_account["youtube_oauth"] = oauth_copy
            hydrated_accounts[str(user_id)] = hydrated_account

        if hydrated_accounts:
            merged[USER_YOUTUBE_ACCOUNTS_KEY] = hydrated_accounts
        else:
            merged.pop(USER_YOUTUBE_ACCOUNTS_KEY, None)
    return merged


def sanitize_secret_record(
    record: dict[str, Any],
    *,
    env_field_map: dict[str, str] | None = None,
    refresh_token_env: str | None = YOUTUBE_REFRESH_TOKEN_ENV,
) -> dict[str, Any]:
    sanitized = dict(record)
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

    for field, env_name in (env_field_map or {}).items():
        raw_value = str(record.get(field) or "").strip()
        sanitized.pop(field, None)
        if env_name and os.environ.get(env_name, "").strip():
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

    refresh_token = str((record.get("youtube_oauth") or {}).get("refresh_token") or "").strip()
    oauth_record.pop("refresh_token", None)
    if oauth_record:
        sanitized["youtube_oauth"] = oauth_record
    else:
        sanitized.pop("youtube_oauth", None)

    env_refresh_token = os.environ.get(refresh_token_env, "").strip() if refresh_token_env else ""
    if env_refresh_token:
        sanitized.pop(ENCRYPTED_REFRESH_TOKEN_KEY, None)
    elif refresh_token:
        sanitized[ENCRYPTED_REFRESH_TOKEN_KEY] = _encrypt_value(refresh_token)
    else:
        sanitized.pop(ENCRYPTED_REFRESH_TOKEN_KEY, None)

    youtube_accounts = sanitized.get(USER_YOUTUBE_ACCOUNTS_KEY)
    if isinstance(youtube_accounts, dict):
        sanitized_accounts: dict[str, Any] = {}
        for user_id, account in youtube_accounts.items():
            if not isinstance(account, dict):
                continue
            sanitized_account = dict(account)

            client_secret = str(sanitized_account.get("client_secret") or "").strip()
            if client_secret:
                sanitized_account["client_secret"] = _encrypt_nested_secret(client_secret)
            else:
                sanitized_account.pop("client_secret", None)

            nested_oauth = sanitized_account.get("youtube_oauth")
            if isinstance(nested_oauth, dict):
                oauth_copy = dict(nested_oauth)
                refresh_token = str(oauth_copy.get("refresh_token") or "").strip()
                if refresh_token:
                    oauth_copy["refresh_token"] = _encrypt_nested_secret(refresh_token)
                else:
                    oauth_copy.pop("refresh_token", None)
                if oauth_copy:
                    sanitized_account["youtube_oauth"] = oauth_copy
                else:
                    sanitized_account.pop("youtube_oauth", None)
            else:
                sanitized_account.pop("youtube_oauth", None)

            sanitized_accounts[str(user_id)] = sanitized_account

        if sanitized_accounts:
            sanitized[USER_YOUTUBE_ACCOUNTS_KEY] = sanitized_accounts
        else:
            sanitized.pop(USER_YOUTUBE_ACCOUNTS_KEY, None)

    return sanitized


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


def _decrypt_nested_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    fernet = _get_fernet()
    if not fernet:
        return raw
    try:
        return fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("Unable to decrypt stored secret value. Check %s.", SHORTMAKER_SECRET_KEY_ENV)
        return raw


def _encrypt_nested_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    fernet = _get_fernet()
    if not fernet:
        return raw
    return fernet.encrypt(raw.encode("utf-8")).decode("utf-8")


def apply_runtime_secrets(config: dict[str, Any]) -> dict[str, Any]:
    return apply_secret_record(
        config,
        env_field_map=SECRET_FIELD_ENV_MAP,
        refresh_token_env=YOUTUBE_REFRESH_TOKEN_ENV,
    )


def sanitize_persisted_config(config: dict[str, Any]) -> dict[str, Any]:
    return sanitize_secret_record(
        config,
        env_field_map=SECRET_FIELD_ENV_MAP,
        refresh_token_env=YOUTUBE_REFRESH_TOKEN_ENV,
    )
