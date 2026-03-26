from __future__ import annotations

import base64
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from http.cookiejar import Cookie
from typing import Any

logger = logging.getLogger(__name__)

COOKIE_DOMAIN_SUFFIXES = (
    "youtube.com",
    "google.com",
    "googlevideo.com",
    "ytimg.com",
    "youtube-nocookie.com",
    "ggpht.com",
)
SUPPORTED_BROWSERS = ("chrome", "edge", "firefox", "brave")
DEFAULT_AUTO_SYNC_BROWSER = "chrome"
DEFAULT_AUTO_SYNC_INTERVAL_HOURS = 24
MIN_AUTO_SYNC_INTERVAL_HOURS = 1
AUTO_SYNC_LOOP_SLEEP_SECONDS = 60

AUTO_SYNC_ENABLED_KEY = "ytdlp_cookie_auto_sync_enabled"
AUTO_SYNC_BROWSER_KEY = "ytdlp_cookie_auto_sync_browser"
AUTO_SYNC_INTERVAL_HOURS_KEY = "ytdlp_cookie_auto_sync_interval_hours"
AUTO_SYNC_ON_SIGN_IN_KEY = "ytdlp_cookie_auto_sync_on_sign_in"
LAST_SYNC_AT_KEY = "ytdlp_cookie_last_synced_at"
LAST_SYNC_STATUS_KEY = "ytdlp_cookie_last_sync_status"
LAST_SYNC_ERROR_KEY = "ytdlp_cookie_last_sync_error"

_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False


def _load_config() -> dict[str, Any]:
    from .ai_engine import load_config

    return load_config()


def _save_config(config: dict[str, Any]) -> None:
    from .ai_engine import save_config

    save_config(config)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def browser_cookie_dependency_available() -> bool:
    try:
        import browser_cookie3  # noqa: F401
    except ImportError:
        return False
    return True


def _load_browser_cookie_jar(browser: str):
    try:
        import browser_cookie3
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'browser_cookie3'. Install it with "
            "`python -m pip install browser-cookie3`."
        ) from exc

    loaders = {
        "chrome": browser_cookie3.chrome,
        "edge": browser_cookie3.edge,
        "firefox": browser_cookie3.firefox,
        "brave": browser_cookie3.brave,
    }
    loader = loaders.get(browser)
    if loader is None:
        supported = ", ".join(SUPPORTED_BROWSERS)
        raise RuntimeError(f"Unsupported browser '{browser}'. Choose one of: {supported}.")
    return loader()


def _to_netscape_line(cookie: Cookie) -> str:
    domain = cookie.domain or ""
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    path = cookie.path or "/"
    secure = "TRUE" if cookie.secure else "FALSE"
    expires = str(int(cookie.expires or 0))
    name = cookie.name or ""
    value = cookie.value or ""
    return "\t".join([domain, include_subdomains, path, secure, expires, name, value])


def _cookie_jar_to_netscape(cookie_jar) -> tuple[str, int]:
    lines = ["# Netscape HTTP Cookie File"]
    seen: set[tuple[str, str, str]] = set()
    count = 0
    for cookie in cookie_jar:
        domain = (cookie.domain or "").lstrip(".").lower()
        if not any(domain.endswith(suffix) for suffix in COOKIE_DOMAIN_SUFFIXES):
            continue
        key = (cookie.domain, cookie.path, cookie.name)
        if key in seen:
            continue
        seen.add(key)
        lines.append(_to_netscape_line(cookie))
        count += 1
    if count == 0:
        raise RuntimeError("No YouTube cookies were found in the selected browser profile.")
    return "\n".join(lines) + "\n", count


def normalize_cookie_auto_sync_browser(value: Any) -> str:
    normalized = str(value or DEFAULT_AUTO_SYNC_BROWSER).strip().lower()
    if normalized in SUPPORTED_BROWSERS:
        return normalized
    return DEFAULT_AUTO_SYNC_BROWSER


