"""
video.py - YouTube video downloader using yt-dlp
"""

import os
import time
import yt_dlp
from pathlib import Path
from utils.binaries import ensure_ffmpeg_on_path, resolve_binary

YT_DLP_JS_RUNTIMES = {'node': {}}
YTDLP_FORMAT = os.environ.get(
    "SHORTMAKER_YTDLP_FORMAT",
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
    "bv*[height<=1080]+ba/"
    "b[height<=1080][ext=mp4]/b[height<=1080]/best",
)
YTDLP_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_RETRIES", "6"))
YTDLP_FRAGMENT_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_FRAGMENT_RETRIES", "8"))
YTDLP_EXTRACTOR_RETRIES = int(os.environ.get("SHORTMAKER_YTDLP_EXTRACTOR_RETRIES", "3"))
YTDLP_SOCKET_TIMEOUT = int(os.environ.get("SHORTMAKER_YTDLP_SOCKET_TIMEOUT", "30"))
YTDLP_HTTP_CHUNK_SIZE = int(os.environ.get("SHORTMAKER_YTDLP_HTTP_CHUNK_SIZE", str(10 * 1024 * 1024)))
YTDLP_OUTER_RETRY_ATTEMPTS = int(os.environ.get("SHORTMAKER_YTDLP_OUTER_RETRY_ATTEMPTS", "3"))
YTDLP_RETRY_BACKOFF_SECONDS = float(os.environ.get("SHORTMAKER_YTDLP_RETRY_BACKOFF_SECONDS", "2.5"))

ensure_ffmpeg_on_path()


def _build_ydl_common_opts() -> dict:
    return {
        'js_runtimes': YT_DLP_JS_RUNTIMES,
        'retries': YTDLP_RETRIES,
        'fragment_retries': YTDLP_FRAGMENT_RETRIES,
        'extractor_retries': YTDLP_EXTRACTOR_RETRIES,
        'file_access_retries': 3,
        'socket_timeout': YTDLP_SOCKET_TIMEOUT,
        'http_chunk_size': YTDLP_HTTP_CHUNK_SIZE,
        'concurrent_fragment_downloads': 1,
    }


def _clear_partial_downloads(output_dir: str, video_id: str) -> None:
    output_path = Path(output_dir)
    for candidate in output_path.glob(f"{video_id}*"):
        if candidate.suffix in {".part", ".ytdl"} or candidate.name.endswith(".mp4.part"):
            try:
                candidate.unlink()
            except OSError:
                pass


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
    ffmpeg_path = resolve_binary("ffmpeg", required=True)
    
    ydl_opts = {
        # Prefer the best 1080p-or-below video + audio, then merge back to mp4.
        'format': YTDLP_FORMAT,
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': False,
        'no_warnings': False,
        'remote_components': ['ejs:github'],
        **_build_ydl_common_opts(),
    }
    ydl_opts['ffmpeg_location'] = ffmpeg_path

    last_error = None
    for attempt in range(1, YTDLP_OUTER_RETRY_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            last_error = None
            break
        except yt_dlp.utils.DownloadError as exc:
            last_error = exc
            if attempt >= YTDLP_OUTER_RETRY_ATTEMPTS:
                raise
            _clear_partial_downloads(output_dir, info['id'])
            sleep_seconds = YTDLP_RETRY_BACKOFF_SECONDS * attempt
            print(
                f"yt-dlp download attempt {attempt}/{YTDLP_OUTER_RETRY_ATTEMPTS} failed; "
                f"retrying in {sleep_seconds:.1f}s: {exc}"
            )
            time.sleep(sleep_seconds)

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
