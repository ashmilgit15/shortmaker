"""
Auto-sync YouTube cookies from local Firefox to your ShortMaker server.

Run this on a machine that has Firefox with YouTube logged in.
It reads cookies from Firefox every hour and uploads them to the server.

Usage:
    python scripts/cookie_auto_sync.py --base-url https://shortmaker-2.onrender.com
    python scripts/cookie_auto_sync.py --base-url https://shortmaker-2.onrender.com --interval 30
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="[cookie-sync] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COOKIE_DOMAIN_SUFFIXES = (
    "youtube.com",
    "google.com",
    "googlevideo.com",
    "ytimg.com",
    "youtube-nocookie.com",
    "ggpht.com",
)


def find_firefox_profiles() -> list[Path]:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"
    else:
        base = Path.home() / ".mozilla" / "firefox"
    if not base.exists():
        return []
    return [p for p in base.iterdir() if p.is_dir() and (p / "cookies.sqlite").exists()]


def read_firefox_cookies() -> str:
    profiles = find_firefox_profiles()
    if not profiles:
        raise RuntimeError(
            "No Firefox profiles found. Make sure Firefox is installed and you've visited YouTube."
        )

    lines = ["# Netscape HTTP Cookie File"]
    seen: set[tuple[str, str, str]] = set()
    count = 0

    for profile_dir in profiles:
        db_path = profile_dir / "cookies.sqlite"
        tmp_db = Path(tempfile.mktemp(suffix=".sqlite"))
        try:
            shutil.copy2(db_path, tmp_db)
        except OSError:
            continue

        try:
            conn = sqlite3.connect(str(tmp_db))
            try:
                rows = conn.execute(
                    "SELECT host, path, isSecure, expiry, name, value, isHttpOnly "
                    "FROM moz_cookies"
                ).fetchall()
            finally:
                conn.close()

            for host, path, is_secure, expiry, name, value, is_httponly in rows:
                domain = host or ""
                domain_lower = domain.lstrip(".").lower()
                if not any(domain_lower.endswith(s) for s in COOKIE_DOMAIN_SUFFIXES):
                    continue
                key = (domain, path, name)
                if key in seen:
                    continue
                seen.add(key)

                include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
                secure = "TRUE" if is_secure else "FALSE"
                expires = str(int(expiry or 0))
                prefix = "#HttpOnly_" if is_httponly else ""
                lines.append(
                    f"{prefix}{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}"
                )
                count += 1
        finally:
            try:
                tmp_db.unlink()
            except OSError:
                pass

    if count == 0:
        raise RuntimeError(
            "No YouTube cookies found in Firefox. Open YouTube in Firefox and sign in."
        )
    return "\n".join(lines) + "\n"


def upload_cookies(base_url: str, cookies_text: str) -> bool:
    url = f"{base_url.rstrip('/')}/ashmil2010/ai/config"
    try:
        response = httpx.post(url, json={"ytdlp_cookies": cookies_text}, timeout=60.0)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Upload failed: %s", exc)
        return False


def count_youtube_auth_cookies(cookies_text: str) -> int:
    auth_names = {
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
    count = 0
    for line in cookies_text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5] in auth_names:
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto-sync YouTube cookies from Firefox to ShortMaker server.",
    )
    parser.add_argument(
        "--base-url",
        default="https://shortmaker-2.onrender.com",
        help="ShortMaker server URL.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Sync interval in minutes (default: 60).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Sync once and exit (don't loop).",
    )
    args = parser.parse_args()

    profiles = find_firefox_profiles()
    if not profiles:
        logger.error(
            "No Firefox profiles found. Install Firefox, sign in to YouTube, then run this script."
        )
        return 1

    logger.info("Found %d Firefox profile(s).", len(profiles))
    logger.info("Server: %s", args.base_url)
    logger.info("Interval: %d minutes", args.interval)

    while True:
        try:
            cookies_text = read_firefox_cookies()
            auth_count = count_youtube_auth_cookies(cookies_text)
            logger.info(
                "Read %d YouTube cookies (%d auth tokens).",
                cookies_text.count("\n"),
                auth_count,
            )

            if auth_count == 0:
                logger.warning(
                    "No YouTube auth cookies found. Make sure you're signed in to YouTube in Firefox."
                )

            if upload_cookies(args.base_url, cookies_text):
                logger.info("Cookies uploaded successfully to %s.", args.base_url)
            else:
                logger.error("Failed to upload cookies.")
        except Exception as exc:
            logger.error("Sync failed: %s", exc)

        if args.once:
            break

        logger.info("Next sync in %d minutes...", args.interval)
        time.sleep(args.interval * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
