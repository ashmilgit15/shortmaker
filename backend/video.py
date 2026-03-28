"""
video.py - YouTube video downloader using yt-dlp
"""

import base64
import logging
import os
import tempfile
import time
import yt_dlp
from pathlib import Path
from utils.binaries import ensure_ffmpeg_on_path, resolve_binary

logger = logging.getLogger(__name__)

YT_DLP_JS_RUNTIMES = {"node": {"timeout": 30}}
YTDLP_FORMAT = os.environ.get(
    "SHORTMAKER_YTDLP_FORMAT",
    "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
)
YTDLP_FALLBACK_FORMATS = [
    "bestvideo+bestaudio/best",
    "best",
]
YTDLP_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_RETRIES", "6"))
YTDLP_FRAGMENT_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_FRAGMENT_RETRIES", "8"))
YTDLP_EXTRACTOR_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_EXTRACTOR_RETRIES", "3"))
YTDLP_SOCKET_TIMEOUT = int(os.environ.get("SHORTMAKER_YTDLP_SOCKET_TIMEOUT", "30"))
YTDLP_HTTP_CHUNK_SIZE = int(
    os.environ.get("SHORTMAKER_YTDLP_HTTP_CHUNK_SIZE", str(10 * 1024 * 1024))
)
YTDLP_OUTER_RETRY_ATTEMPTS = int(
    os.environ.get("SHORTMAKER_YTDLP_OUTER_RETRY_ATTEMPTS", "3")
)
YTDLP_RETRY_BACKOFF_SECONDS = float(
    os.environ.get("SHORTMAKER_YTDLP_RETRY_BACKOFF_SECONDS", "2.5")
)
YTDLP_COOKIE_FILE_ENV = "SHORTMAKER_YTDLP_COOKIES_FILE"
YTDLP_COOKIE_TEXT_ENV = "SHORTMAKER_YTDLP_COOKIES"
YTDLP_COOKIE_BASE64_ENV = "SHORTMAKER_YTDLP_COOKIES_BASE64"
YTDLP_POT_PROVIDER_ENV = "SHORTMAKER_YTDLP_POT_PROVIDER"
YTDLP_POT_BASE_URL_ENV = "SHORTMAKER_YTDLP_POT_BASE_URL"
YTDLP_POT_SERVER_HOME_ENV = "SHORTMAKER_YTDLP_POT_SERVER_HOME"
YTDLP_POT_PLAYER_CLIENTS_ENV = "SHORTMAKER_YTDLP_POT_PLAYER_CLIENTS"
YTDLP_POT_TOKEN_TTL_ENV = "SHORTMAKER_YTDLP_POT_TOKEN_TTL"

ensure_ffmpeg_on_path()


def _env_csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _build_youtube_extractor_args() -> dict:
    # Resolve PO token provider: env var takes priority, then config file
    provider = os.environ.get(YTDLP_POT_PROVIDER_ENV, "").strip().lower()
    config_pot: dict = {}
    if not provider:
        try:
            from .ai_engine import load_config

            config_pot = load_config()
            provider = str(config_pot.get("ytdlp_pot_provider", "")).strip().lower()
        except Exception:
            pass

    # Always set player clients that work well with or without PO tokens
    # tv_embedded and android_embedded often bypass bot detection without tokens
    player_clients_raw = os.environ.get(YTDLP_POT_PLAYER_CLIENTS_ENV, "").strip()
    if not player_clients_raw and config_pot:
        player_clients_raw = str(config_pot.get("ytdlp_pot_player_clients", "")).strip()
    player_clients = [
        c.strip()
        for c in (player_clients_raw or "web_creator,web").split(",")
        if c.strip()
    ]

    extractor_args: dict[str, dict[str, list[str]]] = {}
    if player_clients:
        extractor_args["youtube"] = {"player_client": player_clients}

    if not provider:
        # No PO Token provider — rely on player clients alone
        logger.info("No PO Token provider — using player clients: %s", player_clients)
        return extractor_args

    token_ttl = os.environ.get(YTDLP_POT_TOKEN_TTL_ENV, "").strip()
    if token_ttl:
        os.environ.setdefault("TOKEN_TTL", token_ttl)

    if provider == "http":
        base_url = os.environ.get(YTDLP_POT_BASE_URL_ENV, "").strip()
        if not base_url and config_pot:
            base_url = str(config_pot.get("ytdlp_pot_base_url", "")).strip()
        extractor_args["youtubepot-bgutilhttp"] = (
            {"base_url": [base_url]} if base_url else {}
        )
        logger.info(
            "PO Token: HTTP provider at %s, clients: %s",
            base_url or "(default)",
            player_clients,
        )
        return extractor_args

    if provider == "script":
        server_home = os.environ.get(YTDLP_POT_SERVER_HOME_ENV, "").strip()
        if not server_home:
            logger.warning(
                "%s is set to script, but %s is empty",
                YTDLP_POT_PROVIDER_ENV,
                YTDLP_POT_SERVER_HOME_ENV,
            )
            return extractor_args  # return with player clients only
        if not Path(server_home).exists():
            logger.warning(
                "Configured yt-dlp POT provider path does not exist: %s", server_home
            )
            return extractor_args  # return with player clients only
        extractor_args["youtubepot-bgutilscript"] = {"server_home": [server_home]}
        logger.info(
            "PO Token: script provider at %s, clients: %s",
            server_home,
            player_clients,
        )
        return extractor_args

    logger.warning(
        "Unsupported yt-dlp POT provider '%s'; using player clients only",
        provider,
    )
    return extractor_args


