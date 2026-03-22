"""
youtube_publish.py - OAuth and upload helpers for publishing generated shorts.

Uses the official YouTube Data API `videos.insert` flow with OAuth 2.0
refresh tokens stored in the shared app config.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import warnings
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from utils.env_loader import load_dotenv_file

logger = logging.getLogger(__name__)

# Google may return previously granted scopes in addition to youtube.upload.
# oauthlib treats that scope expansion as a warning exception unless relaxed.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

BASE_DIR = Path(__file__).parent.parent
CLERK_RUNTIME_KEYS = ("CLERK_ISSUER", "CLERK_AUDIENCE", "CLERK_JWKS_URL")
load_dotenv_file(
    BASE_DIR / ".env",
    override_keys=CLERK_RUNTIME_KEYS,
    clear_missing_keys=CLERK_RUNTIME_KEYS,
)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_YOUTUBE_PRIVACY = "private"
DEFAULT_YOUTUBE_OAUTH_CALLBACK_PATH = "/youtube/oauth/callback"
VALID_PRIVACY_STATUSES = {"private", "unlisted", "public"}
DEFAULT_CATEGORY_ID = "22"
YOUTUBE_DEPENDENCY_HINT = (
    "Install YouTube publishing dependencies with "
    "`python -m pip install google-api-python-client google-auth-oauthlib`."
)
USER_YOUTUBE_ACCOUNTS_KEY = "youtube_accounts"


def _load_config() -> dict:
    from .ai_engine import load_config

    return load_config()


def _save_config(config: dict) -> None:
    from .ai_engine import save_config

    save_config(config)


def _normalize_privacy_status(value: Optional[str]) -> str:
    normalized = str(value or DEFAULT_YOUTUBE_PRIVACY).strip().lower()
    return normalized if normalized in VALID_PRIVACY_STATUSES else DEFAULT_YOUTUBE_PRIVACY


def _client_id_from_config(config: dict, *, allow_env_fallback: bool = True) -> str:
    value = str(config.get("youtube_client_id") or config.get("client_id") or "").strip()
    if value or not allow_env_fallback:
        return value
    return str(os.environ.get("YOUTUBE_CLIENT_ID", "")).strip()


def _client_secret_from_config(config: dict, *, allow_env_fallback: bool = True) -> str:
    value = str(config.get("youtube_client_secret") or config.get("client_secret") or "").strip()
    if value or not allow_env_fallback:
        return value
    return str(os.environ.get("YOUTUBE_CLIENT_SECRET", "")).strip()


def _oauth_record_from_config(config: dict) -> dict:
    record = config.get("youtube_oauth") or {}
    return record if isinstance(record, dict) else {}


def _pending_state_from_config(config: dict) -> str:
    return str(config.get("youtube_oauth_state") or "").strip()


def _pending_code_verifier_from_config(config: dict) -> str:
    return str(config.get("youtube_oauth_code_verifier") or "").strip()


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _build_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _youtube_accounts_from_config(config: dict, *, create: bool = False) -> dict:
    accounts = config.get(USER_YOUTUBE_ACCOUNTS_KEY)
    if isinstance(accounts, dict):
        return accounts
    if not create:
        return {}
    accounts = {}
    config[USER_YOUTUBE_ACCOUNTS_KEY] = accounts
    return accounts


def _get_user_youtube_account(config: dict, user_id: Optional[str], *, create: bool = False) -> dict:
    if not user_id:
        return config
    accounts = _youtube_accounts_from_config(config, create=create)
    account = accounts.get(user_id)
    if isinstance(account, dict):
        return account
    if not create:
        return {}
    account = {}
    accounts[user_id] = account
    return account


def _save_user_youtube_account(config: dict, user_id: Optional[str], account: dict) -> None:
    if not user_id:
        return
    accounts = _youtube_accounts_from_config(config, create=True)
    cleaned = dict(account)
    if cleaned:
        accounts[user_id] = cleaned
    else:
        accounts.pop(user_id, None)
    if not accounts:
        config.pop(USER_YOUTUBE_ACCOUNTS_KEY, None)


def _has_user_youtube_data(account: dict) -> bool:
    oauth = _oauth_record_from_config(account)
    return bool(
        str(account.get("youtube_client_id") or account.get("client_id") or "").strip()
        or str(account.get("youtube_client_secret") or account.get("client_secret") or "").strip()
        or str(account.get("youtube_default_privacy") or account.get("default_privacy") or "").strip()
        or str(account.get("youtube_oauth_state") or "").strip()
        or str(account.get("youtube_oauth_code_verifier") or "").strip()
        or str(oauth.get("refresh_token") or "").strip()
        or str(oauth.get("authorized_at") or "").strip()
    )


def _user_has_personal_client_config(account: dict) -> bool:
    return bool(
        str(account.get("youtube_client_id") or account.get("client_id") or "").strip()
        and str(account.get("youtube_client_secret") or account.get("client_secret") or "").strip()
    )


def _get_effective_youtube_record(config: dict, user_id: Optional[str]) -> tuple[dict, Optional[str]]:
    if not user_id:
        return config, None
    account = _get_user_youtube_account(config, user_id, create=False)
    if _has_user_youtube_data(account):
        return account, user_id
    return config, None


def _build_youtube_status_from_record(record: dict, *, allow_env_fallback: bool) -> dict:
    oauth = _oauth_record_from_config(record)
    connected = bool(oauth.get("refresh_token"))
    authorized_at = oauth.get("authorized_at")
    if connected:
        message = "YouTube is connected and ready for uploads."
    elif oauth.get("authorized_at"):
        message = (
            "A previous YouTube authorization exists, but no usable refresh token is available. "
            "Reconnect the account or set YOUTUBE_REFRESH_TOKEN."
        )
    else:
        message = "Add a YouTube OAuth client and connect an account."
    return {
        "has_client_config": bool(
            _client_id_from_config(record, allow_env_fallback=allow_env_fallback)
            and _client_secret_from_config(record, allow_env_fallback=allow_env_fallback)
        ),
        "connected": connected,
        "authorized_at": authorized_at,
        "default_privacy_status": _normalize_privacy_status(
            record.get("youtube_default_privacy")
            or record.get("default_privacy")
            or DEFAULT_YOUTUBE_PRIVACY
        ),
        "callback_path": _normalized_youtube_callback_path(),
        "message": message,
        "needs_reconnect": bool(oauth.get("authorized_at") and not connected),
    }


def has_youtube_client_config(user_id: Optional[str] = None) -> bool:
    config = _load_config()
    record, scope_owner_id = _get_effective_youtube_record(config, user_id)
    allow_env_fallback = scope_owner_id is None or not _user_has_personal_client_config(record)
    return bool(
        _client_id_from_config(record, allow_env_fallback=allow_env_fallback)
        and _client_secret_from_config(record, allow_env_fallback=allow_env_fallback)
    )


def has_youtube_connection(user_id: Optional[str] = None) -> bool:
    config = _load_config()
    record = _get_user_youtube_account(config, user_id, create=False) if user_id else config
    oauth = _oauth_record_from_config(record)
    return bool(oauth.get("refresh_token"))


def _require_google_dependency(module_name: str):
    try:
        module = __import__(module_name, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency '{module_name}'. {YOUTUBE_DEPENDENCY_HINT}"
        ) from exc
    return module


def get_youtube_status(user_id: Optional[str] = None) -> dict:
    config = _load_config()
    if user_id:
        personal_account = _get_user_youtube_account(config, user_id, create=False)
        has_personal_config = _has_user_youtube_data(personal_account)
        has_personal_client_config = _user_has_personal_client_config(personal_account)
        shared_status = _build_youtube_status_from_record(config, allow_env_fallback=True)
        effective_record = personal_account if has_personal_config else {}
        status = _build_youtube_status_from_record(
            effective_record,
            allow_env_fallback=not has_personal_client_config,
        )
        status.update(
            {
                "scope": "user",
                "scope_owner_id": user_id if has_personal_config else None,
                "has_personal_config": has_personal_config,
                "has_personal_client_config": has_personal_client_config,
                "shared_status": shared_status,
                "using_shared_fallback": not has_personal_config
                and bool(shared_status["has_client_config"] or shared_status["connected"]),
            }
        )
    else:
        record, scope_owner_id = _get_effective_youtube_record(config, user_id)
        status = _build_youtube_status_from_record(
            record,
            allow_env_fallback=scope_owner_id is None,
        )
        status.update(
            {
                "scope": "shared",
                "scope_owner_id": None,
                "has_personal_config": False,
                "has_personal_client_config": False,
                "using_shared_fallback": False,
            }
        )
    return status


def _normalized_youtube_callback_path() -> str:
    configured = str(os.environ.get("SHORTMAKER_YOUTUBE_OAUTH_CALLBACK_URI", "")).strip()
    parsed = urlparse(configured)
    if parsed.path:
        return parsed.path
    return DEFAULT_YOUTUBE_OAUTH_CALLBACK_PATH


def clear_youtube_connection(user_id: Optional[str] = None) -> None:
    config = _load_config()
    target = _get_user_youtube_account(config, user_id, create=False) if user_id else config
    target.pop("youtube_oauth", None)
    target.pop("youtube_oauth_state", None)
    target.pop("youtube_oauth_state_created_at", None)
    target.pop("youtube_oauth_code_verifier", None)
    if user_id:
        _save_user_youtube_account(config, user_id, target)
    _save_config(config)


def save_youtube_settings(
    *,
    client_id: str = "",
    client_secret: str = "",
    default_privacy_status: str = DEFAULT_YOUTUBE_PRIVACY,
    user_id: Optional[str] = None,
) -> dict:
    config = _load_config()
    normalized_privacy = _normalize_privacy_status(default_privacy_status)
    target = _get_user_youtube_account(config, user_id, create=bool(user_id)) if user_id else config
    client_id_key = "client_id" if user_id else "youtube_client_id"
    client_secret_key = "client_secret" if user_id else "youtube_client_secret"
    privacy_key = "default_privacy" if user_id else "youtube_default_privacy"
    effective_client_id = client_id.strip() or str(target.get(client_id_key) or "").strip()
    effective_client_secret = client_secret.strip() or str(target.get(client_secret_key) or "").strip()
    client_changed = bool(
        (client_id.strip() and client_id.strip() != str(target.get(client_id_key) or "").strip())
        or (client_secret.strip() and client_secret.strip() != str(target.get(client_secret_key) or "").strip())
    )

    target[client_id_key] = effective_client_id
    target[client_secret_key] = effective_client_secret
    target[privacy_key] = normalized_privacy
    if client_changed:
        target.pop("youtube_oauth", None)
        target.pop("youtube_oauth_state", None)
        target.pop("youtube_oauth_state_created_at", None)
        target.pop("youtube_oauth_code_verifier", None)
    if user_id:
        _save_user_youtube_account(config, user_id, target)
    _save_config(config)
    return get_youtube_status(user_id=user_id)


def build_authorization_url(redirect_uri: str, user_id: Optional[str] = None) -> str:
    Flow = _require_google_dependency("google_auth_oauthlib.flow").Flow

    config = _load_config()
    target = _get_user_youtube_account(config, user_id, create=False) if user_id else config
    allow_env_fallback = user_id is None or not _user_has_personal_client_config(target)
    client_id = _client_id_from_config(target, allow_env_fallback=allow_env_fallback)
    client_secret = _client_secret_from_config(target, allow_env_fallback=allow_env_fallback)
    if not client_id or not client_secret:
        raise ValueError(
            "YouTube OAuth client ID and client secret are required before connecting an account."
        )

    state = secrets.token_urlsafe(24)
    code_verifier = _generate_code_verifier()
    code_challenge = _build_code_challenge(code_verifier)
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=[YOUTUBE_UPLOAD_SCOPE])
    flow.redirect_uri = redirect_uri
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    if user_id:
        target = _get_user_youtube_account(config, user_id, create=True)
    target["youtube_oauth_state"] = state
    target["youtube_oauth_state_created_at"] = datetime.now(timezone.utc).isoformat()
    target["youtube_oauth_code_verifier"] = code_verifier
    if user_id:
        _save_user_youtube_account(config, user_id, target)
    _save_config(config)
    return auth_url


def _build_client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def _find_oauth_target_for_state(config: dict, state: str) -> tuple[dict, Optional[str]]:
    if state and state == _pending_state_from_config(config):
        return config, None

    accounts = _youtube_accounts_from_config(config, create=False)
    for user_id, account in accounts.items():
        if not isinstance(account, dict):
            continue
        if state and state == str(account.get("youtube_oauth_state") or "").strip():
            return account, str(user_id)

    raise ValueError("OAuth state verification failed. Start the YouTube connect flow again.")


def complete_oauth_callback(code: str, state: str, redirect_uri: str) -> dict:
    Flow = _require_google_dependency("google_auth_oauthlib.flow").Flow

    if not code:
        raise ValueError("Missing OAuth authorization code.")

    config = _load_config()
    target, scope_user_id = _find_oauth_target_for_state(config, state)
    allow_env_fallback = scope_user_id is None or not _user_has_personal_client_config(target)
    client_id = _client_id_from_config(target, allow_env_fallback=allow_env_fallback)
    client_secret = _client_secret_from_config(target, allow_env_fallback=allow_env_fallback)
    code_verifier = _pending_code_verifier_from_config(target)
    if not client_id or not client_secret:
        raise ValueError("YouTube OAuth client settings are missing.")
    if not code_verifier:
        raise ValueError("OAuth code verifier missing. Start the YouTube connect flow again.")

    flow = Flow.from_client_config(
        _build_client_config(client_id, client_secret, redirect_uri),
        scopes=[YOUTUBE_UPLOAD_SCOPE],
        state=state,
    )
    flow.redirect_uri = redirect_uri
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"Scope has changed from .*", category=Warning)
        flow.fetch_token(code=code, code_verifier=code_verifier)

    credentials = flow.credentials
    refresh_token = credentials.refresh_token or _oauth_record_from_config(target).get("refresh_token")
    if not refresh_token:
        raise ValueError(
            "Google did not return a refresh token. Reconnect with consent enabled and ensure the OAuth client is configured correctly."
        )

    target["youtube_oauth"] = {
        "refresh_token": refresh_token,
        "token_uri": credentials.token_uri or GOOGLE_TOKEN_URI,
        "scopes": list(credentials.scopes or [YOUTUBE_UPLOAD_SCOPE]),
        "authorized_at": datetime.now(timezone.utc).isoformat(),
    }
    target.pop("youtube_oauth_state", None)
    target.pop("youtube_oauth_state_created_at", None)
    target.pop("youtube_oauth_code_verifier", None)
    if scope_user_id:
        _save_user_youtube_account(config, scope_user_id, target)
    _save_config(config)
    return {
        "connected": True,
        "authorized_at": target["youtube_oauth"]["authorized_at"],
        "scope": "shared" if scope_user_id is None else "user",
        "scope_owner_id": scope_user_id,
    }


def build_callback_html(success: bool, message: str, origin: str) -> str:
    payload = json.dumps(
        {
            "type": "shortmaker-youtube-auth",
            "success": bool(success),
            "message": message,
        }
    )
    title = "YouTube Connected" if success else "YouTube Connection Failed"
    status = "success" if success else "error"
    safe_origin = json.dumps(origin)
    safe_message = escape(message)
    safe_title = escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      display: grid;
      place-items: center;
      min-height: 100vh;
    }}
    .card {{
      max-width: 420px;
      padding: 24px;
      border-radius: 18px;
      background: rgba(15, 23, 42, 0.92);
      border: 1px solid rgba(148, 163, 184, 0.25);
      text-align: center;
      box-shadow: 0 18px 55px rgba(15, 23, 42, 0.35);
    }}
    .status {{
      font-size: 0.78rem;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: {"#34d399" if success else "#fca5a5"};
      margin-bottom: 14px;
      font-weight: 700;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 1.35rem;
    }}
    p {{
      margin: 0;
      line-height: 1.55;
      color: #cbd5e1;
    }}
  </style>
</head>
<body>
  <main class="card">
    <div class="status">{status}</div>
    <h1>{safe_title}</h1>
    <p>{safe_message}</p>
  </main>
  <script>
    const payload = {payload};
    if (window.opener && !window.opener.closed) {{
      const configuredOrigin = {safe_origin};
      const candidateOrigins = Array.from(new Set([
        configuredOrigin,
        window.location.origin,
        configuredOrigin.includes('://localhost') ? configuredOrigin.replace('://localhost', '://127.0.0.1') : '',
        configuredOrigin.includes('://127.0.0.1') ? configuredOrigin.replace('://127.0.0.1', '://localhost') : '',
      ].filter(Boolean)));
      for (const targetOrigin of candidateOrigins) {{
        try {{
          window.opener.postMessage(payload, targetOrigin);
        }} catch (error) {{
          console.warn('Unable to post YouTube auth result to opener', targetOrigin, error);
        }}
      }}
    }}
    setTimeout(() => window.close(), 1200);
  </script>
</body>
</html>"""


