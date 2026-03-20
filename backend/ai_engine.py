"""
ai_engine.py - AI-powered highlight detection using Google Gemini (Free Tier)

Uses Google Gemini API (free: 15 req/min, 1M tokens/min) to:
1. Analyze transcripts and detect the most viral-worthy moments
2. Generate catchy titles for each short
3. Score clips by virality potential
4. Suggest hook captions for maximum engagement

Free API: https://aistudio.google.com/app/apikey
"""

import os
import json
import re
import logging
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
from utils.env_loader import load_dotenv_file
from utils.secret_store import apply_runtime_secrets, sanitize_persisted_config

logger = logging.getLogger(__name__)
SHORTS_MAX_DURATION_SECONDS = 59.0

# ========================================
# Configuration
# ========================================

BASE_DIR = Path(__file__).parent.parent
CLERK_RUNTIME_KEYS = ("CLERK_ISSUER", "CLERK_AUDIENCE", "CLERK_JWKS_URL")
load_dotenv_file(BASE_DIR / ".env", override_keys=CLERK_RUNTIME_KEYS, clear_missing_keys=CLERK_RUNTIME_KEYS)
CONFIG_FILE = BASE_DIR / ".env.json"

# Default config
DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "groq_api_key": "",
    "firecrawl_api_key": "",
    "youtube_client_id": "",
    "youtube_client_secret": "",
    "youtube_default_privacy": "private",
    "youtube_accounts": {},
    "ai_enabled": False,
    "model": "gemini-2.5-flash",
}


def load_config() -> dict:
    """Load AI configuration from .env.json"""
    config = DEFAULT_CONFIG.copy()
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                config.update(saved)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    return apply_runtime_secrets(config)


def save_config(config: dict):
    """Save AI configuration to .env.json"""
    try:
        persisted = sanitize_persisted_config(config)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(persisted, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving config: {e}")


def get_api_key() -> Optional[str]:
    """Get the Gemini API key from config or environment."""
    config = load_config()
    key = config.get("gemini_api_key", "")
    return key if key else None


def is_ai_enabled() -> bool:
    """Check if AI features are enabled and configured."""
    config = load_config()
    return config.get("ai_enabled", False) and bool(get_api_key())


# ========================================
# Gemini API Client (using requests, no SDK needed)
# ========================================

def call_gemini(
    prompt: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    *,
    temperature: float = 0.4,
    max_output_tokens: int = 4096,
) -> Optional[str]:
    """
    Call Google Gemini API directly via REST (no SDK dependency).
    
    Uses the free tier: 15 requests/min, 1M tokens/min.
    Model: gemini-2.0-flash (fast, free, great for analysis)
    """
    import urllib.request
    import urllib.error
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": temperature,
            "topP": 0.9,
            "topK": 40,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json"
        }
    }
    
    data = json.dumps(payload).encode('utf-8')
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
        },
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            # Extract text from Gemini response
            candidates = result.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            
            logger.warning("Empty response from Gemini")
            return None
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ""
        logger.error(f"Gemini API error {e.code}: {error_body}")
        if e.code == 429:
            logger.warning("Rate limited - falling back to rule-based detection")
        elif e.code == 400:
            logger.error(f"Bad request to Gemini: {error_body}")
        return None
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return None


def _strip_json_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_json_array_text(text: str) -> Optional[str]:
    cleaned = _strip_json_code_fences(text)
    if not cleaned:
        return None
    start = cleaned.find("[")
    if start == -1:
        return None
    end = cleaned.rfind("]")
    if end == -1 or end < start:
        return cleaned[start:]
    return cleaned[start : end + 1]


def _extract_json_object_text(text: str) -> Optional[str]:
    cleaned = _strip_json_code_fences(text)
    if not cleaned:
        return None
    start = cleaned.find("{")
    if start == -1:
        return None
    end = cleaned.rfind("}")
    if end == -1 or end < start:
        return cleaned[start:]
    return cleaned[start : end + 1]


def _salvage_partial_json_array(text: str) -> Optional[List[Any]]:
    candidate = _extract_json_array_text(text)
    if not candidate:
        return None

    decoder = json.JSONDecoder()
    items: List[Any] = []
    body = candidate[1:]
    pos = 0

    while pos < len(body):
        while pos < len(body) and body[pos] in " \r\n\t,":
            pos += 1
        if pos >= len(body) or body[pos] == "]":
            break
        try:
            item, next_pos = decoder.raw_decode(body, pos)
        except json.JSONDecodeError:
            break
        items.append(item)
        pos = next_pos

    return items or None