def _build_ydl_common_opts() -> dict:
    ydl_opts = {
        "js_runtimes": YT_DLP_JS_RUNTIMES,
        "retries": YTDLP_RETRIES,
        "fragment_retries": YTDLP_FRAGMENT_RETRIES,
        "extractor_retries": YTDLP_EXTRACTOR_RETRIES,
        "file_access_retries": 3,
        "socket_timeout": YTDLP_SOCKET_TIMEOUT,
        "http_chunk_size": YTDLP_HTTP_CHUNK_SIZE,
        "concurrent_fragment_downloads": 1,
    }
    extractor_args = _build_youtube_extractor_args()
    if extractor_args:
        ydl_opts["extractor_args"] = extractor_args
        logger.info("PO Token provider configured: %s", list(extractor_args.keys()))
    else:
        logger.warning(
            "No PO Token provider configured — downloads may be blocked by YouTube bot detection."
        )

    # OAuth2 support via yt-dlp-youtube-oauth2 plugin
    try:
        from .ai_engine import load_config

        config = load_config()
        if config.get("ytdlp_oauth2_enabled", False):
            ydl_opts["username"] = "oauth2"
            ydl_opts["password"] = ""
    except Exception:
        pass

    return ydl_opts


def _clear_partial_downloads(output_dir: str, video_id: str) -> None:
    output_path = Path(output_dir)
    for candidate in output_path.glob(f"{video_id}*"):
        if candidate.suffix in {".part", ".ytdl"} or candidate.name.endswith(
            ".mp4.part"
        ):
            try:
                candidate.unlink()
            except OSError:
                pass


