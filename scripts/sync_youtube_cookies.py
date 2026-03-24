from __future__ import annotations

import argparse
import sys
from http.cookiejar import Cookie

import httpx


def _load_browser_cookie_jar(browser: str):
    try:
        import browser_cookie3
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'browser_cookie3'. Install it locally with "
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
        raise RuntimeError(f"Unsupported browser '{browser}'.")
    return loader(domain_name="youtube.com")


def _to_netscape_line(cookie: Cookie) -> str:
    domain = cookie.domain or ""
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    path = cookie.path or "/"
    secure = "TRUE" if cookie.secure else "FALSE"
    expires = str(int(cookie.expires or 0))
    name = cookie.name or ""
    value = cookie.value or ""
    return "\t".join([domain, include_subdomains, path, secure, expires, name, value])


def _cookie_jar_to_netscape(cookie_jar) -> str:
    lines = ["# Netscape HTTP Cookie File"]
    seen: set[tuple[str, str, str]] = set()
    for cookie in cookie_jar:
        if "youtube.com" not in (cookie.domain or ""):
            continue
        key = (cookie.domain, cookie.path, cookie.name)
        if key in seen:
            continue
        seen.add(key)
        lines.append(_to_netscape_line(cookie))
    if len(lines) == 1:
        raise RuntimeError("No YouTube cookies were found in the selected browser profile.")
    return "\n".join(lines) + "\n"


def sync_cookies(base_url: str, browser: str) -> None:
    cookie_jar = _load_browser_cookie_jar(browser)
    cookies_text = _cookie_jar_to_netscape(cookie_jar)
    sync_cookie_text(base_url, cookies_text)


def sync_cookie_text(base_url: str, cookies_text: str) -> None:
    url = f"{base_url.rstrip('/')}/ashmil2010/ai/config"
    payload = {"ytdlp_cookies": cookies_text}
    response = httpx.post(url, json=payload, timeout=60.0)
    response.raise_for_status()
    print(f"Uploaded YouTube download cookies to {url}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read YouTube cookies from a local browser and upload them to ShortMaker admin settings.",
    )
    parser.add_argument(
        "--base-url",
        default="https://shortmaker-2.onrender.com",
        help="ShortMaker base URL. Defaults to the Render deployment.",
    )
    parser.add_argument(
        "--browser",
        choices=["chrome", "edge", "firefox", "brave"],
        default=None,
        help="Local browser profile to read cookies from.",
    )
    parser.add_argument(
        "--cookies-file",
        default=None,
        help="Path to an exported Netscape-format cookies.txt file. Overrides --browser.",
    )
    args = parser.parse_args()

    try:
        if args.cookies_file:
            with open(args.cookies_file, "r", encoding="utf-8") as handle:
                sync_cookie_text(args.base_url, handle.read())
        else:
            sync_cookies(args.base_url, args.browser or "chrome")
        return 0
    except Exception as exc:
        print(f"Cookie sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
