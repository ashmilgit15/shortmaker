"""
Playwright-based YouTube video downloader.

Uses a real Chromium browser to visit YouTube, which bypasses bot detection
because it runs JavaScript, WebGL, canvas fingerprinting, etc. just like
a real user's browser.

This is the nuclear option when yt-dlp fails with bot detection.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

YT_VIDEO_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})"
)


def extract_video_id(url: str) -> str | None:
    m = YT_VIDEO_RE.search(url)
    return m.group(1) if m else None


def is_playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        return True
    except ImportError:
        return False


def download_with_playwright(
    url: str,
    output_dir: str,
    *,
    max_wait_seconds: int = 60,
) -> dict:
    """Download a YouTube video using Playwright headless browser.

    Visits the YouTube page, waits for the player to load, then extracts
    the video stream URL from the page's network requests and downloads it.

    Returns dict with 'path', 'info', 'title'.
    Raises RuntimeError if download fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Install with: pip install playwright && playwright install chromium"
        )

    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    video_urls: list[str] = []
    video_title = "Unknown"
    video_duration = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # Intercept video stream URLs
        def handle_response(response):
            nonlocal video_title
            req_url = response.url
            if "googlevideo.com" in req_url and "videoplayback" in req_url:
                content_type = response.headers.get("content-type", "")
                if "video" in content_type or "audio" in content_type:
                    video_urls.append(req_url)

        page.on("response", handle_response)

        logger.info("Playwright: navigating to %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            logger.warning("Playwright goto warning: %s", exc)

        # Wait for video player to start
        time.sleep(5)

        # Get video title
        try:
            title_el = page.query_selector(
                "h1.ytd-watch-metadata yt-formatted-string, h1.title"
            )
            if title_el:
                video_title = title_el.inner_text().strip() or "Unknown"
        except Exception:
            pass

        # Try to click play button if video hasn't started
        try:
            play_btn = page.query_selector("button.ytp-play-button")
            if play_btn:
                play_btn.click()
                time.sleep(3)
        except Exception:
            pass

        # Wait for video URLs to be captured
        waited = 5
        while not video_urls and waited < max_wait_seconds:
            time.sleep(2)
            waited += 2

        browser.close()

    if not video_urls:
        raise RuntimeError(
            "Playwright could not capture any video stream URLs from YouTube. "
            "The video might be restricted or the page didn't load properly."
        )

    # Download the best video stream
    import httpx

    best_url = video_urls[-1]  # Usually the last intercepted URL is the best quality
    output_path = os.path.join(output_dir, f"{video_id}.mp4")

    logger.info(
        "Playwright: downloading video stream (%d URLs captured)", len(video_urls)
    )
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        with client.stream("GET", best_url) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

    file_size = os.path.getsize(output_path)
    if file_size < 100_000:  # Less than 100KB is probably not a real video
        os.remove(output_path)
        raise RuntimeError("Downloaded file is too small — likely not a valid video.")

    logger.info(
        "Playwright: downloaded %s (%.1f MB)",
        output_path,
        file_size / (1024 * 1024),
    )

    return {
        "path": output_path,
        "info": {"title": video_title, "id": video_id, "duration": video_duration},
    }
