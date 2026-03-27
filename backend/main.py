"""
main.py - FastAPI application for ShortMaker

Endpoints:
- POST /process - Start video processing
- GET /status/{job_id} - Get processing status
- GET /shorts/{filename} - Download generated shorts
- POST /ai/config - Configure AI settings
- GET /ai/config - Get AI configuration
- POST /ai/validate - Validate API key
"""

import os
import uuid
import json
import traceback
import secrets
import base64
import hashlib
import ipaddress
import socket
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    File,
    Form,
    Header,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import threading
import logging
from urllib.parse import urlparse
from utils.env_loader import load_dotenv_file
from utils.secret_store import SHORTMAKER_SECRET_KEY_ENV, has_secret_storage_key
from .clerk_auth import ClerkUser, require_clerk_user
from .db import (
    create_job_record,
    database_enabled,
    get_daily_usage,
    get_job_ids_for_user,
    get_job_owner,
    init_database,
    result_file_belongs_to_user,
    sync_job_status,
    upsert_user,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ========================================
# Configuration
# ========================================

BASE_DIR = Path(__file__).parent.parent
load_dotenv_file(BASE_DIR / ".env")
OUTPUT_DIR = BASE_DIR / "outputs"
FRONTEND_DIR = BASE_DIR / "frontend"
MAIN_FILE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIST_DIR = os.path.abspath(os.path.join(MAIN_FILE_DIR, "..", "frontend", "dist"))
WEB_DIST_ASSETS_DIR = os.path.join(WEB_DIST_DIR, "assets")
WEB_DIST_INDEX_FILE = os.path.join(WEB_DIST_DIR, "index.html")
SHORTS_DIR = OUTPUT_DIR / "shorts"
JOBS_DIR = OUTPUT_DIR / "jobs"
UPLOAD_DIR = OUTPUT_DIR / "uploads"
ADMIN_ROUTE_PREFIX = "/ashmil2010"
ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".mpg",
    ".mpeg",
    ".flv",
    ".wmv",
}
MAX_CLIPS = 10
SHORTS_MAX_DURATION_SECONDS = 59.0
RECENT_JOB_LIMIT = 12
DEFAULT_UPLOAD_CALLBACK_TIMEOUT_SECONDS = 30
DEFAULT_API_KEY_LENGTH = 44
DEFAULT_YOUTUBE_OAUTH_CALLBACK_URI = "http://127.0.0.1:8000/youtube/oauth/callback"
DEFAULT_YOUTUBE_OAUTH_CALLBACK_PATH = "/youtube/oauth/callback"
DAILY_PROCESS_LIMIT = 3
ADMIN_API_TOKEN_ENV = "SHORTMAKER_ADMIN_TOKEN"
AUTH_MODE_ENV = "SHORTMAKER_AUTH_MODE"
YOUTUBE_OAUTH_BASE_URL_ENV = "SHORTMAKER_YOUTUBE_OAUTH_BASE_URL"
YOUTUBE_OAUTH_CALLBACK_URI_ENV = "SHORTMAKER_YOUTUBE_OAUTH_CALLBACK_URI"
APP_ENV_ENV = "SHORTMAKER_ENV"
PUBLIC_DOCS_ENV = "SHORTMAKER_PUBLIC_DOCS"
ALLOWED_ORIGINS_ENV = "SHORTMAKER_ALLOWED_ORIGINS"
ALLOWED_HOSTS_ENV = "SHORTMAKER_ALLOWED_HOSTS"
ALLOWED_CALLBACK_HOSTS_ENV = "SHORTMAKER_ALLOWED_CALLBACK_HOSTS"
ALLOW_PRIVATE_CALLBACKS_ENV = "SHORTMAKER_ALLOW_PRIVATE_CALLBACKS"
AUTH_MODE_KEY = "auth_mode"
AUTH_MODE_QUICK = "quick"
AUTH_MODE_PRODUCTION = "production"
YOUTUBE_HOST_SUFFIXES = ("youtube.com", "youtu.be", "youtube-nocookie.com")
TERMINAL_JOB_STAGES = {"complete", "error"}

# Ensure directories exist
OUTPUT_DIR.mkdir(exist_ok=True)
SHORTS_DIR.mkdir(exist_ok=True)
JOBS_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)


# ========================================
# FastAPI App
# ========================================


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _build_trusted_hosts(hosts: list[str]) -> list[str]:
    normalized = [item for item in hosts if item]
    if "*.onrender.com" not in normalized:
        normalized.append("*.onrender.com")
    return normalized


IS_PRODUCTION = os.environ.get(APP_ENV_ENV, "").strip().lower() == "production"
PUBLIC_DOCS_ENABLED = os.environ.get(PUBLIC_DOCS_ENV, "").strip().lower() in {
    "1",
    "true",
    "yes",
}
DEFAULT_ALLOWED_ORIGINS = "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173"
DEFAULT_ALLOWED_HOSTS = "127.0.0.1,localhost"
ALLOWED_ORIGINS = _env_csv(ALLOWED_ORIGINS_ENV, DEFAULT_ALLOWED_ORIGINS)
ALLOWED_HOSTS = _env_csv(ALLOWED_HOSTS_ENV, DEFAULT_ALLOWED_HOSTS)

app = FastAPI(
    title="ShortMaker",
    description="Convert long-form videos into short vertical clips with AI",
    version="3.0.0",
    docs_url=None if IS_PRODUCTION and not PUBLIC_DOCS_ENABLED else "/docs",
    redoc_url=None if IS_PRODUCTION and not PUBLIC_DOCS_ENABLED else "/redoc",
    openapi_url=None if IS_PRODUCTION and not PUBLIC_DOCS_ENABLED else "/openapi.json",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Token", "X-API-Key"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_build_trusted_hosts(ALLOWED_HOSTS or ["127.0.0.1", "localhost"]),
)


# ========================================
# Request/Response Models
# ========================================


class ProcessRequest(BaseModel):
    url: str
    num_clips: int = 10
    callback_url: Optional[str] = None
    callback_token: Optional[str] = None
    callback_auth_header: str = "X-Callback-Token"
    public_base_url: Optional[str] = None
    callback_timeout_seconds: int = DEFAULT_UPLOAD_CALLBACK_TIMEOUT_SECONDS


class ProcessResponse(BaseModel):
    job_id: str
    message: str


class StatusResponse(BaseModel):
    stage: str
    progress: int
    message: str
    error: Optional[str] = None
    results: list = []
    ai_highlights: list = []


class UsageResponse(BaseModel):
    limit: int
    used: int
    remaining: int
    reset_basis: str = "utc_day"


class SessionResponse(BaseModel):
    user_id: str
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    image_url: str = ""
    is_admin: bool = False
    usage: UsageResponse


class AIConfigRequest(BaseModel):
    gemini_api_key: str = ""
    groq_api_key: str = ""
    firecrawl_api_key: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    ytdlp_cookies: str = ""
    ytdlp_cookie_auto_sync_enabled: Optional[bool] = None
    ytdlp_cookie_auto_sync_browser: Optional[str] = None
    ytdlp_cookie_auto_sync_interval_hours: Optional[int] = None
    ytdlp_cookie_auto_sync_on_sign_in: Optional[bool] = None
    youtube_default_privacy: str = "private"
    ai_enabled: bool = True
    model: str = "gemini-2.5-flash"


class AIConfigResponse(BaseModel):
    ai_enabled: bool
    has_api_key: bool
    model: str
    message: str


class AIValidateRequest(BaseModel):
    api_key: str


class AuthModeRequest(BaseModel):
    mode: str = AUTH_MODE_QUICK


class AuthModeResponse(BaseModel):
    mode: str
    requires_api_key: bool
    api_key_count: int
    admin_token_configured: bool


class TrendDiscoverRequest(BaseModel):
    topic: str
    location: str = "India"
    limit: int = 6


class TrendAutoProcessRequest(BaseModel):
    topic: str
    location: str = "India"
    limit: int = 6
    num_clips: int = 3


class YouTubeUploadRequest(BaseModel):
    filename: str
    title: str = ""
    description: str = ""
    tags: List[str] = []
    privacy_status: str = "private"


class YouTubeUploadBatchRequest(BaseModel):
    uploads: List[YouTubeUploadRequest]


class YouTubeConfigRequest(BaseModel):
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_default_privacy: str = "private"


class YouTubeCookieSyncRequest(BaseModel):
    reason: str = "manual"


def validate_num_clips(num_clips: int) -> int:
    """Normalize and validate requested number of clips."""
    if num_clips < 1 or num_clips > MAX_CLIPS:
        raise HTTPException(
            status_code=400, detail=f"num_clips must be between 1 and {MAX_CLIPS}"
        )
    return num_clips


def _read_app_config() -> dict:
    """Load shared config used by AI and API key settings."""
    from .ai_engine import load_config

    return load_config()


def _write_app_config(update: Dict[str, Any]):
    """Persist partial config while preserving existing keys."""
    from .ai_engine import load_config, save_config

    config = load_config()
    config.update(update)
    save_config(config)


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _list_api_keys() -> list[dict]:
    config = _read_app_config()
    keys = config.get("api_keys", [])
    if not isinstance(keys, list):
        return []
    normalized = []
    for item in keys:
        if isinstance(item, dict) and item.get("hash"):
            normalized.append(item)
    return normalized


def _get_auth_mode() -> str:
    env_mode = os.environ.get(AUTH_MODE_ENV, "").strip().lower()
    if env_mode in {AUTH_MODE_QUICK, AUTH_MODE_PRODUCTION}:
        return env_mode

    config = _read_app_config()
    mode = config.get(AUTH_MODE_KEY, AUTH_MODE_QUICK)
    if mode not in {AUTH_MODE_QUICK, AUTH_MODE_PRODUCTION}:
        return AUTH_MODE_QUICK
    return mode


def _set_auth_mode(mode: str):
    normalized = mode.strip().lower()
    if normalized not in {AUTH_MODE_QUICK, AUTH_MODE_PRODUCTION}:
        raise ValueError("mode must be 'quick' or 'production'")
    _write_app_config({AUTH_MODE_KEY: normalized})


def _is_api_auth_required() -> bool:
    if _get_auth_mode() == AUTH_MODE_PRODUCTION:
        return True
    return len(_list_api_keys()) > 0


async def _require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    if not _is_api_auth_required():
        return

    token = x_api_key
    if token and token.startswith("Bearer "):
        token = token[7:]
    elif not token and authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization

    if not token:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    token_hash = _hash_api_key(token)
    keys = _list_api_keys()
    for item in keys:
        if secrets.compare_digest(item.get("hash", ""), token_hash):
            item["last_used_at"] = datetime.now(timezone.utc).isoformat()
            _write_app_config({"api_keys": keys})
            return

    raise HTTPException(status_code=403, detail="Invalid API key")


def _get_admin_token() -> str:
    return os.environ.get(ADMIN_API_TOKEN_ENV, "").strip()


async def _require_admin_token(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
):
    expected = _get_admin_token()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="Set SHORTMAKER_ADMIN_TOKEN before using admin routes.",
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="Invalid admin token")


async def _require_app_user(user: ClerkUser = Depends(require_clerk_user)) -> ClerkUser:
    return _register_user(user)


def _register_user(user: ClerkUser) -> ClerkUser:
    upsert_user(
        {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "image_url": user.image_url,
        }
    )
    return user


