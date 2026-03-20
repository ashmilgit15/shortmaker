"""
trends.py - Discover trend-aligned YouTube source videos using Firecrawl.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from utils.env_loader import load_dotenv_file

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
CLERK_RUNTIME_KEYS = ("CLERK_ISSUER", "CLERK_AUDIENCE", "CLERK_JWKS_URL")
load_dotenv_file(BASE_DIR / ".env", override_keys=CLERK_RUNTIME_KEYS, clear_missing_keys=CLERK_RUNTIME_KEYS)

FIRECRAWL_BASE_URL = os.environ.get("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev").rstrip("/")
FIRECRAWL_SEARCH_ENDPOINT = f"{FIRECRAWL_BASE_URL}/v2/search"
TREND_QUERY_LIMIT = 4
FIRECRAWL_SEARCH_TIMEOUT_MS = 20_000
TREND_QUERY_TEMPLATES = (
    'site:youtube.com/watch "{topic}" trending',
    'site:youtube.com/watch "{topic}" latest',
    'site:youtube.com/watch "{topic}" viral',
)
TREND_SIGNAL_TERMS = (
    "trending",
    "viral",
    "latest",
    "breaking",
    "must watch",
    "must-watch",
    "new",
    "2026",
)
COUNTRY_BY_LOCATION = {
    "india": "IN",
    "united states": "US",
    "usa": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "canada": "CA",
    "australia": "AU",
}


def _load_app_config() -> dict:
    try:
        from .ai_engine import load_config
        return load_config()
    except Exception:
        logger.debug("Could not load app config for Firecrawl", exc_info=True)
        return {}


def get_firecrawl_api_key() -> Optional[str]:
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if key:
        return key
    config = _load_app_config()
    key = str(config.get("firecrawl_api_key", "") or "").strip()
    return key or None


def has_firecrawl_config() -> bool:
    return bool(get_firecrawl_api_key())


def _post_firecrawl_json(endpoint: str, payload: dict, api_key: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ShortMaker/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_youtube_url(url: str) -> Optional[str]:
    try:
        parsed = urllib.parse.urlparse((url or "").strip())
    except Exception:
        return None

    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "youtu.be":
        video_id = parsed.path.strip("/")
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else None

    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parsed.path.startswith("/shorts/"):
            return None
        if parsed.path == "/watch":
            query = urllib.parse.parse_qs(parsed.query)
            video_id = (query.get("v") or [""])[0].strip()
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _topic_terms(topic: str) -> List[str]:
    return [term for term in re.findall(r"[a-z0-9]{3,}", (topic or "").lower()) if len(term) >= 3]


def _score_candidate(candidate: dict, topic: str) -> tuple[int, str]:
    title = str(candidate.get("title", "") or "")
    description = str(candidate.get("description", "") or "")
    markdown = str(candidate.get("markdown", "") or "")
    url = str(candidate.get("url", "") or "")
    text_blob = " ".join(part for part in [title, description, markdown] if part).lower()
    terms = _topic_terms(topic)

    score = 0
    reasons: List[str] = []

    overlap = sum(1 for term in terms if term in text_blob)
    if overlap:
        score += overlap * 5
        reasons.append(f"{overlap} topic matches")

    signal_hits = sum(1 for term in TREND_SIGNAL_TERMS if term in text_blob)
    if signal_hits:
        score += signal_hits * 2
        reasons.append("trend terms")

    if "/watch?v=" in url:
        score += 4
        reasons.append("full YouTube video")

    if "playlist" in text_blob or "/shorts/" in url or "shorts" in title.lower():
        score -= 6
        reasons.append("short-form source penalty")

    if len(description.strip()) > 40:
        score += 1
        reasons.append("descriptive snippet")

    return score, ", ".join(reasons[:3]) or "basic keyword rank"


def _firecrawl_search(query: str, location: str, limit: int, api_key: str) -> List[dict]:
    location_key = (location or "").strip().lower()
    payload = {
        "query": query,
        "limit": max(1, min(limit, 10)),
        "sources": ["web"],
        "location": location,
        "country": COUNTRY_BY_LOCATION.get(location_key, "IN"),
        "tbs": "qdr:w",
        "timeout": FIRECRAWL_SEARCH_TIMEOUT_MS,
        "ignoreInvalidURLs": True,
    }

    try:
        result = _post_firecrawl_json(FIRECRAWL_SEARCH_ENDPOINT, payload, api_key)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else ""
        logger.error(f"Firecrawl search error {exc.code}: {error_body}")
        raise RuntimeError(f"Firecrawl search failed: {exc.code}") from exc
    except Exception as exc:
        logger.error(f"Firecrawl search request failed: {exc}")
        raise RuntimeError("Firecrawl search failed") from exc

    data = result.get("data", []) or []
    if isinstance(data, dict):
        data = data.get("web", []) or []
    return [item for item in data if isinstance(item, dict)]


def discover_trend_videos(topic: str, location: str = "India", limit: int = 6) -> List[dict]:
    topic = (topic or "").strip()
    if len(topic) < 2:
        raise ValueError("topic is required")

    api_key = get_firecrawl_api_key()
    if not api_key:
        raise RuntimeError("Firecrawl API key is not configured")

    candidates_by_url: Dict[str, dict] = {}
    query_errors: List[str] = []
    target_count = max(1, min(limit, 12))

    for template in TREND_QUERY_TEMPLATES:
        query = template.format(topic=topic)
        try:
            query_results = _firecrawl_search(query, location, TREND_QUERY_LIMIT, api_key)
        except RuntimeError as exc:
            logger.warning("Trend discovery query failed for '%s': %s", query, exc)
            query_errors.append(str(exc))
            continue

        for item in query_results:
            normalized_url = _normalize_youtube_url(str(item.get("url", "")))
            if not normalized_url:
                continue

            score, reason = _score_candidate({**item, "url": normalized_url}, topic)
            candidate = {
                "title": str(item.get("title", "") or "YouTube video").strip()[:140],
                "description": str(item.get("description", "") or "").strip()[:320],
                "url": normalized_url,
                "score": score,
                "reason": reason,
                "query": query,
            }

            existing = candidates_by_url.get(normalized_url)
            if existing is None or candidate["score"] > existing["score"]:
                candidates_by_url[normalized_url] = candidate

        if len(candidates_by_url) >= target_count:
            break

    ranked = sorted(candidates_by_url.values(), key=lambda item: item["score"], reverse=True)
    if ranked:
        return ranked[:target_count]

    if query_errors:
        raise RuntimeError(query_errors[0])

    return []


def auto_pick_trend_video(topic: str, location: str = "India", limit: int = 6) -> dict:
    candidates = discover_trend_videos(topic=topic, location=location, limit=limit)
    if not candidates:
        raise RuntimeError("No trend-aligned YouTube videos found")
    return candidates[0]