def _parse_json_payload(text: str, *, expect_array: bool) -> Optional[Any]:
    candidates = []
    cleaned = _strip_json_code_fences(text)
    if cleaned:
        candidates.append(cleaned)

    extracted = _extract_json_array_text(text) if expect_array else _extract_json_object_text(text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            if expect_array and isinstance(payload, list):
                return payload
            if not expect_array and isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue

    if expect_array:
        return _salvage_partial_json_array(text)
    return None


# ========================================
# AI-Powered Highlight Detection
# ========================================


def _normalize_ai_highlights(highlights: List[Dict], video_duration: float, num_clips: int) -> Optional[List[Dict]]:
    """Validate and normalize raw Gemini highlight output."""
    if not isinstance(highlights, list):
        logger.error(f"AI returned non-list: {type(highlights)}")
        return None

    validated = []
    for h in highlights:
        if not isinstance(h, dict):
            continue

        try:
            start = float(h.get('start', 0))
            end = float(h.get('end', 0))
        except (TypeError, ValueError):
            continue

        if end <= start or start < 0 or end > video_duration:
            continue
        if end - start < 10:
            end = min(start + 30, video_duration)
        if end - start > SHORTS_MAX_DURATION_SECONDS:
            end = min(start + SHORTS_MAX_DURATION_SECONDS, video_duration)

        try:
            virality_score = int(h.get('virality_score', 5))
        except (TypeError, ValueError):
            virality_score = 5

        validated.append({
            'start': start,
            'end': end,
            'title': str(h.get('title', 'Highlight'))[:50],
            'hook_caption': str(h.get('hook_caption', ''))[:150],
            'virality_score': min(10, max(1, virality_score)),
            'reason': str(h.get('reason', 'highlight')),
            'text': str(h.get('text', ''))[:200],
        })

    if not validated:
        logger.warning("No valid highlights after AI analysis")
        return None

    validated.sort(key=lambda x: x['virality_score'], reverse=True)
    validated = validated[:num_clips]
    validated.sort(key=lambda x: x['start'])

    logger.info(f"AI detected {len(validated)} highlights with scores: {[h['virality_score'] for h in validated]}")
    return validated

def ai_detect_highlights(
    segments: List[Dict],
    video_duration: float,
    num_clips: int = 3,
    video_title: str = ""
) -> Optional[List[Dict]]:
    """
    Use Gemini AI to find the most viral-worthy moments in a transcript.
    
    Returns a list of highlight dicts or None if AI is unavailable.
    """
    api_key = get_api_key()
    if not api_key:
        logger.info("No API key configured, skipping AI detection")
        return None
    
    config = load_config()
    model = config.get("model", "gemini-2.5-flash")
    
    # Build transcript with timestamps
    transcript_lines = []
    for seg in segments:
        timestamp = f"[{seg['start']:.1f}s - {seg['end']:.1f}s]"
        transcript_lines.append(f"{timestamp} {seg['text']}")
    
    full_transcript = "\n".join(transcript_lines)
    
    # Truncate if too long (keep under token limits for free tier)
    if len(full_transcript) > 15000:
        full_transcript = full_transcript[:15000] + "\n... [transcript truncated]"
    
    prompt = f"""You are a viral content expert and social media strategist. Analyze this YouTube video transcript and find the {num_clips} most viral-worthy moments for short-form content (TikTok, YouTube Shorts, Instagram Reels).

VIDEO TITLE: {video_title or "Unknown"}
TOTAL DURATION: {video_duration:.0f} seconds

TRANSCRIPT:
{full_transcript}

INSTRUCTIONS:
1. Find exactly {num_clips} non-overlapping segments that would make the most engaging short clips (15-59 seconds each).
2. Prioritize moments with: emotional peaks, surprising revelations, funny moments, controversial takes, useful tips, dramatic pauses, climactic points, or strong hooks.
3. AVOID: intros, outros, sponsor reads, "subscribe" segments, boring transitions.
4. each clip should have a natural start and end point — don't cut mid-sentence.
5. Skip the first 10% and last 10% of the video (intro/outro).

Return a JSON array with exactly {num_clips} objects. Each object must have these exact fields:
- "start": number (start time in seconds)
- "end": number (end time in seconds)  
- "title": string (catchy, short title for this clip, max 50 chars)
- "hook_caption": string (a 1-sentence hook caption that would make someone stop scrolling)
- "virality_score": number (1-10, how viral this clip could be)
- "reason": string (one of: "emotional", "funny", "surprising", "educational", "dramatic", "controversial", "hook", "inspiring")
- "text": string (the transcript text for this segment, max 200 chars)

IMPORTANT: Return ONLY a valid JSON array, nothing else. No markdown, no explanation."""

    logger.info(f"Calling Gemini AI for highlight detection ({num_clips} clips)...")
    
    response_text = call_gemini(
        prompt,
        api_key,
        model,
        temperature=0.2,
        max_output_tokens=2200,
    )
    
    if not response_text:
        logger.warning("AI detection returned empty, falling back")
        return None
    
    highlights = _parse_json_payload(response_text, expect_array=True)
    if highlights is None:
        logger.error("Failed to parse AI response as JSON array")
        logger.debug(f"Raw response: {response_text[:800]}")
        return None

    if len(highlights) < num_clips:
        logger.warning(f"Gemini returned only {len(highlights)} parseable highlight objects")
    return _normalize_ai_highlights(highlights, video_duration, num_clips)


# ========================================
# AI Title & Caption Generation
# ========================================

def ai_generate_metadata(
    transcript_text: str,
    reason: str = "highlight"
) -> Optional[Dict]:
    """
    Generate a catchy title and hook caption for a clip.
    
    Returns dict with 'title' and 'hook_caption' or None.
    """
    api_key = get_api_key()
    if not api_key:
        return None
    
    config = load_config()
    model = config.get("model", "gemini-2.5-flash")
    
    # Truncate transcript
    text = transcript_text[:500]
    
    prompt = f"""Generate a catchy social media title and on-screen captioning for this video clip.

CLIP TRANSCRIPT: {text}
CLIP CATEGORY: {reason}

Return a JSON object with:
- "title": string (catchy title, max 40 chars, use emojis)
- "hook_caption": string (1-sentence hook that makes people stop scrolling, max 100 chars)
- "trendy_caption": string (short caption to display on screen, max 110 chars)
- "hashtags": array of 2-4 short hashtag strings like ["#Shorts", "#Viral"]

Return ONLY valid JSON, no markdown."""

    response_text = call_gemini(
        prompt,
        api_key,
        model,
        temperature=0.25,
        max_output_tokens=700,
    )
    
    if not response_text:
        return None
    
    result = _parse_json_payload(response_text, expect_array=False)
    if not isinstance(result, dict):
        logger.debug("Failed to parse AI metadata payload")
        return None

    hashtags = result.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = []

    return {
        'title': str(result.get('title', 'Untitled'))[:50],
        'hook_caption': str(result.get('hook_caption', ''))[:150],
        'trendy_caption': str(result.get('trendy_caption', ''))[:160],
        'hashtags': hashtags,
    }


# ========================================
# Validate API Key
# ========================================

def ai_enrich_highlight_metadata(
    transcript_text: str,
    reason: str = "highlight"
) -> Optional[Dict]:
    """
    Generate richer clip metadata for short-form output.
    
    Returns dict with title, hook_caption, trendy_caption and hashtags.
    """
    metadata = ai_generate_metadata(transcript_text, reason)
    if not metadata:
        return None

    # Keep backwards compatibility and avoid sending malformed extras to callers.
    hashtags = metadata.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = []

    return {
        "title": metadata.get("title", ""),
        "hook_caption": metadata.get("hook_caption", ""),
        "trendy_caption": metadata.get("trendy_caption", ""),
        "hashtags": hashtags,
    }

def validate_api_key(api_key: str) -> Tuple[bool, str]:
    """
    Test if a Gemini API key is valid by making a simple API call.
    
    Returns (is_valid, message).
    """
    if not api_key or len(api_key) < 10:
        return False, "API key is too short"
    
    # Quick format check
    if not api_key.startswith("AI") and len(api_key) < 30:
        return False, "API key format looks invalid. Get one at aistudio.google.com/app/apikey"
    
    test_prompt = "Say hello in one word."
    
    try:
        result = call_gemini(test_prompt, api_key, model="gemini-2.5-flash")
        if result:
            return True, "API key is valid! AI features are ready."
        return False, "API key validation failed — no response from Gemini. Check your key."
    except Exception as e:
        return False, f"API key validation failed: {str(e)}"


def check_api_key_format(api_key: str) -> Tuple[bool, str]:
    """
    Quick format-only check without calling the API.
    Used when saving config to avoid blocking.
    """
    if not api_key or len(api_key) < 10:
        return False, "API key is too short"
    return True, "API key format accepted. It will be validated on first use."
