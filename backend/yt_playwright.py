"""
Lightweight YouTube video downloaders as fallbacks when yt-dlp is blocked.

Priority order:
1. pytubefix — uses YouTube InnerTube API directly (no browser, no cookies)
2. Playwright — headless Chromium (heavy, needs RAM)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

YT_VIDEO_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})"
)


def extract_video_id(url: str) -> str | None:
    m = YT_VIDEO_RE.search(url)
    return m.group(1) if m else None


def download_with_pytubefix(url: str, output_dir: str) -> dict:
    """Download YouTube video using pytubefix (InnerTube API).

    This bypasses bot detection because it directly calls YouTube's
    internal API with the right client parameters, without going through
    the web interface that has bot detection.

    Returns dict with 'path', 'info'.
    """
    try:
        from pytubefix import YouTube
    except ImportError:
        raise RuntimeError("pytubefix is not installed. Run: pip install pytubefix")

    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("pytubefix: downloading %s", url)
    try:
        yt = YouTube(url, use_po_token=True)
        stream = (
            yt.streams.filter(progressive=True, file_extension="mp4")
            .order_by("resolution")
            .desc()
            .first()
        )
        if not stream:
            stream = yt.streams.filter(file_extension="mp4").first()
        if not stream:
            stream = yt.streams.get_highest_resolution()

        if not stream:
            raise RuntimeError("No suitable video stream found.")

        output_path = stream.download(
            output_path=output_dir, filename=f"{video_id}.mp4"
        )
        logger.info(
            "pytubefix: downloaded %s (%s)",
            output_path,
            stream.resolution,
        )

        return {
            "path": output_path,
            "info": {
                "title": yt.title or "Unknown",
                "id": video_id,
                "duration": yt.length or 0,
            },
        }
    except Exception as exc:
        raise RuntimeError(f"pytubefix download failed: {exc}") from exc


def is_pytubefix_available() -> bool:
    try:
        from pytubefix import YouTube

        return True
    except ImportError:
        return False


def is_playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        return True
    except ImportError:
        return False