def _build_credentials(user_id: Optional[str] = None):
    Credentials = _require_google_dependency("google.oauth2.credentials").Credentials

    config = _load_config()
    record = _get_user_youtube_account(config, user_id, create=False) if user_id else config
    allow_env_fallback = not user_id or not _user_has_personal_client_config(record)
    client_id = _client_id_from_config(record, allow_env_fallback=allow_env_fallback)
    client_secret = _client_secret_from_config(record, allow_env_fallback=allow_env_fallback)
    oauth = _oauth_record_from_config(record)
    refresh_token = str(oauth.get("refresh_token") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("YouTube OAuth client settings are missing.")
    if not refresh_token:
        raise ValueError("No YouTube account is connected yet.")

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=str(oauth.get("token_uri") or GOOGLE_TOKEN_URI),
        client_id=client_id,
        client_secret=client_secret,
        scopes=list(oauth.get("scopes") or [YOUTUBE_UPLOAD_SCOPE]),
    )


def _sanitize_title(title: Optional[str], filename: str) -> str:
    value = str(title or Path(filename).stem).strip() or "Short clip"
    if "#shorts" not in value.lower():
        suffix = " #Shorts"
        if len(value) + len(suffix) <= 100:
            value = f"{value}{suffix}"
        else:
            value = f"{value[:100 - len(suffix)].rstrip()}{suffix}"
    return value[:100]