def _build_bot_detection_error(original_exc: Exception) -> RuntimeError:
    """Build a diagnostic RuntimeError after all player client fallbacks fail."""
    auth_methods = []
    suggestion = ""
    try:
        from .ai_engine import load_config

        config = load_config()
    except Exception:
        config = {}

    has_cookies = bool(_resolve_cookie_file())
    oauth2_enabled = bool(config.get("ytdlp_oauth2_enabled", False))
    pot_provider = (
        os.environ.get(YTDLP_POT_PROVIDER_ENV, "").strip()
        or str(config.get("ytdlp_pot_provider", "")).strip()
        or "disabled"
    )

    if has_cookies:
        auth_methods.append("Cookies (configured)")
    else:
        auth_methods.append("Cookies (not set)")

    pot_healthy = pot_provider != "disabled"
    if pot_provider == "http":
        try:
            import urllib.request

            pot_base = (
                os.environ.get(YTDLP_POT_BASE_URL_ENV, "").strip()
                or str(config.get("ytdlp_pot_base_url", "")).strip()
            )
            if pot_base:
                req = urllib.request.Request(
                    pot_base.rstrip("/") + "/ping", method="GET"
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    pot_healthy = resp.status == 200
        except Exception:
            pot_healthy = False

    if pot_healthy:
        auth_methods.append(f"PO Token ({pot_provider})")
    elif pot_provider != "disabled":
        auth_methods.append(f"PO Token ({pot_provider}, server unreachable)")
    else:
        auth_methods.append("PO Token (disabled)")

    if not has_cookies and not pot_healthy:
        suggestion = (
            "YouTube is blocking downloads from this server. "
            "To fix this, the admin needs to run the cookie sync script from a local machine:\n\n"
            "  pip install httpx\n"
            "  python scripts/cookie_auto_sync.py --base-url https://your-app.onrender.com\n\n"
            "This reads YouTube cookies from Firefox and uploads them to the server. "
            "Run it once to set up, then it syncs automatically every hour."
        )
    elif not has_cookies:
        suggestion = (
            "PO Token provider is active but may not fully bypass bot detection. "
            "For best reliability, also set browser cookies via the "
            "SHORTMAKER_YTDLP_COOKIES_BASE64 environment variable."
        )
    elif not pot_healthy:
        suggestion = (
            "Cookies are set but may be expired. Refresh them from your local browser, "
            "or set up a PO Token provider as a backup."
        )
    else:
        suggestion = (
            "All auth methods are configured but YouTube still blocked the download. "
            "Your cookies may have expired — try refreshing them from your local browser."
        )

    return RuntimeError(
        "YouTube blocked this download after trying all available player clients. "
        f"Active auth: {', '.join(auth_methods)}. {suggestion}"
    )


YTDLP_AUTH_COOKIE_NAMES = frozenset(
    {
        "LOGIN_INFO",
        "SID",
        "HSID",
        "SSID",
        "SAPISID",
        "APISID",
        "__Secure-3PSID",
        "__Secure-3PAPISID",
        "__Secure-3PSIDCC",
    }
)


def _validate_cookie_auth(cookie_text: str) -> None:
    """Check if cookie text contains critical YouTube auth cookies.

    Logs warnings if auth cookies appear missing or expired, which helps
    diagnose "Sign in to confirm you're not a bot" errors.
    """
    cookie_lines = [
        ln
        for ln in cookie_text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not cookie_lines:
        return

    found_names: set[str] = set()
    for line in cookie_lines:
        parts = line.split("\t")
        if len(parts) >= 7:
            found_names.add(parts[5])

    auth_found = found_names & YTDLP_AUTH_COOKIE_NAMES
    if not auth_found:
        logger.warning(
            "Cookie file has %d cookies but none are YouTube auth cookies "
            "(LOGIN_INFO, SID, SAPISID, etc.). Downloads will likely be "
            "blocked. Make sure you exported cookies from a signed-in "
            "YouTube session.",
            len(cookie_lines),
        )
    else:
        logger.info(
            "Cookie file contains %d cookies including auth tokens: %s",
            len(cookie_lines),
            ", ".join(sorted(auth_found)),
        )


def _resolve_cookie_file() -> str | None:
    configured_path = os.environ.get(YTDLP_COOKIE_FILE_ENV, "").strip()
    if configured_path and Path(configured_path).exists():
        logger.info("Using cookie file from env var: %s", configured_path)
        return configured_path

    cookie_text = os.environ.get(YTDLP_COOKIE_TEXT_ENV, "").strip()
    cookie_base64 = os.environ.get(YTDLP_COOKIE_BASE64_ENV, "").strip()
    source = "env"

    if not cookie_text and not cookie_base64:
        try:
            from .ai_engine import load_config

            config = load_config()
            cookie_base64 = str(config.get("ytdlp_cookies_base64") or "").strip()
            source = "config"
        except Exception:
            cookie_base64 = ""

    if not cookie_text and cookie_base64:
        try:
            cookie_text = base64.b64decode(cookie_base64).decode("utf-8")
        except Exception as exc:
            raise RuntimeError(
                f"{YTDLP_COOKIE_BASE64_ENV} is not valid base64-encoded Netscape cookies text."
            ) from exc

    if not cookie_text:
        logger.warning(
            "No YouTube cookies found — downloads may be blocked by bot detection."
        )
        return None

    # Ensure the cookie text starts with the Netscape header. yt-dlp silently
    # ignores cookie files that lack it, which makes pasted cookies appear to
    # work (no error) while actually sending zero cookies.
    if not cookie_text.lstrip().startswith("# Netscape HTTP Cookie File"):
        cookie_text = "# Netscape HTTP Cookie File\n" + cookie_text

    # Count actual cookie lines (non-blank, non-comment)
    cookie_lines = [
        ln
        for ln in cookie_text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    logger.info(
        "Resolved %d cookie line(s) from %s; writing temp cookie file.",
        len(cookie_lines),
        source,
    )
    if len(cookie_lines) == 0:
        logger.warning("Cookie text is present but contains 0 actual cookie lines!")
    else:
        _validate_cookie_auth(cookie_text)

    runtime_dir = Path(tempfile.gettempdir()) / "shortmaker"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cookie_path = runtime_dir / "yt-dlp-cookies.txt"
    cookie_path.write_text(cookie_text, encoding="utf-8")
    return str(cookie_path)


def _build_format_candidates() -> list[str]:
    candidates: list[str] = []
    for candidate in [YTDLP_FORMAT, *YTDLP_FALLBACK_FORMATS]:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def get_video_info(url: str) -> dict:
    """
    Get video metadata without downloading.
    Returns: dict with title, duration, etc.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        **_build_ydl_common_opts(),
    }
    cookie_file = _resolve_cookie_file()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "id": info.get("id", "unknown"),
        }


def download_video(url: str, output_dir: str) -> dict:
    """
    Download a YouTube video.

    Args:
        url: YouTube video URL
        output_dir: Directory to save the video

    Returns:
        dict with 'path' (file path) and 'info' (video metadata)

    Raises:
        ValueError: If video is too long (> 30 minutes)
    """
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # First, get video info to check duration
    info = get_video_info(url)
    duration = info.get("duration", 0)

    # Check if video is too long (30 minutes = 1800 seconds)
    if duration > 1800:
        raise ValueError(
            f"Video is too long ({duration // 60} minutes). Maximum allowed is 30 minutes."
        )

    # Configure download options
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")
    ffmpeg_path = resolve_binary("ffmpeg", required=False)
    ffmpeg_location = str(Path(ffmpeg_path).parent) if ffmpeg_path else None

    ydl_opts = {
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "remote_components": ["ejs:github"],
        **_build_ydl_common_opts(),
    }
    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location
    cookie_file = _resolve_cookie_file()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    last_error = None
    for format_index, format_selector in enumerate(_build_format_candidates(), start=1):
        candidate_opts = {
            **ydl_opts,
            # Prefer the best 1080p-or-below video + audio, then broaden if unavailable.
            "format": format_selector,
        }
        for attempt in range(1, YTDLP_OUTER_RETRY_ATTEMPTS + 1):
            try:
                with yt_dlp.YoutubeDL(candidate_opts) as ydl:
                    ydl.download([url])
                last_error = None
                break
            except yt_dlp.utils.DownloadError as exc:
                last_error = exc
                message = str(exc)
                if (
                    "Sign in to confirm you're not a bot" in message
                    or "sign in to confirm" in message.lower()
                ):
                    # Try alternative player clients before giving up
                    _clear_partial_downloads(output_dir, info["id"])

                    # Round 1: Try fallback clients WITH PO Token provider
                    fallback_clients = [
                        "web_creator",
                        "web_music",
                        "tv_embedded",
                        "android_vr",
                        "android_embedded",
                        "ios",
                        "web_embedded",
                        "mweb",
                    ]
                    bot_bypassed = False
                    for client_name in fallback_clients:
                        logger.info(
                            "Bot detection triggered — retrying with player client: %s",
                            client_name,
                        )
                        retry_opts = {**candidate_opts}
                        retry_ea = dict(retry_opts.get("extractor_args") or {})
                        retry_ea["youtube"] = {"player_client": [client_name]}
                        retry_opts["extractor_args"] = retry_ea
                        try:
                            _clear_partial_downloads(output_dir, info["id"])
                            with yt_dlp.YoutubeDL(retry_opts) as ydl:
                                ydl.download([url])
                            logger.info(
                                "Bot detection bypassed using player client: %s",
                                client_name,
                            )
                            bot_bypassed = True
                            last_error = None
                            break
                        except yt_dlp.utils.DownloadError:
                            continue

                    # Round 2: Nuclear fallback — try clients WITHOUT
                    # any PO Token provider (some work without tokens)
                    if not bot_bypassed:
                        bare_clients = [
                            "web_creator",
                            "tv_embedded",
                            "android_embedded",
                        ]
                        for client_name in bare_clients:
                            logger.info(
                                "Bot detection still active — "
                                "trying bare %s client (no PO Token)...",
                                client_name,
                            )
                            retry_opts = {
                                **candidate_opts,
                                "extractor_args": {
                                    "youtube": {"player_client": [client_name]}
                                },
                            }
                            # Remove PO Token extractor args for bare retry
                            retry_opts.pop("extractor_args", None)
                            retry_opts["extractor_args"] = {
                                "youtube": {"player_client": [client_name]}
                            }
                            try:
                                _clear_partial_downloads(output_dir, info["id"])
                                with yt_dlp.YoutubeDL(retry_opts) as ydl:
                                    ydl.download([url])
                                logger.info(
                                    "Bot detection bypassed using bare %s client!",
                                    client_name,
                                )
                                bot_bypassed = True
                                last_error = None
                                break
                            except yt_dlp.utils.DownloadError:
                                continue

                    if bot_bypassed:
                        break
                    # All fallback clients failed — raise with diagnostic info
                    raise _build_bot_detection_error(exc)
                if "Requested format is not available" in message:
                    print(
                        f"yt-dlp format '{format_selector}' unavailable for {info['id']}; "
                        f"trying fallback {format_index + 1}/{len(_build_format_candidates())}."
                    )
                    break
                if attempt >= YTDLP_OUTER_RETRY_ATTEMPTS:
                    raise
                _clear_partial_downloads(output_dir, info["id"])
                sleep_seconds = YTDLP_RETRY_BACKOFF_SECONDS * attempt
                print(
                    f"yt-dlp download attempt {attempt}/{YTDLP_OUTER_RETRY_ATTEMPTS} failed; "
                    f"retrying in {sleep_seconds:.1f}s: {exc}"
                )
                time.sleep(sleep_seconds)
        if last_error is None:
            break

    if last_error is not None:
        # All yt-dlp attempts failed — try fallbacks
        # 1. pytubefix (lightweight InnerTube API)
        try:
            from .yt_playwright import is_pytubefix_available, download_with_pytubefix

            if is_pytubefix_available():
                logger.warning("yt-dlp failed — attempting pytubefix download...")
                return download_with_pytubefix(url, output_dir)
        except ImportError:
            pass
        except Exception as pt_exc:
            logger.error("pytubefix download failed: %s", pt_exc)

        # 2. Playwright (heavy, needs RAM)
        try:
            from .yt_playwright import is_playwright_available, download_with_playwright

            if is_playwright_available():
                logger.warning(
                    "pytubefix failed — attempting Playwright browser download..."
                )
                return download_with_playwright(url, output_dir)
        except ImportError:
            pass
        except Exception as pw_exc:
            logger.error("Playwright download failed: %s", pw_exc)

        raise last_error

    # Find the downloaded file
    video_id = info["id"]
    video_path = os.path.join(output_dir, f"{video_id}.mp4")

    # Sometimes yt-dlp uses webm, check for it
    if not os.path.exists(video_path):
        webm_path = os.path.join(output_dir, f"{video_id}.webm")
        if os.path.exists(webm_path):
            video_path = webm_path
        else:
            # Find any file with the video ID
            for f in os.listdir(output_dir):
                if video_id in f:
                    video_path = os.path.join(output_dir, f)
                    break

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Downloaded video not found at {video_path}")

    return {"path": video_path, "info": info}


if __name__ == "__main__":
    # Test the downloader
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    result = download_video(test_url, "./test_downloads")
    print(f"Downloaded: {result['path']}")
    print(f"Info: {result['info']}")