def _split_csv_env(name: str) -> set[str]:
    return {
        item.strip() for item in os.environ.get(name, "").split(",") if item.strip()
    }


def _is_admin_user(user: ClerkUser) -> bool:
    allowed_ids = _split_csv_env("SHORTMAKER_ADMIN_USER_IDS")
    allowed_emails = {
        item.lower() for item in _split_csv_env("SHORTMAKER_ADMIN_EMAILS")
    }
    if not allowed_ids and not allowed_emails:
        return False
    if user.id in allowed_ids:
        return True
    if user.email and user.email.lower() in allowed_emails:
        return True
    return False


def _youtube_scope_user_id(user: ClerkUser) -> Optional[str]:
    if _is_admin_console_user(user) or _is_admin_user(user):
        return None
    return user.id


async def _require_admin_user(
    user: ClerkUser = Depends(_require_app_user),
) -> ClerkUser:
    if _is_admin_user(user):
        return user
    raise HTTPException(
        status_code=403, detail="You do not have access to the admin console."
    )


def _admin_console_user() -> ClerkUser:
    return ClerkUser(
        id="admin-console",
        email="admin@shortmaker.local",
        first_name="Admin",
        last_name="Console",
        image_url="",
        claims={"role": "admin-console"},
    )


def _automation_api_user() -> ClerkUser:
    return ClerkUser(
        id="api-automation",
        email="automation@shortmaker.local",
        first_name="API",
        last_name="Automation",
        image_url="",
        claims={"role": "api-automation"},
    )


def _is_admin_console_user(user: Optional[ClerkUser]) -> bool:
    return bool(user and user.id == "admin-console")


def _is_automation_api_user(user: Optional[ClerkUser]) -> bool:
    return bool(user and user.id == "api-automation")


async def _require_app_user_or_api_key(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ClerkUser:
    raw_authorization = (authorization or "").strip()

    if x_api_key:
        await _require_api_key(x_api_key=x_api_key, authorization=authorization)
        return _register_user(_automation_api_user())

    if raw_authorization:
        token = (
            raw_authorization[7:].strip()
            if raw_authorization.lower().startswith("bearer ")
            else raw_authorization
        )
        if token.count(".") == 2:
            return _register_user(await require_clerk_user(authorization))
        await _require_api_key(x_api_key=x_api_key, authorization=authorization)
        return _register_user(_automation_api_user())

    if _is_api_auth_required():
        raise HTTPException(
            status_code=401,
            detail="Missing authentication. Provide a Clerk bearer token or X-API-Key.",
        )

    return _register_user(_automation_api_user())


def _owner_id_from_status(status: dict) -> str:
    return str(status.get("owner_id") or "").strip()


def _assert_job_ownership(job_id: str, status: dict, user: ClerkUser):
    owner_id = _owner_id_from_status(status)
    if owner_id and owner_id == user.id:
        return

    if database_enabled():
        persisted_owner = get_job_owner(job_id)
        if persisted_owner and persisted_owner == user.id:
            return

    raise HTTPException(status_code=404, detail="Job not found.")


def _assert_daily_quota(user: ClerkUser):
    usage = get_daily_usage(user.id, limit=DAILY_PROCESS_LIMIT)
    if usage["remaining"] <= 0:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily processing limit reached. Each account can process up to "
                f"{DAILY_PROCESS_LIMIT} URLs or uploads per UTC day."
            ),
        )


def _mask_api_key(api_key: str) -> str:
    if len(api_key) <= 12:
        return "***"
    return f"{api_key[:8]}...{api_key[-4:]}"


def _assert_secret_storage_ready(*values: str):
    if (
        any(str(value or "").strip() for value in values)
        and not has_secret_storage_key()
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Secret persistence is disabled. Set {SHORTMAKER_SECRET_KEY_ENV} "
                "or configure the secret directly via environment variables."
            ),
        )


def _normalize_callback_timeout(timeout_seconds: int) -> int:
    if timeout_seconds <= 0:
        return 5
    return min(120, timeout_seconds)


def _is_public_ip(value: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    )


def _callback_host_allowed(hostname: str) -> bool:
    allowed_hosts = {
        item.lower() for item in _split_csv_env(ALLOWED_CALLBACK_HOSTS_ENV)
    }
    if not allowed_hosts:
        return False
    normalized = (hostname or "").strip().lower()
    if not normalized:
        return False
    for allowed_host in allowed_hosts:
        if normalized == allowed_host:
            return True
        if allowed_host.startswith("*."):
            suffix = allowed_host[2:]
            if suffix and (normalized == suffix or normalized.endswith(f".{suffix}")):
                return True
        if allowed_host.startswith("."):
            suffix = allowed_host[1:]
            if suffix and (normalized == suffix or normalized.endswith(f".{suffix}")):
                return True
    return False


def _allow_private_callbacks() -> bool:
    return not IS_PRODUCTION and _env_flag(ALLOW_PRIVATE_CALLBACKS_ENV)


def _safe_filename(filename: str) -> str:
    return Path(filename or "").name


def _is_supported_youtube_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in YOUTUBE_HOST_SUFFIXES
    )


def _validate_callback_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400, detail="callback_url must be http or https"
        )
    if not parsed.hostname:
        raise HTTPException(
            status_code=400, detail="callback_url must include a hostname"
        )
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400, detail="callback_url must not contain embedded credentials"
        )
    if not _callback_host_allowed(parsed.hostname):
        raise HTTPException(
            status_code=400, detail="callback_url host is not allowlisted"
        )
    if _is_public_ip(parsed.hostname):
        return
    try:
        resolved_hosts = socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400, detail=f"callback_url host could not be resolved: {exc}"
        ) from exc
    resolved_ips = {entry[4][0] for entry in resolved_hosts if entry and entry[4]}
    if not resolved_ips:
        raise HTTPException(
            status_code=400, detail="callback_url host could not be resolved"
        )
    if _allow_private_callbacks():
        return
    if not all(_is_public_ip(ip) for ip in resolved_ips):
        raise HTTPException(
            status_code=400,
            detail="callback_url must resolve only to public IP addresses",
        )


def _build_result_payload(
    job_id: str, status: dict, public_base_url: Optional[str] = None
):
    results = status.get("results", []) or []
    base = (public_base_url or "").rstrip("/")
    short_urls = [f"{base}/shorts/{name}" for name in results] if base else []
    stage = status.get("stage") or status.get("status") or "unknown"
    ai_highlights = status.get("ai_highlights", []) or []

    return {
        "job_id": job_id,
        "stage": stage,
        "status": stage,
        "message": status.get("message", ""),
        "error": status.get("error"),
        "results": results,
        "shorts": results,
        "short_urls": short_urls,
        "progress": status.get("progress", 0),
        "ai_highlights": ai_highlights,
        "video_title": status.get("video_title", ""),
        "source_type": status.get("source_type", ""),
        "input_name": status.get("input_name", ""),
        "num_clips": status.get("num_clips", 0),
        "video_duration": status.get("video_duration", 0),
        "created_at": status.get("created_at"),
        "updated_at": status.get("updated_at"),
        "has_ai_data": any(
            item.get("virality_score") or item.get("title") or item.get("hook_caption")
            for item in ai_highlights
            if isinstance(item, dict)
        ),
    }


def _derive_clip_title(highlight: dict, index: int) -> str:
    raw_value = (
        highlight.get("title")
        or highlight.get("trendy_caption")
        or highlight.get("hook_caption")
        or highlight.get("text")
        or f"Short #{index}"
    )
    title = " ".join(str(raw_value).replace("\n", " ").split()).strip(" .-")
    return (title or f"Short #{index}")[:80]


def _clamp_highlights_to_short_duration(
    highlights: list[dict], video_duration: float
) -> list[dict]:
    normalized: list[dict] = []
    for highlight in highlights or []:
        if not isinstance(highlight, dict):
            continue
        start = max(0.0, float(highlight.get("start", 0) or 0))
        end = min(
            float(highlight.get("end", start) or start), float(video_duration or 0)
        )
        if end <= start:
            continue
        if end - start > SHORTS_MAX_DURATION_SECONDS:
            end = min(start + SHORTS_MAX_DURATION_SECONDS, float(video_duration or end))
        if end <= start:
            continue
        updated = dict(highlight)
        updated["start"] = round(start, 3)
        updated["end"] = round(end, 3)
        normalized.append(updated)
    return normalized


def _build_highlights_info(status: dict) -> list[dict]:
    highlights = status.get("ai_highlights", []) or []
    if not isinstance(highlights, list):
        return []

    normalized: list[dict] = []
    for index, highlight in enumerate(highlights, start=1):
        if not isinstance(highlight, dict):
            continue
        start = float(highlight.get("start", 0) or 0)
        end = float(highlight.get("end", 0) or 0)
        normalized.append(
            {
                "index": index,
                "filename": highlight.get("filename", ""),
                "title": _derive_clip_title(highlight, index),
                "start": start,
                "end": end,
                "duration": round(max(0.0, end - start), 2),
                "reason": highlight.get("reason", "highlight"),
                "virality_score": highlight.get("virality_score", 0),
                "trendy_caption": highlight.get("trendy_caption", ""),
                "hook_caption": highlight.get("hook_caption", ""),
                "hashtags": highlight.get("hashtags", []),
            }
        )
    return normalized


def _send_callback(job_id: str, status: dict, callback_info: dict):
    import urllib.request

    callback_url = callback_info.get("callback_url")
    if not callback_url:
        return

    timeout_seconds = callback_info.get(
        "callback_timeout_seconds", DEFAULT_UPLOAD_CALLBACK_TIMEOUT_SECONDS
    )
    if not isinstance(timeout_seconds, (int, float)):
        timeout_seconds = DEFAULT_UPLOAD_CALLBACK_TIMEOUT_SECONDS

    payload = _build_result_payload(
        job_id, status, public_base_url=callback_info.get("public_base_url")
    )
    payload.update(
        {
            "event": "completed" if payload["status"] == "complete" else "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "success": payload["status"] == "complete",
        }
    )

    headers = {"Content-Type": "application/json"}
    auth_header = (
        callback_info.get("callback_auth_header") or "X-Callback-Token"
    ).strip()
    callback_token = callback_info.get("callback_token")
    if callback_token:
        headers[auth_header or "X-Callback-Token"] = callback_token

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        callback_url, data=body, headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=int(timeout_seconds)) as response:
            logger.info(f"[callback] Job {job_id[:8]} sent, status={response.status}")
    except Exception as e:
        logger.warning(f"[callback] Job {job_id[:8]} failed: {e}")


# ========================================
# Persistent Job Storage (File-based for stability)
# ========================================


def save_job_status(job_id: str, status_data: dict):
    """Save job status to file for persistence across restarts."""
    try:
        job_file = JOBS_DIR / f"{job_id}.json"
        with open(job_file, "w") as f:
            json.dump(status_data, f)
    except Exception as e:
        logger.error(f"Failed to save job status: {e}")


