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

YT_DLP_JS_RUNTIMES = {'node': {}}
YTDLP_FORMAT = os.environ.get(
    "SHORTMAKER_YTDLP_FORMAT",
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
    "bv*[height<=1080]+ba/"
    "b[height<=1080][ext=mp4]/b[height<=1080]/best",
)
YTDLP_FALLBACK_FORMATS = [
    "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]",
    "bv*+ba/b",
    "best",
]
YTDLP_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_RETRIES", "6"))
YTDLP_FRAGMENT_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_FRAGMENT_RETRIES", "8"))
YTDLP_EXTRACTOR_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_EXTRACTOR_RETRIES", "3"))
YTDLP_SOCKET_TIMEOUT = int(os.environ.get("SHORTMAKER_YTDLP_SOCKET_TIMEOUT", "30"))
YTDLP_HTTP_CHUNK_SIZE = int(os.environ.get("SHORTMAKER_YTDLP_HTTP_CHUNK_SIZE", str(10 * 1024 * 1024)))
YTDLP_OUTER_RETRY_ATTEMPTS = int(os.environ.get("SHORTMAKER_YTDLP_OUTER_RETRY_ATTEMPTS", "3"))
YTDLP_RETRY_BACKOFF_SECONDS = float(os.environ.get("SHORTMAKER_YTDLP_RETRY_BACKOFF_SECONDS", "2.5"))
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
    provider = os.environ.get(YTDLP_POT_PROVIDER_ENV, "").strip().lower()
    if not provider:
        return {}

    player_clients = _env_csv(YTDLP_POT_PLAYER_CLIENTS_ENV, "mweb,web")
    extractor_args: dict[str, dict[str, list[str]]] = {}
    if player_clients:
        extractor_args["youtube"] = {"player_client": player_clients}

    token_ttl = os.environ.get(YTDLP_POT_TOKEN_TTL_ENV, "").strip()
    if token_ttl:
        os.environ.setdefault("TOKEN_TTL", token_ttl)

    if provider == "http":
        base_url = os.environ.get(YTDLP_POT_BASE_URL_ENV, "").strip()
        extractor_args["youtubepot-bgutilhttp"] = {"base_url": [base_url]} if base_url else {}
        return extractor_args

    if provider == "script":
        server_home = os.environ.get(YTDLP_POT_SERVER_HOME_ENV, "").strip()
        if not server_home:
            logger.warning("%s is set to script, but %s is empty", YTDLP_POT_PROVIDER_ENV, YTDLP_POT_SERVER_HOME_ENV)
            return {}
        if not Path(server_home).exists():
            logger.warning("Configured yt-dlp POT provider path does not exist: %s", server_home)
            return {}
        extractor_args["youtubepot-bgutilscript"] = {"server_home": [server_home]}
        return extractor_args

    logger.warning("Unsupported yt-dlp POT provider '%s'; continuing without PO token provider", provider)
    return {}


def _build_ydl_common_opts() -> dict:
    ydl_opts = {
        'js_runtimes': YT_DLP_JS_RUNTIMES,
        'retries': YTDLP_RETRIES,
        'fragment_retries': YTDLP_FRAGMENT_RETRIES,
        'extractor_retries': YTDLP_EXTRACTOR_RETRIES,
        'file_access_retries': 3,
        'socket_timeout': YTDLP_SOCKET_TIMEOUT,
        'http_chunk_size': YTDLP_HTTP_CHUNK_SIZE,
        'concurrent_fragment_downloads': 1,
    }
    extractor_args = _build_youtube_extractor_args()
    if extractor_args:
        ydl_opts['extractor_args'] = extractor_args
    return ydl_opts


def _clear_partial_downloads(output_dir: str, video_id: str) -> None:
    output_path = Path(output_dir)
    for candidate in output_path.glob(f"{video_id}*"):
        if candidate.suffix in {".part", ".ytdl"} or candidate.name.endswith(".mp4.part"):
            try:
                candidate.unlink()
            except OSError:
                pass


def _resolve_cookie_file() -> str | None:
    configured_path = os.environ.get(YTDLP_COOKIE_FILE_ENV, "").strip()
    if configured_path and Path(configured_path).exists():
        return configured_path

    cookie_text = os.environ.get(YTDLP_COOKIE_TEXT_ENV, "").strip()
    cookie_base64 = os.environ.get(YTDLP_COOKIE_BASE64_ENV, "").strip()

    if not cookie_text and not cookie_base64:
        try:
            from .ai_engine import load_config

            config = load_config()
            cookie_base64 = str(config.get("ytdlp_cookies_base64") or "").strip()
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
        return None

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
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        **_build_ydl_common_opts(),
    }
    cookie_file = _resolve_cookie_file()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration', 0),
            'id': info.get('id', 'unknown'),
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
    duration = info.get('duration', 0)
    
    # Check if video is too long (30 minutes = 1800 seconds)
    if duration > 1800:
        raise ValueError(f"Video is too long ({duration // 60} minutes). Maximum allowed is 30 minutes.")
    
    # Configure download options
    output_template = os.path.join(output_dir, '%(id)s.%(ext)s')
    ffmpeg_path = resolve_binary("ffmpeg", required=False)
    ffmpeg_location = str(Path(ffmpeg_path).parent) if ffmpeg_path else None
    
    ydl_opts = {
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': False,
        'no_warnings': False,
        'remote_components': ['ejs:github'],
        **_build_ydl_common_opts(),
    }
    if ffmpeg_location:
        ydl_opts['ffmpeg_location'] = ffmpeg_location
    cookie_file = _resolve_cookie_file()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    last_error = None
    for format_index, format_selector in enumerate(_build_format_candidates(), start=1):
        candidate_opts = {
            **ydl_opts,
            # Prefer the best 1080p-or-below video + audio, then broaden if unavailable.
            'format': format_selector,
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
                if "Sign in to confirm you’re not a bot" in message or "sign in to confirm" in message.lower():
                    pot_provider = os.environ.get(YTDLP_POT_PROVIDER_ENV, "").strip() or "disabled"
                    raise RuntimeError(
                        "YouTube blocked this download because it could not verify your session. "
                        "Go to Settings → YouTube Download Session and either paste fresh cookies "
                        "from your browser or click ‘Sync From Browser Now’. "
                        f"(PO token provider: {pot_provider})"
                    ) from exc
                if "Requested format is not available" in message:
                    print(
                        f"yt-dlp format '{format_selector}' unavailable for {info['id']}; "
                        f"trying fallback {format_index + 1}/{len(_build_format_candidates())}."
                    )
                    break
                if attempt >= YTDLP_OUTER_RETRY_ATTEMPTS:
                    raise
                _clear_partial_downloads(output_dir, info['id'])
                sleep_seconds = YTDLP_RETRY_BACKOFF_SECONDS * attempt
                print(
                    f"yt-dlp download attempt {attempt}/{YTDLP_OUTER_RETRY_ATTEMPTS} failed; "
                    f"retrying in {sleep_seconds:.1f}s: {exc}"
                )
                time.sleep(sleep_seconds)
        if last_error is None:
            break

    if last_error is not None:
        raise last_error
        
    # Find the downloaded file
    video_id = info['id']
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
    
    return {
        'path': video_path,
        'info': info
    }


if __name__ == "__main__":
    # Test the downloader
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    result = download_video(test_url, "./test_downloads")
    print(f"Downloaded: {result['path']}")
    print(f"Info: {result['info']}")