def _sanitize_description(description: Optional[str], tags: List[str]) -> str:
    base = str(description or "").strip()
    if "#shorts" not in base.lower():
        suffix = " #Shorts"
        if len(base) + len(suffix) <= 5000:
            base = f"{base}{suffix}".strip()
    return base[:5000]


def _sanitize_tags(tags: Optional[List[str]]) -> List[str]:
    cleaned: List[str] = []
    lowered: set[str] = set()
    for tag in tags or []:
        value = str(tag or "").strip().lstrip("#")
        if not value:
            continue
        normalized = value[:30]
        normalized_lower = normalized.lower()
        if normalized_lower not in lowered:
            cleaned.append(normalized)
            lowered.add(normalized_lower)
        if len(cleaned) >= 15:
            break
    if "shorts" not in lowered and len(cleaned) < 15:
        cleaned.append("Shorts")
    return cleaned


def upload_short(
    *,
    file_path: str,
    title: Optional[str],
    description: Optional[str],
    tags: Optional[List[str]],
    privacy_status: Optional[str],
    category_id: str = DEFAULT_CATEGORY_ID,
    user_id: Optional[str] = None,
) -> dict:
    build = _require_google_dependency("googleapiclient.discovery").build
    HttpError = _require_google_dependency("googleapiclient.errors").HttpError
    MediaFileUpload = _require_google_dependency("googleapiclient.http").MediaFileUpload

    resolved_path = Path(file_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Short not found: {resolved_path.name}")

    credentials = _build_credentials(user_id=user_id)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)

    snippet = {
        "title": _sanitize_title(title, resolved_path.name),
        "description": _sanitize_description(description, _sanitize_tags(tags)),
        "categoryId": str(category_id or DEFAULT_CATEGORY_ID),
    }
    sanitized_tags = _sanitize_tags(tags)
    if sanitized_tags:
        snippet["tags"] = sanitized_tags

    body = {
        "snippet": snippet,
        "status": {
            "privacyStatus": _normalize_privacy_status(privacy_status),
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(resolved_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    try:
        response = None
        while response is None:
            _, response = request.next_chunk()
    except HttpError as exc:
        try:
            error_text = exc.content.decode("utf-8")
        except Exception:
            error_text = str(exc)
        logger.error("YouTube upload failed: %s", error_text)
        raise HTTPException(status_code=502, detail=f"YouTube upload failed: {error_text}")

    video_id = str((response or {}).get("id") or "").strip()
    if not video_id:
        raise HTTPException(status_code=502, detail="YouTube upload did not return a video ID.")

    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "privacy_status": body["status"]["privacyStatus"],
        "title": snippet["title"],
    }