def load_job_status(job_id: str) -> Optional[dict]:
    """Load job status from file."""
    try:
        job_file = JOBS_DIR / f"{job_id}.json"
        if job_file.exists():
            with open(job_file, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load job status: {e}")
    return None


def _is_terminal_job_stage(stage: Optional[str]) -> bool:
    return (stage or "").strip().lower() in TERMINAL_JOB_STAGES


def _mark_job_interrupted(job_id: str, status_data: dict, reason: str):
    """Convert an in-flight persisted job into an explicit error state."""
    stage = (
        (status_data.get("stage") or status_data.get("status") or "").strip().lower()
    )
    if _is_terminal_job_stage(stage):
        return

    timestamp = datetime.now(timezone.utc).isoformat()
    interrupted_status = {
        **status_data,
        "stage": "error",
        "status": "error",
        "message": reason,
        "error": "job_interrupted_by_server_restart",
        "updated_at": timestamp,
        "interrupted_at": timestamp,
        "interrupted_stage": stage or "unknown",
        "interrupted_progress": status_data.get("progress", 0),
    }
    save_job_status(job_id, interrupted_status)
    logger.warning(
        f"[{job_id[:8]}] marked interrupted after restart (was {stage or 'unknown'})"
    )


def recover_incomplete_jobs():
    """Mark any persisted in-flight jobs as interrupted after a server restart."""
    if not JOBS_DIR.exists():
        return

    reason = "Server restarted while this job was running. Start the job again."
    for job_file in JOBS_DIR.glob("*.json"):
        status = load_job_status(job_file.stem)
        if not status:
            continue
        _mark_job_interrupted(job_file.stem, status, reason)


def update_job_status(
    job_id: str,
    stage: str,
    progress: int,
    message: str,
    error: Optional[str] = None,
    results: list = None,
    ai_highlights: list = None,
    metadata: Optional[dict] = None,
):
    """Update and persist job status."""
    previous = load_job_status(job_id) or {}
    status_data = {
        **previous,
        "stage": stage,
        "status": stage,
        "progress": progress,
        "message": message,
        "error": error,
        "results": results if results is not None else previous.get("results", []),
        "ai_highlights": ai_highlights
        if ai_highlights is not None
        else previous.get("ai_highlights", []),
        "created_at": previous.get("created_at")
        or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        for key, value in metadata.items():
            if value is not None:
                status_data[key] = value
    save_job_status(job_id, status_data)
    sync_job_status(job_id, status_data)
    logger.info(f"[{job_id[:8]}] [{stage}] {progress}% - {message}")


@app.on_event("startup")
async def _recover_interrupted_jobs_on_startup():
    from .ytdlp_cookie_sync import ensure_cookie_auto_sync_worker_started

    if not os.environ.get("CLERK_ISSUER", "").strip():
        logger.warning(
            "CLERK_ISSUER is not configured. Authenticated routes will reject requests."
        )
    if not _split_csv_env("SHORTMAKER_ADMIN_USER_IDS") and not _split_csv_env(
        "SHORTMAKER_ADMIN_EMAILS"
    ):
        logger.warning(
            "No admin allowlist configured. Admin routes are disabled until SHORTMAKER_ADMIN_USER_IDS or SHORTMAKER_ADMIN_EMAILS is set."
        )
    init_database()
    recover_incomplete_jobs()
    ensure_cookie_auto_sync_worker_started()


def list_recent_jobs(
    limit: int = RECENT_JOB_LIMIT,
    public_base_url: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Return the most recent persisted jobs."""
    jobs: list[dict] = []
    job_ids: list[str] = []

    if owner_id and database_enabled():
        job_ids = get_job_ids_for_user(owner_id, limit=max(1, limit))
    elif JOBS_DIR.exists():
        files = sorted(
            JOBS_DIR.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        job_ids = [path.stem for path in files[: max(1, limit)]]

    for job_id in job_ids:
        status = load_job_status(job_id)
        if not status:
            continue
        if (
            owner_id
            and _owner_id_from_status(status)
            and _owner_id_from_status(status) != owner_id
        ):
            continue
        jobs.append(
            _build_result_payload(job_id, status, public_base_url=public_base_url)
        )
    return jobs


def _build_callback_config(
    callback_url: Optional[str],
    callback_token: Optional[str],
    callback_auth_header: str,
    callback_timeout_seconds: int,
) -> Optional[dict]:
    if not callback_url:
        return None

    _validate_callback_url(callback_url)
    return {
        "callback_url": callback_url,
        "callback_token": callback_token,
        "callback_auth_header": callback_auth_header,
        "callback_timeout_seconds": _normalize_callback_timeout(
            callback_timeout_seconds
        ),
    }


def _resolve_public_base_url(request: Request, route_prefix: str = "") -> str:
    base_url = str(request.base_url).rstrip("/")
    prefix = route_prefix.rstrip("/")
    return f"{base_url}{prefix}" if prefix else base_url


def _normalize_oauth_origin(candidate: str) -> str:
    parsed = urlparse((candidate or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    hostname = parsed.hostname or ""
    port = parsed.port
    if hostname in {"127.0.0.1", "0.0.0.0", "::1"}:
        hostname = "localhost"
    netloc = hostname
    if port:
        netloc = f"{hostname}:{port}"
    return f"{parsed.scheme}://{netloc}".rstrip("/")


def _normalize_oauth_callback_uri(candidate: str) -> str:
    parsed = urlparse((candidate or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    if parsed.path:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _resolve_youtube_oauth_origin(request: Request) -> str:
    configured = _normalize_oauth_origin(os.environ.get(YOUTUBE_OAUTH_BASE_URL_ENV, ""))
    if configured:
        return configured
    return _normalize_oauth_origin(str(request.base_url)) or str(
        request.base_url
    ).rstrip("/")


def _prefer_loopback_redirect_origin(origin: str) -> str:
    parsed = urlparse(origin)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return origin

    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://127.0.0.1{port}"


def _build_youtube_redirect_uri(request: Request) -> str:
    origin = _resolve_youtube_oauth_origin(request)
    redirect_origin = _prefer_loopback_redirect_origin(origin)
    configured_callback = _normalize_oauth_callback_uri(
        os.environ.get(YOUTUBE_OAUTH_CALLBACK_URI_ENV, "")
    )
    if configured_callback:
        return configured_callback

    normalized_relative = (
        os.environ.get("SHORTMAKER_YOUTUBE_OAUTH_CALLBACK_PATH", "") or ""
    ).strip()
    if normalized_relative:
        if normalized_relative.startswith("/"):
            return f"{redirect_origin}{normalized_relative}"
        return f"{redirect_origin}/{normalized_relative.lstrip('/')}"

    return f"{redirect_origin}{DEFAULT_YOUTUBE_OAUTH_CALLBACK_PATH}"


def _queue_youtube_job(request: ProcessRequest, user: ClerkUser) -> ProcessResponse:
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not _is_supported_youtube_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    user = _register_user(user)

    num_clips = validate_num_clips(request.num_clips)
    callback_config = _build_callback_config(
        callback_url=request.callback_url,
        callback_token=request.callback_token,
        callback_auth_header=request.callback_auth_header,
        callback_timeout_seconds=request.callback_timeout_seconds,
    )

    job_id = str(uuid.uuid4())
    update_job_status(
        job_id,
        "queued",
        0,
        "Job queued for processing",
        metadata={
            "owner_id": user.id,
            "owner_email": user.email,
            "source_type": "youtube",
            "input_name": request.url,
            "num_clips": num_clips,
        },
    )
    create_job_record(
        job_id=job_id,
        clerk_user_id=user.id,
        source_type="youtube",
        input_name=request.url,
        num_clips=num_clips,
        stage="queued",
        progress=0,
        message="Job queued for processing",
    )

    thread = threading.Thread(
        target=run_processing_job,
        args=(job_id, request.url, num_clips),
        kwargs={
            "callback_config": callback_config,
            "public_base_url": request.public_base_url,
        },
        daemon=True,
    )
    thread.start()

    return ProcessResponse(job_id=job_id, message="Processing started")


async def _queue_upload_job(
    file: UploadFile,
    num_clips: int,
    callback_url: Optional[str],
    callback_token: Optional[str],
    callback_auth_header: str,
    public_base_url: Optional[str],
    callback_timeout_seconds: int,
    user: ClerkUser,
) -> ProcessResponse:
    num_clips = validate_num_clips(num_clips)
    user = _register_user(user)

    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")

    ext = Path(file.filename).suffix.lower()
    if ext and ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Upload mp4/mov/mkv/webm/avi/flv/wmv.",
        )

    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = str(job_dir / f"source{ext or '.mp4'}")

    try:
        with open(source_path, "wb") as fp:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                fp.write(chunk)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to store uploaded file: {str(exc)}"
        )
    finally:
        await file.close()

    callback_config = _build_callback_config(
        callback_url=callback_url,
        callback_token=callback_token,
        callback_auth_header=callback_auth_header,
        callback_timeout_seconds=callback_timeout_seconds,
    )

    update_job_status(
        job_id,
        "queued",
        0,
        "Job queued for processing uploaded video",
        metadata={
            "owner_id": user.id,
            "owner_email": user.email,
            "source_type": "upload",
            "input_name": file.filename,
            "num_clips": num_clips,
        },
    )
    create_job_record(
        job_id=job_id,
        clerk_user_id=user.id,
        source_type="upload",
        input_name=file.filename,
        num_clips=num_clips,
        stage="queued",
        progress=0,
        message="Job queued for processing uploaded video",
    )

    thread = threading.Thread(
        target=run_processing_job,
        args=(job_id, source_path, num_clips),
        kwargs={
            "source_type": "upload",
            "original_filename": file.filename,
            "callback_config": callback_config,
            "public_base_url": public_base_url,
        },
        daemon=True,
    )
    thread.start()

    return ProcessResponse(job_id=job_id, message="Upload processing started")


def _get_job_payload(
    job_id: str, public_base_url: Optional[str] = None, user: Optional[ClerkUser] = None
) -> dict:
    status = load_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if user:
        _assert_job_ownership(job_id, status, user)
    return _build_result_payload(job_id, status, public_base_url=public_base_url)


def _get_completed_result_payload(
    job_id: str, public_base_url: str, user: Optional[ClerkUser] = None
) -> dict:
    status = load_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if user:
        _assert_job_ownership(job_id, status, user)
    if status.get("stage") != "complete":
        raise HTTPException(
            status_code=400,
            detail=f"Job not complete. Current stage: {status.get('stage')}",
        )

    payload = _build_result_payload(job_id, status, public_base_url=public_base_url)
    payload["success"] = True
    payload["highlights_info"] = _build_highlights_info(status)
    return payload


def _build_capabilities_payload(
    *, require_api_key: bool, admin_console: bool = False
) -> dict:
    from .ai_engine import load_config, get_api_key
    from .trends import has_firecrawl_config
    from .youtube_publish import has_youtube_client_config, has_youtube_connection

    config = load_config()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    effective_gemini = gemini_key if admin_console else (gemini_key or get_api_key())
    effective_groq = (
        groq_key if admin_console else (groq_key or config.get("groq_api_key", ""))
    )
    effective_firecrawl = (
        firecrawl_key
        if admin_console
        else (firecrawl_key or config.get("firecrawl_api_key", ""))
    )

    return {
        "max_clips": MAX_CLIPS,
        "daily_process_limit": DAILY_PROCESS_LIMIT,
        "supports_uploads": True,
        "supports_trend_discovery": bool(has_firecrawl_config()),
        "supports_youtube_publish": True,
        "allowed_video_extensions": sorted(ALLOWED_VIDEO_EXTENSIONS),
        "requires_api_key": require_api_key,
        "requires_authentication": not admin_console,
        "auth_mode": "admin" if admin_console else _get_auth_mode(),
        "api_key_count": len(_list_api_keys()),
        "admin_token_configured": bool(_get_admin_token()),
        "ai_enabled": bool(effective_gemini or effective_groq),
        "has_gemini_key": bool(effective_gemini),
        "has_groq_key": bool(effective_groq),
        "has_firecrawl_key": bool(effective_firecrawl),
        "has_youtube_client_config": bool(has_youtube_client_config()),
        "has_youtube_connection": bool(has_youtube_connection()),
        "youtube_default_privacy": config.get("youtube_default_privacy", "private"),
        "recent_jobs_limit": RECENT_JOB_LIMIT,
        "uses_env_ai": admin_console,
    }


# ========================================
# Processing Logic (Inline to avoid import issues)
# ========================================


def run_processing_job(
    job_id: str,
    source: str,
    num_clips: int,
    source_type: str = "youtube",
    original_filename: Optional[str] = None,
    callback_config: Optional[dict] = None,
    public_base_url: Optional[str] = None,
):
    """Background task to process a video."""
    import time
    import shutil

    try:
        update_job_status(
            job_id, "starting", 5, "Initializing AI processing pipeline..."
        )

        # Import here to avoid startup issues
        from .video import download_video
        from .transcription import transcribe_video, get_segments_in_range
        from .highlights import detect_highlights
        from .ai_engine import is_ai_enabled, ai_enrich_highlight_metadata

        import sys

        sys.path.insert(0, str(BASE_DIR))
        from utils.ffmpeg_helpers import (
            create_shorts,
            get_video_info as ffmpeg_get_info,
        )

        ai_active = is_ai_enabled()
        ai_label = "🤖 AI-Powered" if ai_active else "📏 Rule-Based"

        temp_dir = OUTPUT_DIR / "temp" / job_id
        shorts_dir = SHORTS_DIR

        # Clean up any previous temp files
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        # ========================================
        # STAGE 1: Acquire Video
        # ========================================
        if source_type == "youtube":
            update_job_status(
                job_id, "downloading", 10, "Downloading video from YouTube..."
            )
            try:
                download_result = download_video(source, str(temp_dir))
                video_path = download_result["path"]
                video_info = download_result["info"]
            except Exception as e:
                update_job_status(
                    job_id, "error", 0, f"Download failed: {str(e)}", error=str(e)
                )
                return

            video_title = video_info.get("title", "Unknown")
            update_job_status(
                job_id,
                "downloading",
                25,
                f"Downloaded: {video_title[:50]}...",
                metadata={
                    "video_title": video_title,
                    "input_name": source,
                    "source_type": source_type,
                    "video_id": video_info.get("id"),
                },
            )

            source_type_label = "YouTube"
        else:
            update_job_status(job_id, "processing", 10, "Using uploaded source file...")
            if not os.path.exists(source):
                update_job_status(
                    job_id,
                    "error",
                    0,
                    f"Uploaded video not found: {source}",
                    error="source not found",
                )
                return

            # Copy into temp directory so cleanup is predictable
            ext = Path(source).suffix.lower()
            staged_path = temp_dir / f"source{ext}"
            shutil.copy2(source, staged_path)
            video_path = str(staged_path)
            video_title = Path(original_filename or Path(source).name).stem
            video_info = {
                "title": original_filename or Path(source).name,
                "duration": 0,
                "id": Path(source).stem,
            }
            source_type_label = "Uploaded file"
            update_job_status(
                job_id,
                "downloading",
                25,
                f"Prepared upload: {video_title[:50]}...",
                metadata={
                    "video_title": video_title,
                    "input_name": original_filename or Path(source).name,
                    "source_type": source_type,
                    "video_id": Path(source).stem,
                },
            )

        # Get video duration from ffprobe for accuracy
        try:
            ffmpeg_info = ffmpeg_get_info(video_path)
            video_duration = ffmpeg_info["duration"]
            if not video_duration:
                video_duration = video_info.get("duration", 300) or 300
        except Exception as e:
            logger.error(f"FFmpeg info error: {e}")
            video_duration = video_info.get("duration", 300) or 300

        update_job_status(
            job_id,
            "processing",
            28,
            "Video prepared. Starting transcription...",
            metadata={
                "video_title": video_title,
                "video_duration": round(float(video_duration or 0), 2),
                "source_type": source_type,
            },
        )

        # ========================================
        # STAGE 2: Transcribe with Whisper
        # ========================================
        update_job_status(
            job_id,
            "transcribing",
            30,
            "Transcribing audio with Whisper (this may take a while)...",
        )

        try:
            local_whisper_model = os.environ.get("LOCAL_WHISPER_MODEL", "base")
            segments = transcribe_video(video_path, model_size=local_whisper_model)
        except Exception as e:
            update_job_status(
                job_id, "error", 0, f"Transcription failed: {str(e)}", error=str(e)
            )
            return

        update_job_status(
            job_id, "transcribing", 55, f"Transcribed {len(segments)} segments"
        )

        # ========================================
        # STAGE 3: Detect Highlights (AI or Rule-based)
        # ========================================
        update_job_status(
            job_id,
            "analyzing",
            60,
            f"{ai_label}: Analyzing transcript for best moments from {source_type_label}...",
        )

        try:
            highlights = detect_highlights(
                segments=segments,
                video_duration=video_duration,
                num_clips=num_clips,
                video_title=video_title,
                video_path=video_path,
            )
        except Exception as e:
            update_job_status(
                job_id,
                "error",
                0,
                f"Highlight detection failed: {str(e)}",
                error=str(e),
            )
            return

        if not highlights:
            update_job_status(
                job_id,
                "error",
                0,
                "No highlights detected. Video may be too short.",
                error="No highlights detected",
            )
            return
        highlights = _clamp_highlights_to_short_duration(highlights, video_duration)
        if not highlights:
            update_job_status(
                job_id,
                "error",
                0,
                "No valid sub-60-second highlights were found.",
                error="No valid short highlights",
            )
            return

        # Enrich each clip with trendy metadata (AI titles + captions)
        if ai_active:
            update_job_status(
                job_id,
                "analyzing",
                68,
                "Generating AI short titles and trendy captions...",
            )
            for i, h in enumerate(highlights):
                clip_segments = get_segments_in_range(
                    segments, h.get("start", 0), h.get("end", 0)
                )
                clip_text = " ".join(seg["text"] for seg in clip_segments).strip()
                if not clip_text:
                    clip_text = h.get("text", "")

                metadata = ai_enrich_highlight_metadata(
                    transcript_text=clip_text, reason=h.get("reason", "highlight")
                )

                if not metadata:
                    continue

                if not h.get("title"):
                    h["title"] = metadata.get("title", "")
                if not h.get("hook_caption"):
                    h["hook_caption"] = metadata.get("hook_caption", "")
                if not h.get("trendy_caption"):
                    h["trendy_caption"] = metadata.get("trendy_caption", "")

                h["hashtags"] = metadata.get("hashtags", h.get("hashtags", []))
                h["caption_pack"] = metadata

        # Fill any missing trendy captions with a strong fallback
        for index, h in enumerate(highlights, start=1):
            if not h.get("trendy_caption"):
                if h.get("hook_caption"):
                    h["trendy_caption"] = h["hook_caption"]
                else:
                    h["trendy_caption"] = (
                        f"{h.get('text', 'Clip excerpt')[:110].strip()}..."
                    )
            if not h.get("title"):
                h["title"] = _derive_clip_title(h, index)

        # Check if AI provided enhanced data
        has_ai_data = any(h.get("title") or h.get("virality_score") for h in highlights)

        if has_ai_data:
            update_job_status(
                job_id,
                "analyzing",
                70,
                f"🤖 AI found {len(highlights)} viral moments! Top virality: "
                f"{max(h.get('virality_score', 0) for h in highlights)}/10",
            )
        else:
            update_job_status(
                job_id, "analyzing", 70, f"Found {len(highlights)} highlight segments"
            )

        # ========================================
        # STAGE 4: Generate Short Clips
        # ========================================
        update_job_status(
            job_id, "generating", 75, "Creating vertical short clips with captions..."
        )
        rendered_results: list[str] = []

        def on_short_render_progress(
            completed_count: int, total_count: int, output_path: str, highlight: dict
        ):
            if completed_count <= 0:
                return
            filename = os.path.basename(output_path)
            if filename not in rendered_results:
                rendered_results.append(filename)
            progress = min(98, 75 + int((completed_count / max(total_count, 1)) * 23))
            clip_label = (
                completed_count if completed_count <= total_count else total_count
            )
            update_job_status(
                job_id,
                "generating",
                progress,
                f"Rendered short {clip_label}/{total_count}",
                results=rendered_results,
            )

        try:
            output_files = create_shorts(
                input_video=video_path,
                highlights=highlights,
                segments=segments,
                output_dir=str(shorts_dir),
                output_prefix=f"{job_id[:8]}_short",
                progress_callback=on_short_render_progress,
            )
        except Exception as e:
            update_job_status(
                job_id, "error", 0, f"Video generation failed: {str(e)}", error=str(e)
            )
            return

        # ========================================
        # COMPLETE
        # ========================================
        result_files = [os.path.basename(f) for f in output_files]

        # Build AI highlights info
        ai_highlights_data = []
        for i, h in enumerate(highlights):
            hashtags = h.get("hashtags", [])
            if not isinstance(hashtags, list):
                hashtags = []

            ai_highlights_data.append(
                {
                    "index": i + 1,
                    "filename": result_files[i] if i < len(result_files) else "",
                    "title": _derive_clip_title(h, i + 1),
                    "hook_caption": h.get("hook_caption", ""),
                    "trendy_caption": h.get("trendy_caption", ""),
                    "hashtags": hashtags,
                    "virality_score": h.get("virality_score", 0),
                    "face_score": round(float(h.get("face_score", 0.0)), 4),
                    "face_presence": round(float(h.get("face_presence", 0.0)), 4),
                    "face_center_offset": round(
                        float(h.get("face_center_offset", 0.0)), 4
                    ),
                    "reason": h.get("reason", "highlight"),
                    "start": h.get("start", 0),
                    "end": h.get("end", 0),
                    "text": h.get("text", "")[:200],
                }
            )

        update_job_status(
            job_id,
            "complete",
            100,
            f"✨ Generated {len(result_files)} viral shorts!",
            results=result_files,
            ai_highlights=ai_highlights_data,
            metadata={
                "video_title": video_title,
                "video_duration": round(float(video_duration or 0), 2),
                "source_type": source_type,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Clean up temp files
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

    except Exception as e:
        logger.error(f"Processing error: {traceback.format_exc()}")
        update_job_status(
            job_id, "error", 0, f"Processing failed: {str(e)}", error=str(e)
        )
    finally:
        final_status = load_job_status(job_id) or {}
        if callback_config:
            _send_callback(
                job_id=job_id,
                status=final_status,
                callback_info={
                    **callback_config,
                    "public_base_url": public_base_url,
                },
            )

        if source_type == "upload":
            try:
                upload_root = Path(source).parent
                shutil.rmtree(upload_root)
            except:
                pass


# ========================================
# API Endpoints
# ========================================


@app.get("/session", response_model=SessionResponse)
async def get_session(user: ClerkUser = Depends(_require_app_user)):
    usage = get_daily_usage(user.id, limit=DAILY_PROCESS_LIMIT)
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        image_url=user.image_url,
        is_admin=_is_admin_user(user),
        usage=UsageResponse(**usage),
    )


@app.get("/usage", response_model=UsageResponse)
async def get_usage(user: ClerkUser = Depends(_require_app_user)):
    usage = get_daily_usage(user.id, limit=DAILY_PROCESS_LIMIT)
    return UsageResponse(**usage)


@app.post("/process", response_model=ProcessResponse)
async def start_processing(
    request: ProcessRequest, user: ClerkUser = Depends(_require_app_user_or_api_key)
):
    if not _is_automation_api_user(user):
        _assert_daily_quota(user)
    return _queue_youtube_job(request, user)


@app.post("/process/upload", response_model=ProcessResponse)
async def start_processing_upload(
    file: UploadFile = File(...),
    num_clips: int = Form(10),
    callback_url: Optional[str] = Form(default=None),
    callback_token: Optional[str] = Form(default=None),
    callback_auth_header: str = Form(default="X-Callback-Token"),
    public_base_url: Optional[str] = Form(default=None),
    callback_timeout_seconds: int = Form(
        default=DEFAULT_UPLOAD_CALLBACK_TIMEOUT_SECONDS
    ),
    user: ClerkUser = Depends(_require_app_user_or_api_key),
):
    if not _is_automation_api_user(user):
        _assert_daily_quota(user)
    return await _queue_upload_job(
        file=file,
        num_clips=num_clips,
        callback_url=callback_url,
        callback_token=callback_token,
        callback_auth_header=callback_auth_header,
        public_base_url=public_base_url,
        callback_timeout_seconds=callback_timeout_seconds,
        user=user,
    )


@app.get("/status/{job_id}")
async def get_status(
    job_id: str,
    request: Request,
    user: ClerkUser = Depends(_require_app_user_or_api_key),
):
    return _get_job_payload(
        job_id, public_base_url=_resolve_public_base_url(request), user=user
    )


@app.get("/jobs/recent")
async def get_recent_jobs(
    request: Request, user: ClerkUser = Depends(_require_app_user_or_api_key)
):
    base_url = _resolve_public_base_url(request)
    jobs = list_recent_jobs(public_base_url=base_url, owner_id=user.id)
    return {
        "jobs": jobs,
        "count": len(jobs),
    }


@app.get("/result/{job_id}")
async def get_result(
    job_id: str,
    request: Request,
    user: ClerkUser = Depends(_require_app_user_or_api_key),
):
    return _get_completed_result_payload(
        job_id, _resolve_public_base_url(request), user=user
    )


@app.get("/shorts/{filename}")
async def download_short(
    filename: str, user: ClerkUser = Depends(_require_app_user_or_api_key)
):
    """Download a generated short clip."""
    safe_name = Path(filename).name
    file_path = SHORTS_DIR / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if database_enabled() and not result_file_belongs_to_user(user.id, safe_name):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=str(file_path), filename=filename, media_type="video/mp4")


@app.get("/shorts")
async def list_shorts(user: ClerkUser = Depends(_require_app_user_or_api_key)):
    """List all generated shorts."""
    jobs = list_recent_jobs(limit=RECENT_JOB_LIMIT, owner_id=user.id)
    short_names: list[str] = []
    for job in jobs:
        for filename in job.get("results", []) or []:
            if filename not in short_names:
                short_names.append(filename)
    return {"shorts": short_names}


@app.delete("/shorts/{filename}")
async def delete_short(
    filename: str, user: ClerkUser = Depends(_require_app_user_or_api_key)
):
    """Delete a generated short clip."""
    safe_name = _safe_filename(filename)
    file_path = SHORTS_DIR / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if database_enabled() and not result_file_belongs_to_user(user.id, safe_name):
        raise HTTPException(status_code=404, detail="File not found")

    os.remove(file_path)
    return {"message": f"Deleted {safe_name}"}


@app.delete("/shorts")
async def clear_shorts(user: ClerkUser = Depends(_require_app_user_or_api_key)):
    """Delete all generated shorts."""
    if SHORTS_DIR.exists():
        jobs = list_recent_jobs(limit=RECENT_JOB_LIMIT * 4, owner_id=user.id)
        owned_files = {
            filename for job in jobs for filename in (job.get("results", []) or [])
        }
        for filename in owned_files:
            file_path = SHORTS_DIR / filename
            if file_path.exists() and file_path.suffix == ".mp4":
                os.remove(file_path)

    return {"message": "Deleted your generated shorts"}


# ========================================
# API Key Management Endpoints
# ========================================


class APIKeyRequest(BaseModel):
    name: str = "n8n-automation"


@app.get("/api-keys")
async def list_api_keys(admin: None = Depends(_require_admin_token)):
    """List configured API keys (metadata only)."""
    keys = _list_api_keys()
    return {
        "count": len(keys),
        "api_keys": [
            {
                "id": item.get("id"),
                "name": item.get("name", ""),
                "prefix": item.get("prefix", ""),
                "created_at": item.get("created_at", ""),
                "last_used_at": item.get("last_used_at", ""),
            }
            for item in keys
        ],
    }


@app.post("/api-keys")
async def create_api_key(
    payload: APIKeyRequest, admin: None = Depends(_require_admin_token)
):
    """Create a new API key for automation clients."""
    api_key = secrets.token_urlsafe(DEFAULT_API_KEY_LENGTH)
    key_entry = {
        "id": secrets.token_hex(8),
        "name": payload.name,
        "hash": _hash_api_key(api_key),
        "prefix": api_key[:8],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    keys = _list_api_keys()
    keys.append(key_entry)
    _write_app_config({"api_keys": keys})
    if _get_auth_mode() == AUTH_MODE_QUICK:
        _set_auth_mode(AUTH_MODE_PRODUCTION)

    return {
        "id": key_entry["id"],
        "name": key_entry["name"],
        "api_key": api_key,
        "masked_api_key": _mask_api_key(api_key),
        "prefix": key_entry["prefix"],
        "message": "Store this key now; it cannot be retrieved again.",
    }


@app.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: str, admin: None = Depends(_require_admin_token)):
    """Revoke one API key by ID."""
    keys = [item for item in _list_api_keys() if item.get("id") != key_id]
    _write_app_config({"api_keys": keys})
    return {"message": f"Deleted API key {key_id}"}


@app.get("/auth/mode", response_model=AuthModeResponse)
async def get_auth_mode():
    """Inspect whether API key authentication is required."""
    mode = _get_auth_mode()
    return AuthModeResponse(
        mode=mode,
        requires_api_key=mode == AUTH_MODE_PRODUCTION or len(_list_api_keys()) > 0,
        api_key_count=len(_list_api_keys()),
        admin_token_configured=bool(_get_admin_token()),
    )


@app.post("/auth/mode", response_model=AuthModeResponse)
async def set_auth_mode(
    payload: AuthModeRequest, admin: None = Depends(_require_admin_token)
):
    """Force auth mode for production/quick behavior."""
    try:
        _set_auth_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return AuthModeResponse(
        mode=_get_auth_mode(),
        requires_api_key=_is_api_auth_required(),
        api_key_count=len(_list_api_keys()),
        admin_token_configured=bool(_get_admin_token()),
    )


# ========================================
# AI Configuration Endpoints
# ========================================


def _build_ai_config_response() -> dict:
    """Get current AI configuration status."""
    from .ai_engine import load_config, is_ai_enabled, get_api_key
    from .youtube_publish import get_youtube_status
    from .ytdlp_cookie_sync import (
        browser_cookie_dependency_available,
        get_cookie_auto_sync_state,
    )

    config = load_config()
    api_key = get_api_key()
    youtube_status = get_youtube_status()
    cookie_sync_state = get_cookie_auto_sync_state(config)

    # Download auth fields
    pot_provider = (
        os.environ.get("SHORTMAKER_YTDLP_POT_PROVIDER", "").strip()
        or str(config.get("ytdlp_pot_provider", "")).strip()
        or "disabled"
    )
    pot_base_url = (
        os.environ.get("SHORTMAKER_YTDLP_POT_BASE_URL", "").strip()
        or str(config.get("ytdlp_pot_base_url", "")).strip()
    )
    pot_server_healthy = None
    if pot_provider == "http" and pot_base_url:
        try:
            import urllib.request

            health_url = pot_base_url.rstrip("/") + "/ping"
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                pot_server_healthy = resp.status == 200
        except Exception:
            pot_server_healthy = False

    # PO Token server management capabilities
    try:
        from .pot_server import (
            get_server_status as _pot_status,
            DEFAULT_PORT as _POT_PORT,
        )

        _psi = _pot_status(port=_POT_PORT)
        pot_server_running = (
            _psi.get("process_running", False) or _psi.get("healthy") is True
        )
        pot_server_can_start = _psi.get("docker_image_available", False) or _psi.get(
            "native_installed", False
        )
        pot_docker_available = _psi.get("docker_available", False)
        pot_node_available = _psi.get("node_available", False)
    except Exception:
        pot_server_running = False
        pot_server_can_start = False
        pot_docker_available = False
        pot_node_available = False

    return {
        "ai_enabled": config.get("ai_enabled", False),
        "has_api_key": bool(api_key),
        "has_groq_key": bool(config.get("groq_api_key", "")),
        "has_firecrawl_key": bool(config.get("firecrawl_api_key", "")),
        "has_ytdlp_cookies": bool(config.get("ytdlp_cookies_base64", "")),
        "browser_cookie_import_supported": browser_cookie_dependency_available(),
        **cookie_sync_state,
        "has_youtube_client_config": youtube_status.get("has_client_config", False),
        "has_youtube_connection": youtube_status.get("connected", False),
        "youtube_default_privacy": youtube_status.get(
            "default_privacy_status", "private"
        ),
        "youtube_authorized_at": youtube_status.get("authorized_at"),
        "model": config.get("model", "gemini-2.5-flash"),
        "is_active": is_ai_enabled(),
        "message": (
            "AI is active and ready!"
            if is_ai_enabled()
            else "Configure your API keys through environment variables or the encrypted admin store."
        ),
        # Download auth (PO Token + OAuth2)
        "ytdlp_pot_provider": pot_provider,
        "ytdlp_pot_base_url": pot_base_url,
        "ytdlp_pot_player_clients": str(
            config.get("ytdlp_pot_player_clients", "mweb,web")
        ),
        "ytdlp_pot_server_healthy": pot_server_healthy,
        "ytdlp_pot_server_running": pot_server_running,
        "ytdlp_pot_server_can_start": pot_server_can_start,
        "ytdlp_pot_docker_available": pot_docker_available,
        "ytdlp_pot_node_available": pot_node_available,
        "ytdlp_oauth2_enabled": bool(config.get("ytdlp_oauth2_enabled", False)),
    }


def _apply_ai_config(request: AIConfigRequest) -> dict:
    """Configure AI settings."""
    from .ai_engine import save_config, check_api_key_format, load_config
    from .youtube_publish import VALID_PRIVACY_STATUSES
    from .ytdlp_cookie_sync import (
        get_cookie_auto_sync_state,
        normalize_cookie_auto_sync_browser,
        normalize_cookie_auto_sync_interval_hours,
    )

    # Quick format check for Gemini key (no live API call)
    if request.gemini_api_key:
        is_valid, message = check_api_key_format(request.gemini_api_key)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)
    _assert_secret_storage_ready(
        request.gemini_api_key,
        request.groq_api_key,
        request.firecrawl_api_key,
        request.youtube_client_id,
        request.youtube_client_secret,
        request.ytdlp_cookies,
    )
    normalized_privacy = request.youtube_default_privacy.strip().lower() or "private"
    if normalized_privacy not in VALID_PRIVACY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="YouTube privacy must be private, unlisted, or public.",
        )

    # Load existing config to preserve keys and automation credentials not updated by this endpoint
    existing = load_config()
    existing_cookie_sync_state = get_cookie_auto_sync_state(existing)
    youtube_client_changed = bool(
        (
            request.youtube_client_id
            and request.youtube_client_id != existing.get("youtube_client_id", "")
        )
        or (
            request.youtube_client_secret
            and request.youtube_client_secret
            != existing.get("youtube_client_secret", "")
        )
    )
    auto_sync_enabled = (
        request.ytdlp_cookie_auto_sync_enabled
        if request.ytdlp_cookie_auto_sync_enabled is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_enabled"]
    )
    auto_sync_browser = normalize_cookie_auto_sync_browser(
        request.ytdlp_cookie_auto_sync_browser
        if request.ytdlp_cookie_auto_sync_browser is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_browser"]
    )
    auto_sync_interval_hours = normalize_cookie_auto_sync_interval_hours(
        request.ytdlp_cookie_auto_sync_interval_hours
        if request.ytdlp_cookie_auto_sync_interval_hours is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_interval_hours"]
    )
    auto_sync_on_sign_in = (
        request.ytdlp_cookie_auto_sync_on_sign_in
        if request.ytdlp_cookie_auto_sync_on_sign_in is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_on_sign_in"]
    )

    config = {
        "gemini_api_key": request.gemini_api_key or existing.get("gemini_api_key", ""),
        "groq_api_key": request.groq_api_key or existing.get("groq_api_key", ""),
        "firecrawl_api_key": request.firecrawl_api_key
        or existing.get("firecrawl_api_key", ""),
        "youtube_client_id": request.youtube_client_id
        or existing.get("youtube_client_id", ""),
        "youtube_client_secret": request.youtube_client_secret
        or existing.get("youtube_client_secret", ""),
        "ytdlp_cookies_base64": (
            base64.b64encode(request.ytdlp_cookies.encode("utf-8")).decode("utf-8")
            if request.ytdlp_cookies.strip()
            else existing.get("ytdlp_cookies_base64", "")
        ),
        "ytdlp_cookie_auto_sync_enabled": auto_sync_enabled,
        "ytdlp_cookie_auto_sync_browser": auto_sync_browser,
        "ytdlp_cookie_auto_sync_interval_hours": auto_sync_interval_hours,
        "ytdlp_cookie_auto_sync_on_sign_in": auto_sync_on_sign_in,
        "youtube_default_privacy": normalized_privacy,
        "ai_enabled": request.ai_enabled,
        "model": request.model,
    }

    # Keep non-AI settings (automation API keys, admin metadata)
    merged = existing.copy()
    merged.update(config)
    if youtube_client_changed:
        merged.pop("youtube_oauth", None)

    save_config(merged)

    parts = []
    if config["gemini_api_key"]:
        parts.append("Gemini AI highlights")
    if config["groq_api_key"]:
        parts.append("Groq Whisper transcription")
    if config["firecrawl_api_key"]:
        parts.append("Firecrawl trend discovery")
    if config["ytdlp_cookies_base64"]:
        parts.append("YouTube source downloads")
    if config["youtube_client_id"] and config["youtube_client_secret"]:
        parts.append("YouTube publishing")

    feature_msg = " & ".join(parts) if parts else "No features"

    return {
        "success": True,
        "ai_enabled": request.ai_enabled,
        "has_api_key": bool(config["gemini_api_key"]),
        "has_groq_key": bool(config["groq_api_key"]),
        "has_firecrawl_key": bool(config["firecrawl_api_key"]),
        "has_youtube_client_config": bool(
            config["youtube_client_id"] and config["youtube_client_secret"]
        ),
        "has_youtube_connection": bool(
            merged.get("youtube_oauth", {}).get("refresh_token")
        ),
        "ytdlp_cookie_auto_sync_enabled": auto_sync_enabled,
        "ytdlp_cookie_auto_sync_browser": auto_sync_browser,
        "ytdlp_cookie_auto_sync_interval_hours": auto_sync_interval_hours,
        "ytdlp_cookie_auto_sync_on_sign_in": auto_sync_on_sign_in,
        "youtube_default_privacy": normalized_privacy,
        "model": request.model,
        "message": f"Saved! Enabled: {feature_msg}."
        if request.ai_enabled
        else "AI features disabled.",
    }


def _validate_ai_key(request: AIValidateRequest) -> dict:
    """Validate a Gemini API key without saving it."""
    from .ai_engine import validate_api_key

    is_valid, message = validate_api_key(request.api_key)

    return {"valid": is_valid, "message": message}


@app.get("/ai/config")
async def get_ai_config(admin: ClerkUser = Depends(_require_admin_user)):
    return _build_ai_config_response()


@app.post("/ai/config")
async def set_ai_config(
    request: AIConfigRequest, admin: ClerkUser = Depends(_require_admin_user)
):
    return _apply_ai_config(request)


@app.post("/ai/validate")
async def validate_key(
    request: AIValidateRequest, admin: ClerkUser = Depends(_require_admin_user)
):
    return _validate_ai_key(request)


@app.get(f"{ADMIN_ROUTE_PREFIX}/ai/config")
async def admin_get_ai_config():
    """Expose admin config values for the standalone admin console."""

    from .ai_engine import load_config

    payload = _build_ai_config_response()
    config = load_config()
    payload["gemini_api_key"] = config.get("gemini_api_key", "")
    payload["groq_api_key"] = config.get("groq_api_key", "")
    payload["firecrawl_api_key"] = config.get("firecrawl_api_key", "")
    payload["youtube_client_id"] = config.get("youtube_client_id", "")
    payload["youtube_client_secret"] = config.get("youtube_client_secret", "")
    payload["ytdlp_cookies"] = ""
    return payload


@app.post(f"{ADMIN_ROUTE_PREFIX}/ai/config")
async def admin_set_ai_config(request: AIConfigRequest):
    """Accept admin-prefixed AI config requests for frontend compatibility."""
    return _apply_ai_config(request)


@app.post(f"{ADMIN_ROUTE_PREFIX}/ai/validate")
async def admin_validate_key(request: AIValidateRequest):
    return _validate_ai_key(request)


def _run_ytdlp_cookie_sync(reason: str) -> dict:
    from .ytdlp_cookie_sync import (
        maybe_sync_cookies_for_sign_in,
        sync_cookies_with_status,
    )

    normalized_reason = (reason or "manual").strip().lower()
    if normalized_reason == "login":
        return maybe_sync_cookies_for_sign_in()
    return sync_cookies_with_status(reason=normalized_reason or "manual")


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/cookies/sync")
async def admin_sync_youtube_cookies(request: YouTubeCookieSyncRequest):
    result = _run_ytdlp_cookie_sync(request.reason)
    status_code = 200 if result.get("ok", False) else 500
    if status_code != 200:
        raise HTTPException(
            status_code=status_code,
            detail=result.get("error")
            or result.get("message")
            or "Cookie sync failed.",
        )
    return result


# ========================================
# Cookie Config Endpoints (all authenticated users)
# ========================================


class CookieConfigRequest(BaseModel):
    ytdlp_cookies: str = ""
    ytdlp_cookie_auto_sync_enabled: Optional[bool] = None
    ytdlp_cookie_auto_sync_browser: Optional[str] = None
    ytdlp_cookie_auto_sync_interval_hours: Optional[int] = None
    ytdlp_cookie_auto_sync_on_sign_in: Optional[bool] = None


def _build_cookie_config_response() -> dict:
    from .ai_engine import load_config
    from .ytdlp_cookie_sync import (
        browser_cookie_dependency_available,
        get_cookie_auto_sync_state,
        _playwright_available,
        _is_firefox_available,
    )

    config = load_config()
    cookie_sync_state = get_cookie_auto_sync_state(config)

    return {
        "has_ytdlp_cookies": bool(config.get("ytdlp_cookies_base64", "")),
        "browser_cookie_import_supported": browser_cookie_dependency_available()
        or _is_firefox_available(),
        "firefox_available": _is_firefox_available(),
        "playwright_available": _playwright_available(),
        **cookie_sync_state,
    }


def _apply_cookie_config(request: CookieConfigRequest) -> dict:
    from .ai_engine import save_config, load_config
    from .ytdlp_cookie_sync import (
        get_cookie_auto_sync_state,
        normalize_cookie_auto_sync_browser,
        normalize_cookie_auto_sync_interval_hours,
    )

    existing = load_config()
    existing_cookie_sync_state = get_cookie_auto_sync_state(existing)

    auto_sync_enabled = (
        request.ytdlp_cookie_auto_sync_enabled
        if request.ytdlp_cookie_auto_sync_enabled is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_enabled"]
    )
    auto_sync_browser = normalize_cookie_auto_sync_browser(
        request.ytdlp_cookie_auto_sync_browser
        if request.ytdlp_cookie_auto_sync_browser is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_browser"]
    )
    auto_sync_interval_hours = normalize_cookie_auto_sync_interval_hours(
        request.ytdlp_cookie_auto_sync_interval_hours
        if request.ytdlp_cookie_auto_sync_interval_hours is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_interval_hours"]
    )
    auto_sync_on_sign_in = (
        request.ytdlp_cookie_auto_sync_on_sign_in
        if request.ytdlp_cookie_auto_sync_on_sign_in is not None
        else existing_cookie_sync_state["ytdlp_cookie_auto_sync_on_sign_in"]
    )

    merged = existing.copy()
    if request.ytdlp_cookies.strip():
        _assert_secret_storage_ready(request.ytdlp_cookies)
        merged["ytdlp_cookies_base64"] = base64.b64encode(
            request.ytdlp_cookies.encode("utf-8")
        ).decode("utf-8")
    merged["ytdlp_cookie_auto_sync_enabled"] = auto_sync_enabled
    merged["ytdlp_cookie_auto_sync_browser"] = auto_sync_browser
    merged["ytdlp_cookie_auto_sync_interval_hours"] = auto_sync_interval_hours
    merged["ytdlp_cookie_auto_sync_on_sign_in"] = auto_sync_on_sign_in

    save_config(merged)

    return {
        "success": True,
        "has_ytdlp_cookies": bool(merged.get("ytdlp_cookies_base64", "")),
        "ytdlp_cookie_auto_sync_enabled": auto_sync_enabled,
        "ytdlp_cookie_auto_sync_browser": auto_sync_browser,
        "ytdlp_cookie_auto_sync_interval_hours": auto_sync_interval_hours,
        "ytdlp_cookie_auto_sync_on_sign_in": auto_sync_on_sign_in,
        "message": "Cookie settings saved.",
    }


@app.get("/youtube/cookies/config")
async def get_cookie_config(user: ClerkUser = Depends(_require_app_user)):
    return _build_cookie_config_response()


@app.post("/youtube/cookies/config")
async def set_cookie_config(
    request: CookieConfigRequest,
    user: ClerkUser = Depends(_require_app_user),
):
    return _apply_cookie_config(request)


@app.get(f"{ADMIN_ROUTE_PREFIX}/youtube/cookies/config")
async def admin_get_cookie_config():
    return _build_cookie_config_response()


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/cookies/config")
async def admin_set_cookie_config(request: CookieConfigRequest):
    return _apply_cookie_config(request)


# Downgrade cookie sync from admin-only to any authenticated user
@app.post("/youtube/cookies/sync")
async def sync_youtube_cookies(
    request: YouTubeCookieSyncRequest,
    user: ClerkUser = Depends(_require_app_user),
):
    result = _run_ytdlp_cookie_sync(request.reason)
    status_code = 200 if result.get("ok", False) else 500
    if status_code != 200:
        raise HTTPException(
            status_code=status_code,
            detail=result.get("error")
            or result.get("message")
            or "Cookie sync failed.",
        )
    return result


# Playwright-based cookie sync (automated browser fallback)
class PlaywrightCookieSyncRequest(BaseModel):
    reason: str = "manual"
    google_email: Optional[str] = None
    google_password: Optional[str] = None


def _run_playwright_cookie_sync(
    reason: str,
    google_email: Optional[str] = None,
    google_password: Optional[str] = None,
) -> dict:
    from .ytdlp_cookie_sync import sync_cookies_with_playwright

    return sync_cookies_with_playwright(
        google_email=google_email,
        google_password=google_password,
        reason=reason,
    )


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/cookies/sync-playwright")
async def admin_sync_youtube_cookies_playwright(request: PlaywrightCookieSyncRequest):
    try:
        result = _run_playwright_cookie_sync(
            request.reason, request.google_email, request.google_password
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@app.post("/youtube/cookies/sync-playwright")
async def sync_youtube_cookies_playwright(
    request: PlaywrightCookieSyncRequest,
    user: ClerkUser = Depends(_require_app_user),
):
    try:
        result = _run_playwright_cookie_sync(
            request.reason, request.google_email, request.google_password
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


# ========================================
# Download Auth Endpoints (PO Token + OAuth2)
# ========================================


class DownloadAuthConfigRequest(BaseModel):
    ytdlp_pot_provider: Optional[str] = None
    ytdlp_pot_base_url: Optional[str] = None
    ytdlp_pot_player_clients: Optional[str] = None
    ytdlp_oauth2_enabled: Optional[bool] = None


def _build_download_auth_status() -> dict:
    from .ai_engine import load_config

    config = load_config()
    pot_provider = (
        os.environ.get("SHORTMAKER_YTDLP_POT_PROVIDER", "").strip()
        or str(config.get("ytdlp_pot_provider", "")).strip()
        or "disabled"
    )
    pot_base_url = (
        os.environ.get("SHORTMAKER_YTDLP_POT_BASE_URL", "").strip()
        or str(config.get("ytdlp_pot_base_url", "")).strip()
    )

    # Check PO token server health
    pot_server_healthy = None
    if pot_provider == "http" and pot_base_url:
        try:
            import urllib.request

            health_url = pot_base_url.rstrip("/") + "/ping"
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                pot_server_healthy = resp.status == 200
        except Exception:
            pot_server_healthy = False

    # Server management capabilities
    try:
        from .pot_server import (
            is_server_running as _pot_running,
            get_server_status as _pot_status,
            DEFAULT_PORT as _POT_PORT,
        )

        pot_server_info = _pot_status(port=_POT_PORT)
    except Exception:
        pot_server_info = {
            "process_running": False,
            "healthy": False,
            "docker_image_available": False,
            "native_installed": False,
            "docker_available": False,
            "node_available": False,
        }

    return {
        "oauth2_enabled": bool(config.get("ytdlp_oauth2_enabled", False)),
        "has_cookies": bool(config.get("ytdlp_cookies_base64", "")),
        "pot_provider": pot_provider,
        "pot_base_url": pot_base_url,
        "pot_player_clients": str(config.get("ytdlp_pot_player_clients", "mweb,web")),
        "pot_server_healthy": pot_server_healthy,
        "pot_server_running": pot_server_info.get("process_running", False)
        or pot_server_info.get("healthy") is True,
        "pot_server_can_start": pot_server_info.get("docker_image_available", False)
        or pot_server_info.get("native_installed", False),
        "pot_docker_available": pot_server_info.get("docker_available", False),
        "pot_node_available": pot_server_info.get("node_available", False),
    }


def _apply_download_auth_config(request: DownloadAuthConfigRequest) -> dict:
    from .ai_engine import save_config, load_config

    existing = load_config()
    merged = existing.copy()

    if request.ytdlp_pot_provider is not None:
        merged["ytdlp_pot_provider"] = request.ytdlp_pot_provider.strip().lower()
    if request.ytdlp_pot_base_url is not None:
        merged["ytdlp_pot_base_url"] = request.ytdlp_pot_base_url.strip()
    if request.ytdlp_pot_player_clients is not None:
        merged["ytdlp_pot_player_clients"] = request.ytdlp_pot_player_clients.strip()
    if request.ytdlp_oauth2_enabled is not None:
        merged["ytdlp_oauth2_enabled"] = request.ytdlp_oauth2_enabled

    save_config(merged)

    status = _build_download_auth_status()
    return {"success": True, "message": "Download auth settings saved.", **status}


@app.get("/youtube/download-auth/status")
async def get_download_auth_status(user: ClerkUser = Depends(_require_app_user)):
    return _build_download_auth_status()


@app.post("/youtube/download-auth/config")
async def set_download_auth_config(
    request: DownloadAuthConfigRequest,
    user: ClerkUser = Depends(_require_app_user),
):
    return _apply_download_auth_config(request)


@app.get("/youtube/download-auth/pot/health")
async def check_pot_health(user: ClerkUser = Depends(_require_app_user)):
    status = _build_download_auth_status()
    if status["pot_provider"] == "disabled":
        return {
            "healthy": None,
            "provider": "disabled",
            "message": "No PO token provider configured.",
        }
    if status["pot_provider"] == "http":
        return {
            "healthy": status["pot_server_healthy"],
            "provider": "http",
            "base_url": status["pot_base_url"],
            "message": "PO token server is reachable."
            if status["pot_server_healthy"]
            else "PO token server is not reachable.",
        }
    return {
        "healthy": None,
        "provider": status["pot_provider"],
        "message": f"Provider '{status['pot_provider']}' does not support health checks.",
    }


@app.get(f"{ADMIN_ROUTE_PREFIX}/youtube/download-auth/status")
async def admin_get_download_auth_status():
    return _build_download_auth_status()


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/download-auth/config")
async def admin_set_download_auth_config(request: DownloadAuthConfigRequest):
    return _apply_download_auth_config(request)


@app.get(f"{ADMIN_ROUTE_PREFIX}/youtube/download-auth/pot/health")
async def admin_check_pot_health():
    status = _build_download_auth_status()
    if status["pot_provider"] == "disabled":
        return {
            "healthy": None,
            "provider": "disabled",
            "message": "No PO token provider configured.",
        }
    if status["pot_provider"] == "http":
        return {
            "healthy": status["pot_server_healthy"],
            "provider": "http",
            "base_url": status["pot_base_url"],
            "message": "PO token server is reachable."
            if status["pot_server_healthy"]
            else "PO token server is not reachable.",
        }
    return {
        "healthy": None,
        "provider": status["pot_provider"],
        "message": f"Provider '{status['pot_provider']}' does not support health checks.",
    }


# PO Token Server Management (auto-start bgutil HTTP server)


@app.get("/youtube/download-auth/pot/server-status")
async def get_pot_server_status(user: ClerkUser = Depends(_require_app_user)):
    from .pot_server import get_server_status, DEFAULT_PORT

    return get_server_status(port=DEFAULT_PORT)


@app.post("/youtube/download-auth/pot/start")
async def start_pot_server(user: ClerkUser = Depends(_require_app_user)):
    from .pot_server import ensure_server_started, DEFAULT_PORT

    result = ensure_server_started(port=DEFAULT_PORT)
    if not result["started"]:
        raise HTTPException(status_code=500, detail=result["message"])

    # Auto-save the base URL and provider into config
    from .ai_engine import load_config, save_config

    config = load_config()
    config["ytdlp_pot_provider"] = "http"
    config["ytdlp_pot_base_url"] = result["base_url"]
    save_config(config)

    return result


@app.post("/youtube/download-auth/pot/stop")
async def stop_pot_server(user: ClerkUser = Depends(_require_app_user)):
    from .pot_server import stop_server

    stop_server()
    return {"stopped": True, "message": "PO Token server stopped."}


@app.get(f"{ADMIN_ROUTE_PREFIX}/youtube/download-auth/pot/server-status")
async def admin_get_pot_server_status():
    from .pot_server import get_server_status, DEFAULT_PORT

    return get_server_status(port=DEFAULT_PORT)


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/download-auth/pot/start")
async def admin_start_pot_server():
    from .pot_server import ensure_server_started, DEFAULT_PORT

    result = ensure_server_started(port=DEFAULT_PORT)
    if not result["started"]:
        raise HTTPException(status_code=500, detail=result["message"])

    from .ai_engine import load_config, save_config

    config = load_config()
    config["ytdlp_pot_provider"] = "http"
    config["ytdlp_pot_base_url"] = result["base_url"]
    save_config(config)

    return result


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/download-auth/pot/stop")
async def admin_stop_pot_server():
    from .pot_server import stop_server

    stop_server()
    return {"stopped": True, "message": "PO Token server stopped."}


@app.post("/trends/discover")
async def discover_trends(
    request: TrendDiscoverRequest, user: ClerkUser = Depends(_require_app_user)
):
    from .trends import discover_trend_videos

    try:
        candidates = discover_trend_videos(
            topic=request.topic,
            location=request.location,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "topic": request.topic,
        "location": request.location,
        "candidates": candidates,
        "count": len(candidates),
    }


@app.post("/trends/auto-process")
async def auto_process_trend(
    request: TrendAutoProcessRequest, user: ClerkUser = Depends(_require_app_user)
):
    from .trends import auto_pick_trend_video

    _assert_daily_quota(user)

    try:
        candidate = auto_pick_trend_video(
            topic=request.topic,
            location=request.location,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    response = _queue_youtube_job(
        ProcessRequest(
            url=candidate["url"],
            num_clips=validate_num_clips(request.num_clips),
        ),
        user,
    )

    return {
        "job_id": response.job_id,
        "message": response.message,
        "candidate": candidate,
    }


@app.get("/youtube/status")
async def get_youtube_publish_status(
    request: Request, user: ClerkUser = Depends(_require_app_user)
):
    from .youtube_publish import get_youtube_status

    try:
        status = get_youtube_status(user_id=_youtube_scope_user_id(user))
        status["expected_redirect_uri"] = _build_youtube_redirect_uri(request)
        return status
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to build YouTube status for user %s", getattr(user, "id", None)
        )
        raise HTTPException(
            status_code=500, detail="Failed to load YouTube status."
        ) from exc


@app.post("/youtube/config")
async def set_youtube_publish_config(
    request: YouTubeConfigRequest, user: ClerkUser = Depends(_require_app_user)
):
    from .youtube_publish import save_youtube_settings

    _assert_secret_storage_ready(
        request.youtube_client_id, request.youtube_client_secret
    )
    status = save_youtube_settings(
        client_id=request.youtube_client_id,
        client_secret=request.youtube_client_secret,
        default_privacy_status=request.youtube_default_privacy,
        user_id=_youtube_scope_user_id(user),
    )
    return {
        "success": True,
        **status,
        "message": "Saved YouTube publishing settings.",
    }


@app.post("/youtube/auth/start")
async def start_youtube_auth(
    request: Request, user: ClerkUser = Depends(_require_app_user)
):
    from .youtube_publish import build_authorization_url

    redirect_uri = _build_youtube_redirect_uri(request)
    try:
        auth_url = build_authorization_url(
            redirect_uri, user_id=_youtube_scope_user_id(user)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("YouTube auth start failed")
        raise HTTPException(status_code=503, detail=f"YouTube auth failed: {exc}")

    return {
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
    }


@app.get("/youtube/oauth/callback")
@app.get("/ashmil2010/youtube/oauth/callback")
@app.get("/rest/oauth2-credential/callback")
@app.get("/ashmil2010/rest/oauth2-credential/callback")
async def youtube_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    from .youtube_publish import build_callback_html, complete_oauth_callback

    origin = _resolve_youtube_oauth_origin(request)
    redirect_uri = _build_youtube_redirect_uri(request)
    if error:
        return HTMLResponse(
            build_callback_html(False, f"Google OAuth returned: {error}", origin),
            status_code=400,
        )

    try:
        complete_oauth_callback(
            code=code or "", state=state or "", redirect_uri=redirect_uri
        )
    except ValueError as exc:
        return HTMLResponse(
            build_callback_html(False, str(exc), origin), status_code=400
        )
    except RuntimeError as exc:
        return HTMLResponse(
            build_callback_html(False, str(exc), origin), status_code=503
        )
    except Exception as exc:
        logger.exception("YouTube OAuth callback failed")
        return HTMLResponse(
            build_callback_html(False, str(exc), origin), status_code=400
        )

    return HTMLResponse(
        build_callback_html(
            True, "YouTube account connected. You can return to ShortMaker.", origin
        )
    )


@app.delete("/youtube/connection")
async def disconnect_youtube(user: ClerkUser = Depends(_require_app_user)):
    from .youtube_publish import clear_youtube_connection

    clear_youtube_connection(user_id=_youtube_scope_user_id(user))
    return {"success": True, "message": "Disconnected YouTube account."}


@app.post("/youtube/upload")
async def upload_short_to_youtube(
    payload: YouTubeUploadRequest,
    user: ClerkUser = Depends(_require_app_user),
):
    from .youtube_publish import upload_short

    file_path = SHORTS_DIR / _safe_filename(payload.filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Short file not found.")
    if (
        database_enabled()
        and not _is_admin_console_user(user)
        and not result_file_belongs_to_user(user.id, _safe_filename(payload.filename))
    ):
        raise HTTPException(status_code=404, detail="Short file not found.")

    try:
        result = upload_short(
            file_path=str(file_path),
            title=payload.title,
            description=payload.description,
            tags=payload.tags,
            privacy_status=payload.privacy_status,
            user_id=_youtube_scope_user_id(user),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "success": True,
        **result,
    }


@app.post("/youtube/upload/batch")
async def upload_shorts_to_youtube(
    payload: YouTubeUploadBatchRequest,
    user: ClerkUser = Depends(_require_app_user),
):
    from .youtube_publish import upload_short

    if not payload.uploads:
        raise HTTPException(
            status_code=400, detail="No shorts were provided for upload."
        )

    uploads = []
    uploaded_count = 0
    failed_count = 0

    for item in payload.uploads:
        safe_name = _safe_filename(item.filename)
        file_path = SHORTS_DIR / safe_name
        if not file_path.exists():
            uploads.append(
                {
                    "success": False,
                    "filename": item.filename,
                    "error": "Short file not found.",
                }
            )
            failed_count += 1
            continue
        if (
            database_enabled()
            and not _is_admin_console_user(user)
            and not result_file_belongs_to_user(user.id, safe_name)
        ):
            uploads.append(
                {
                    "success": False,
                    "filename": item.filename,
                    "error": "Short file not found.",
                }
            )
            failed_count += 1
            continue

        try:
            result = upload_short(
                file_path=str(file_path),
                title=item.title,
                description=item.description,
                tags=item.tags,
                privacy_status=item.privacy_status,
                user_id=_youtube_scope_user_id(user),
            )
            uploads.append(
                {
                    "success": True,
                    "filename": item.filename,
                    **result,
                }
            )
            uploaded_count += 1
        except RuntimeError as exc:
            uploads.append(
                {
                    "success": False,
                    "filename": item.filename,
                    "error": str(exc),
                }
            )
            failed_count += 1
        except HTTPException as exc:
            uploads.append(
                {
                    "success": False,
                    "filename": item.filename,
                    "error": str(exc.detail),
                }
            )
            failed_count += 1

    return {
        "success": failed_count == 0,
        "uploaded_count": uploaded_count,
        "failed_count": failed_count,
        "uploads": uploads,
    }


@app.get("/capabilities")
async def get_capabilities():
    """Expose product capabilities for dynamic frontends."""
    try:
        return _build_capabilities_payload(require_api_key=_is_api_auth_required())
    except Exception as exc:
        logger.exception("Failed to build capabilities payload.")
        raise HTTPException(
            status_code=500, detail="Failed to load capabilities."
        ) from exc


# ========================================
# Admin Console Routes
# ========================================


@app.post(f"{ADMIN_ROUTE_PREFIX}/process", response_model=ProcessResponse)
async def admin_start_processing(request: ProcessRequest):
    """Start a YouTube processing job from the admin console without API-key auth."""
    return _queue_youtube_job(request, _admin_console_user())


@app.post(f"{ADMIN_ROUTE_PREFIX}/process/upload", response_model=ProcessResponse)
async def admin_start_processing_upload(
    file: UploadFile = File(...),
    num_clips: int = Form(10),
    callback_url: Optional[str] = Form(default=None),
    callback_token: Optional[str] = Form(default=None),
    callback_auth_header: str = Form(default="X-Callback-Token"),
    public_base_url: Optional[str] = Form(default=None),
    callback_timeout_seconds: int = Form(
        default=DEFAULT_UPLOAD_CALLBACK_TIMEOUT_SECONDS
    ),
):
    return await _queue_upload_job(
        file=file,
        num_clips=num_clips,
        callback_url=callback_url,
        callback_token=callback_token,
        callback_auth_header=callback_auth_header,
        public_base_url=public_base_url,
        callback_timeout_seconds=callback_timeout_seconds,
        user=_admin_console_user(),
    )


@app.get(f"{ADMIN_ROUTE_PREFIX}/status/{{job_id}}")
async def admin_get_status(job_id: str, request: Request):
    return _get_job_payload(
        job_id, public_base_url=_resolve_public_base_url(request, ADMIN_ROUTE_PREFIX)
    )


@app.get(f"{ADMIN_ROUTE_PREFIX}/jobs/recent")
async def admin_get_recent_jobs(request: Request):
    base_url = _resolve_public_base_url(request, ADMIN_ROUTE_PREFIX)
    jobs = list_recent_jobs(public_base_url=base_url)
    return {
        "jobs": jobs,
        "count": len(jobs),
    }


@app.get(f"{ADMIN_ROUTE_PREFIX}/result/{{job_id}}")
async def admin_get_result(job_id: str, request: Request):
    return _get_completed_result_payload(
        job_id, _resolve_public_base_url(request, ADMIN_ROUTE_PREFIX)
    )


@app.post(f"{ADMIN_ROUTE_PREFIX}/trends/discover")
async def admin_discover_trends(request: TrendDiscoverRequest):
    return await discover_trends(request, _admin_console_user())


@app.post(f"{ADMIN_ROUTE_PREFIX}/trends/auto-process")
async def admin_auto_process_trend(request: TrendAutoProcessRequest):
    from .trends import auto_pick_trend_video

    admin_user = _admin_console_user()
    try:
        candidate = auto_pick_trend_video(
            topic=request.topic,
            location=request.location,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    response = _queue_youtube_job(
        ProcessRequest(
            url=candidate["url"],
            num_clips=validate_num_clips(request.num_clips),
        ),
        admin_user,
    )

    return {
        "job_id": response.job_id,
        "message": response.message,
        "candidate": candidate,
    }


@app.get(f"{ADMIN_ROUTE_PREFIX}/youtube/status")
async def admin_get_youtube_publish_status(request: Request):
    return await get_youtube_publish_status(request, _admin_console_user())


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/config")
async def admin_set_youtube_publish_config(request: YouTubeConfigRequest):
    return await set_youtube_publish_config(request, _admin_console_user())


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/auth/start")
async def admin_start_youtube_auth(request: Request):
    return await start_youtube_auth(request, _admin_console_user())


@app.delete(f"{ADMIN_ROUTE_PREFIX}/youtube/connection")
async def admin_disconnect_youtube():
    return await disconnect_youtube(_admin_console_user())


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/upload")
async def admin_upload_short_to_youtube(payload: YouTubeUploadRequest):
    return await upload_short_to_youtube(payload, _admin_console_user())


@app.post(f"{ADMIN_ROUTE_PREFIX}/youtube/upload/batch")
async def admin_upload_shorts_to_youtube(payload: YouTubeUploadBatchRequest):
    return await upload_shorts_to_youtube(payload, _admin_console_user())


@app.get(f"{ADMIN_ROUTE_PREFIX}/shorts/{{filename}}")
async def admin_download_short(filename: str):
    safe_name = _safe_filename(filename)
    file_path = SHORTS_DIR / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=str(file_path), filename=safe_name, media_type="video/mp4")


@app.get(f"{ADMIN_ROUTE_PREFIX}/capabilities")
async def admin_get_capabilities():
    payload = _build_capabilities_payload(require_api_key=False, admin_console=True)
    payload["env_has_gemini_key"] = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    payload["env_has_groq_key"] = bool(os.environ.get("GROQ_API_KEY", "").strip())
    payload["admin_route"] = ADMIN_ROUTE_PREFIX
    return payload


# ========================================
# Frontend Serving
# ========================================


def _serve_spa_index() -> FileResponse:
    if not os.path.exists(WEB_DIST_INDEX_FILE):
        raise HTTPException(status_code=404, detail="Frontend build not found.")
    return FileResponse(
        WEB_DIST_INDEX_FILE,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


if os.path.isdir(WEB_DIST_ASSETS_DIR):
    app.mount(
        "/assets", StaticFiles(directory=WEB_DIST_ASSETS_DIR), name="frontend-assets"
    )


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_frontend_root():
    return _serve_spa_index()


@app.get("/favicon.ico")
async def favicon():
    """Return empty favicon to prevent 404."""
    from fastapi.responses import Response

    return Response(content=b"", media_type="image/x-icon", status_code=204)


# ========================================
# Health Check
# ========================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        from .ai_engine import is_ai_enabled

        ai_status = is_ai_enabled()
    except:
        ai_status = False

    return {
        "status": "healthy",
        "version": "3.0.0",
        "ai_enabled": ai_status,
        "database_enabled": database_enabled(),
    }


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_frontend(full_path: str):
    # Prevent API and backend routes from being swallowed by the SPA catch-all.
    blocked_prefixes = (
        "api/",
        "ashmil2010/",
        "process",
        "status/",
        "result/",
        "jobs",
        "session",
        "capabilities",
        "youtube",
        "trends",
        "ai/",
        "auth/",
        "shorts/",
        "docs",
        "redoc",
        "openapi.json",
        "health",
        "favicon.ico",
        "assets/",
    )
    if full_path in {"health", "openapi.json", "favicon.ico"} or full_path.startswith(
        blocked_prefixes
    ):
        raise HTTPException(status_code=404)
    return _serve_spa_index()


# ========================================
# Run Server
# ========================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
