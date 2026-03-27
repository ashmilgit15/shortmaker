"""
Sync YouTube cookies from local Firefox to ShortMaker.

Two modes:
  1. Upload via API (default):  python scripts/cookie_auto_sync.py
  2. Output base64 for env var: python scripts/cookie_auto_sync.py --print-base64

For Render deployment, use mode 2 and paste the output into
SHORTMAKER_YTDLP_COOKIES_BASE64 env var in Render dashboard.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

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
        raise RuntimeError("No Firefox profiles found.")

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
        raise RuntimeError("No YouTube cookies found in Firefox.")
    return "\n".join(lines) + "\n"


def count_auth_cookies(cookies_text: str) -> int:
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
        description="Sync YouTube cookies from Firefox to ShortMaker.",
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
        help="Sync once and exit.",
    )
    parser.add_argument(
        "--print-base64",
        action="store_true",
        help="Print base64-encoded cookies for env var (don't upload).",
    )
    args = parser.parse_args()

    profiles = find_firefox_profiles()
    if not profiles:
        logger.error(
            "No Firefox profiles found. Install Firefox and sign in to YouTube."
        )
        return 1

    logger.info("Found %d Firefox profile(s).", len(profiles))

    while True:
        try:
            cookies_text = read_firefox_cookies()
            auth_count = count_auth_cookies(cookies_text)
            total_lines = sum(
                1
                for l in cookies_text.splitlines()
                if l.strip() and not l.startswith("#")
            )
            logger.info(
                "Read %d YouTube cookies (%d auth tokens).", total_lines, auth_count
            )

            if auth_count == 0:
                logger.warning(
                    "No YouTube auth cookies — sign in to YouTube in Firefox first."
                )
                return 1

            if args.print_base64:
                b64 = base64.b64encode(cookies_text.encode("utf-8")).decode("utf-8")
                print("\n" + "=" * 60)
                print("COPY THIS VALUE into SHORTMAKER_YTDLP_COOKIES_BASE64")
                print("in your Render dashboard environment variables:")
                print("=" * 60)
                print(b64)
                print("=" * 60)
                print(
                    f"\n({len(b64)} characters, {total_lines} cookies, {auth_count} auth tokens)"
                )
                return 0

            import httpx

            url = f"{args.base_url.rstrip('/')}/ashmil2010/ai/config"
            response = httpx.post(
                url,
                json={"ytdlp_cookies": cookies_text},
                timeout=60.0,
            )
            response.raise_for_status()
            logger.info("Cookies uploaded to %s.", args.base_url)
        except Exception as exc:
            logger.error("Sync failed: %s", exc)

        if args.once:
            break

        logger.info("Next sync in %d minutes...", args.interval)
        time.sleep(args.interval * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