def normalize_cookie_auto_sync_interval_hours(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = DEFAULT_AUTO_SYNC_INTERVAL_HOURS
    return max(MIN_AUTO_SYNC_INTERVAL_HOURS, normalized)


def get_cookie_auto_sync_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or _load_config()
    return {
        "ytdlp_cookie_auto_sync_enabled": bool(config.get(AUTO_SYNC_ENABLED_KEY, False)),
        "ytdlp_cookie_auto_sync_browser": normalize_cookie_auto_sync_browser(
            config.get(AUTO_SYNC_BROWSER_KEY)
        ),
        "ytdlp_cookie_auto_sync_interval_hours": normalize_cookie_auto_sync_interval_hours(
            config.get(AUTO_SYNC_INTERVAL_HOURS_KEY)
        ),
        "ytdlp_cookie_auto_sync_on_sign_in": bool(config.get(AUTO_SYNC_ON_SIGN_IN_KEY, False)),
        "ytdlp_cookie_last_synced_at": str(config.get(LAST_SYNC_AT_KEY) or "").strip() or None,
        "ytdlp_cookie_last_sync_status": str(config.get(LAST_SYNC_STATUS_KEY) or "").strip() or "idle",
        "ytdlp_cookie_last_sync_error": str(config.get(LAST_SYNC_ERROR_KEY) or "").strip() or None,
    }


def _store_cookie_text(config: dict[str, Any], cookie_text: str) -> None:
    config["ytdlp_cookies_base64"] = base64.b64encode(cookie_text.encode("utf-8")).decode("utf-8")


def _record_sync_success(config: dict[str, Any]) -> str:
    synced_at = _utcnow_iso()
    config[LAST_SYNC_AT_KEY] = synced_at
    config[LAST_SYNC_STATUS_KEY] = "success"
    config[LAST_SYNC_ERROR_KEY] = ""
    return synced_at


def _record_sync_failure(config: dict[str, Any], error: str) -> None:
    config[LAST_SYNC_STATUS_KEY] = "error"
    config[LAST_SYNC_ERROR_KEY] = error


def _should_run_interval_sync(config: dict[str, Any]) -> bool:
    state = get_cookie_auto_sync_state(config)
    if not state["ytdlp_cookie_auto_sync_enabled"]:
        return False

    last_synced_at = _parse_datetime(state["ytdlp_cookie_last_synced_at"])
    if last_synced_at is None:
        return True

    interval = timedelta(hours=state["ytdlp_cookie_auto_sync_interval_hours"])
    return (_utcnow() - last_synced_at) >= interval


def sync_cookies_from_browser(
    *,
    browser: str | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    config = _load_config()
    state = get_cookie_auto_sync_state(config)
    selected_browser = normalize_cookie_auto_sync_browser(browser or state["ytdlp_cookie_auto_sync_browser"])

    cookie_jar = _load_browser_cookie_jar(selected_browser)
    cookies_text, cookie_count = _cookie_jar_to_netscape(cookie_jar)
    _store_cookie_text(config, cookies_text)
    synced_at = _record_sync_success(config)
    _save_config(config)

    logger.info(
        "Synced %s YouTube cookies from %s (%s).",
        cookie_count,
        selected_browser,
        reason,
    )
    return {
        "ok": True,
        "performed": True,
        "browser": selected_browser,
        "reason": reason,
        "cookie_count": cookie_count,
        "synced_at": synced_at,
        "message": f"Imported {cookie_count} YouTube cookies from {selected_browser}.",
    }


def sync_cookies_with_status(
    *,
    browser: str | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    try:
        return sync_cookies_from_browser(browser=browser, reason=reason)
    except Exception as exc:
        config = _load_config()
        error = str(exc)
        _record_sync_failure(config, error)
        _save_config(config)
        logger.warning("Cookie sync failed (%s): %s", reason, error)
        return {
            "ok": False,
            "performed": True,
            "browser": normalize_cookie_auto_sync_browser(browser or config.get(AUTO_SYNC_BROWSER_KEY)),
            "reason": reason,
            "message": error,
            "error": error,
        }


def maybe_sync_cookies_for_sign_in() -> dict[str, Any]:
    config = _load_config()
    state = get_cookie_auto_sync_state(config)
    if not state["ytdlp_cookie_auto_sync_enabled"]:
        return {
            "ok": True,
            "performed": False,
            "message": "Automatic cookie sync is disabled.",
        }
    if not state["ytdlp_cookie_auto_sync_on_sign_in"]:
        return {
            "ok": True,
            "performed": False,
            "message": "Sign-in cookie sync is disabled.",
        }
    return sync_cookies_with_status(
        browser=state["ytdlp_cookie_auto_sync_browser"],
        reason="login",
    )


def maybe_sync_cookies_for_interval() -> dict[str, Any]:
    config = _load_config()
    state = get_cookie_auto_sync_state(config)
    if not state["ytdlp_cookie_auto_sync_enabled"]:
        return {
            "ok": True,
            "performed": False,
            "message": "Automatic cookie sync is disabled.",
        }
    if not _should_run_interval_sync(config):
        return {
            "ok": True,
            "performed": False,
            "message": "Cookie sync interval has not elapsed yet.",
        }
    return sync_cookies_with_status(
        browser=state["ytdlp_cookie_auto_sync_browser"],
        reason="interval",
    )


def _cookie_auto_sync_worker() -> None:
    logger.info("Started yt-dlp cookie auto-sync worker.")
    while True:
        try:
            maybe_sync_cookies_for_interval()
        except Exception:
            logger.exception("Unexpected cookie auto-sync worker failure")
        time.sleep(AUTO_SYNC_LOOP_SLEEP_SECONDS)


def ensure_cookie_auto_sync_worker_started() -> None:
    global _WORKER_STARTED

    if _WORKER_STARTED:
        return

    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        thread = threading.Thread(
            target=_cookie_auto_sync_worker,
            name="shortmaker-cookie-auto-sync",
            daemon=True,
        )
        thread.start()
        _WORKER_STARTED = True
