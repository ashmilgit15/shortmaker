"""
highlights.py - Smart highlight detection (AI-first with rule-based fallback)

Uses Google Gemini AI for intelligent content analysis when configured.
Falls back to deterministic rule-based scoring if AI is unavailable.
Includes optional face-based refinement to prioritize clips with face-centered
frames and better visual attention quality.
"""

import re
import logging
import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Highlight:
    """Represents a detected highlight segment."""
    start: float
    end: float
    score: float
    reason: str
    text: str
    title: str = ""
    hook_caption: str = ""
    virality_score: int = 0
    face_score: float = 0.0
    face_presence: float = 0.0
    face_center_offset: float = 0.0
    face_frames_scored: int = 0


# ========================================
# AI-Powered Detection (Primary)
# ========================================


def detect_highlights_ai(
    segments: List[Dict],
    video_duration: float,
    num_clips: int = 3,
    video_title: str = "",
    video_path: Optional[str] = None
) -> List[Dict]:
    """
    Try AI-powered highlight detection first.
    Falls back to rule-based if AI is unavailable.
    """
    try:
        from .ai_engine import is_ai_enabled, ai_detect_highlights

        if is_ai_enabled():
            logger.info("🤖 Using AI-powered highlight detection")
            ai_results = ai_detect_highlights(
                segments=segments,
                video_duration=video_duration,
                num_clips=num_clips,
                video_title=video_title
            )

            if ai_results and len(ai_results) >= num_clips:
                logger.info(f"✅ AI detected {len(ai_results)} highlights")
                return _apply_face_tracking(
                    ai_results[:num_clips],
                    video_path=video_path,
                    requested_count=num_clips
                )
            elif ai_results:
                logger.warning(
                    f"⚠️ AI found {len(ai_results)} clips, needed {num_clips}. "
                    f"Supplementing with rule-based."
                )
                # Supplement with rule-based
                needed = num_clips - len(ai_results)
                rule_results = detect_highlights_rules(
                    segments,
                    video_duration,
                    needed + 2,
                    video_path=video_path
                )

                ai_ranges = [(h['start'], h['end']) for h in ai_results]
                for rh in rule_results:
                    overlaps = False
                    for ai_start, ai_end in ai_ranges:
                        if not (rh['end'] + 15 < ai_start or rh['start'] > ai_end + 15):
                            overlaps = True
                            break
                    if not overlaps:
                        ai_results.append(rh)
                        if len(ai_results) >= num_clips:
                            break

                return _apply_face_tracking(
                    ai_results,
                    video_path=video_path,
                    requested_count=num_clips
                )
            else:
                logger.warning("⚠️ AI detection returned no results, falling back to rules")
        else:
            logger.info("📏 AI not enabled, using rule-based detection")
    except ImportError as e:
        logger.warning(f"AI engine not available: {e}")
    except Exception as e:
        logger.error(f"AI detection error: {e}")

    return detect_highlights_rules(segments, video_duration, num_clips, video_path=video_path)


# ========================================
# Rule-Based Detection (Fallback)
# ========================================

# Scoring patterns - words/phrases that indicate engaging content
QUESTION_PATTERNS = [
    r'\?',  # Questions
    r'\b(what|why|how|when|where|who|which)\b',
    r'\b(do you|did you|have you|can you|would you)\b',
]

STRONG_STATEMENT_PATTERNS = [
    r'\b(i believe|i think|the key is|the secret is|here\'s the thing)\b',
    r'\b(most important|biggest mistake|game changer|changed my life)\b',
    r'\b(never|always|absolutely|definitely|exactly)\b',
    r'\b(the truth is|honestly|let me tell you|listen)\b',
    r'\b(number one|first thing|main reason|top)\b',
]

EMOTIONAL_PATTERNS = [
    r'\b(amazing|incredible|unbelievable|shocking|insane|crazy)\b',
    r'\b(love|hate|excited|scared|surprised|blown away)\b',
    r'\b(best|worst|greatest|terrible|awesome|fantastic)\b',
    r'\b(wow|omg|oh my god|holy|no way)\b',
]

HOOK_PATTERNS = [
    r'\b(but here\'s|but wait|plot twist|guess what)\b',
    r'\b(you won\'t believe|this is why|that\'s when)\b',
    r'\b(the problem is|the thing is|here\'s why)\b',
]

# Patterns to avoid (intros, outros, sponsors)
SKIP_PATTERNS = [
    r'\b(subscribe|like and subscribe|hit the bell|notification)\b',
    r'\b(sponsored by|this video is sponsored|check out|use code)\b',
    r'\b(thanks for watching|see you|next video|bye|goodbye)\b',
    r'\b(welcome to|hey guys|what\'s up|hello everyone|intro)\b',
    r'\b(patreon|merch|link in description|affiliate)\b',
]


def calculate_segment_score(text: str) -> Tuple[float, str]:
    """
    Calculate engagement score for a text segment.
    
    Returns:
        Tuple of (score, primary_reason)
    """
    text_lower = text.lower()
    score = 0.0
    reasons = []
    
    # Check for skip patterns (negative score)
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, text_lower):
            return -10.0, "skip_content"
    
    # Score questions (high engagement)
    for pattern in QUESTION_PATTERNS:
        matches = len(re.findall(pattern, text_lower))
        if matches > 0:
            score += matches * 3.0
            reasons.append("question")
    
    # Score strong statements
    for pattern in STRONG_STATEMENT_PATTERNS:
        matches = len(re.findall(pattern, text_lower))
        if matches > 0:
            score += matches * 2.5
            reasons.append("strong_statement")
    
    # Score emotional content
    for pattern in EMOTIONAL_PATTERNS:
        matches = len(re.findall(pattern, text_lower))
        if matches > 0:
            score += matches * 2.0
            reasons.append("emotional")
    
    # Score hooks
    for pattern in HOOK_PATTERNS:
        matches = len(re.findall(pattern, text_lower))
        if matches > 0:
            score += matches * 3.5
            reasons.append("hook")
    
    # Bonus for medium-length segments (not too short, not too long)
    word_count = len(text.split())
    if 10 <= word_count <= 50:
        score += 1.0
    
    # Determine primary reason
    primary_reason = reasons[0] if reasons else "general"
    
    return score, primary_reason


def find_highlight_windows(
    segments: List[Dict],
    video_duration: float,
    window_size: float = 30.0,  # Target clip length
    min_clip: float = 15.0,
    max_clip: float = 59.0
) -> List[Highlight]:
    """
    Find the best highlight windows in the transcript.
    """
    if not segments:
        return []
    
    # Skip first and last 10% of video (intro/outro)
    skip_start = video_duration * 0.10
    skip_end = video_duration * 0.90
    
    # Filter segments to valid range
    valid_segments = [
        seg for seg in segments
        if seg['start'] >= skip_start and seg['end'] <= skip_end
    ]
    
    if not valid_segments:
        valid_segments = segments[1:-1] if len(segments) > 2 else segments
    
    highlights = []
    
    # Sliding window approach
    i = 0
    while i < len(valid_segments):
        window_start = valid_segments[i]['start']
        window_text = ""
        window_end = window_start
        
        j = i
        while j < len(valid_segments):
            seg = valid_segments[j]
            potential_end = seg['end']
            
            if potential_end - window_start > max_clip:
                break
            
            window_text += " " + seg['text']
            window_end = potential_end
            j += 1
        
        window_duration = window_end - window_start
        if window_duration >= min_clip:
            score, reason = calculate_segment_score(window_text)
            
            if score > 0:
                highlights.append(Highlight(
                    start=window_start,
                    end=window_end,
                    score=score,
                    reason=reason,
                    text=window_text.strip(),
                ))
        
        i += 1
    
    # Sort by score (highest first)
    highlights.sort(key=lambda h: h.score, reverse=True)
    
    return highlights


def select_top_highlights(
    highlights: List[Highlight],
    count: int = 3,
    min_gap: float = 30.0
) -> List[Highlight]:
    """
    Select top N non-overlapping highlights.
    """
    if not highlights:
        return []
    
    selected = []
    
    for highlight in highlights:
        overlaps = False
        for sel in selected:
            if not (highlight.end + min_gap < sel.start or 
                    highlight.start > sel.end + min_gap):
                overlaps = True
                break
        
        if not overlaps:
            selected.append(highlight)
            
            if len(selected) >= count:
                break
    
    # Sort by timestamp for sequential processing
    selected.sort(key=lambda h: h.start)
    
    return selected


def detect_highlights_rules(
    segments: List[Dict],
    video_duration: float,
    num_clips: int = 3,
    video_path: Optional[str] = None
) -> List[Dict]:
    """
    Rule-based highlight detection (fallback method).
    """
    # Find all potential highlights
    all_highlights = find_highlight_windows(segments, video_duration)
    
    # Select top non-overlapping highlights
    top_highlights = select_top_highlights(all_highlights, count=num_clips)
    
    # If we don't have enough highlights, fall back to evenly spaced segments
    if len(top_highlights) < num_clips:
        logger.warning(f"Only found {len(top_highlights)} highlights, using fallback")
        return fallback_highlights(
            segments=segments,
            video_duration=video_duration,
            num_clips=num_clips,
            video_path=video_path
        )
    
    candidates = [
        {
            'start': h.start,
            'end': h.end,
            'score': h.score,
            'reason': h.reason,
            'text': h.text[:200] + "..." if len(h.text) > 200 else h.text,
            'title': '',
            'hook_caption': '',
            'virality_score': max(1, min(10, int(h.score))),
            'face_score': h.face_score,
            'face_presence': h.face_presence,
            'face_center_offset': h.face_center_offset,
            'face_frames_scored': h.face_frames_scored,
        }
        for h in top_highlights
    ]
    
    return _apply_face_tracking(candidates, video_path=video_path, requested_count=num_clips)


def fallback_highlights(
    segments: List[Dict],
    video_duration: float,
    num_clips: int = 3,
    video_path: Optional[str] = None
) -> List[Dict]:
    """
    Fallback: Create evenly spaced clips if highlight detection fails.
    """
    if not segments:
        return []
    
    clip_duration = 30.0  # 30 second clips
    skip_start = video_duration * 0.15
    skip_end = video_duration * 0.85
    usable_duration = skip_end - skip_start
    
    if usable_duration < clip_duration * num_clips:
        clip_duration = max(0.0, usable_duration / num_clips) if num_clips > 0 else 0.0
    
    highlights = []
    spacing = usable_duration / (num_clips + 1) if num_clips > 0 else 0.0
    
    for i in range(num_clips):
        start = skip_start + spacing * (i + 1) - clip_duration / 2
        end = start + clip_duration
        clip_segments = [s for s in segments if s['start'] >= start and s['end'] <= end]
        text = ' '.join(s['text'] for s in clip_segments)
        
        highlights.append({
            'start': start,
            'end': end,
            'score': 1.0,
            'reason': 'evenly_spaced',
            'text': text[:200] + "..." if len(text) > 200 else text,
            'title': '',
            'hook_caption': '',
            'virality_score': 3,
            'face_score': 0.0,
            'face_presence': 0.0,
            'face_center_offset': 0.0,
            'face_frames_scored': 0,
        })
    
    return _apply_face_tracking(highlights, video_path=video_path, requested_count=num_clips)


# ========================================
# Face tracking utility
# ========================================


def _apply_face_tracking(
    highlights: List[Dict],
    video_path: Optional[str],
    requested_count: int,
    min_gap: float = 30.0
) -> List[Dict]:
    """
    Re-rank highlights using face-centered frame quality and return the best candidates.
    """
    if not highlights:
        return []

    # If no path and no face module, return original list.
    if not video_path:
        return highlights[:requested_count]

    enriched: List[Dict] = []
    for h in highlights:
        face_data = _score_highlight_by_face(video_path, h.get('start', 0), h.get('end', 0))
        merged = dict(h)
        if face_data:
            merged.update(face_data)
        else:
            merged.setdefault('face_score', 0.0)
            merged.setdefault('face_presence', 0.0)
            merged.setdefault('face_center_offset', 1.0)
            merged.setdefault('face_frames_scored', 0)
        enriched.append(merged)

    for item in enriched:
        base_score = _normalize_base_score(item.get('virality_score'), item.get('score'))
        item['selection_score'] = base_score + item.get('face_score', 0.0) * 4.8 + item.get('face_presence', 0.0) * 1.2

    enriched.sort(key=lambda item: item.get('selection_score', 0), reverse=True)

    selected = []
    for item in enriched:
        overlaps = False
        for existing in selected:
            if not (item['end'] + min_gap < existing['start'] or item['start'] > existing['end'] + min_gap):
                overlaps = True
                break
        if not overlaps:
            selected.append(item)
            if len(selected) >= requested_count:
                break

    # If overlap filtering removed too many clips, keep highest-scored candidates.
    if len(selected) < requested_count:
        selected = enriched[:requested_count]

    # Sort clips by timeline for processing
    selected.sort(key=lambda item: item['start'])

    for item in selected:
        item.pop('selection_score', None)
        item.pop('score', None)

    logger.info(
        f"🎯 Face tracking refined highlights for {video_path}: "
        f"selected {len(selected)}/{len(highlights)}"
    )
    return selected


def _score_highlight_by_face(video_path: str, start: float, end: float) -> Dict:
    """
    Score a candidate highlight window using facial presence and center alignment.
    """
    try:
        import cv2
        from cv2 import data as cv2_data
    except Exception:
        return {}

    try:
        start = max(0.0, float(start))
        end = max(start + 0.01, float(end))
        duration = end - start
        if duration <= 0:
            return {}

        cascade_path = cv2_data.haarcascades + "haarcascade_frontalface_default.xml"
        face_detector = cv2.CascadeClassifier(cascade_path)
        if face_detector.empty():
            return {}

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {}

        sample_count = min(18, max(1, int(math.floor(duration / 0.8))))
        times = [
            start + ((i + 0.5) * duration / sample_count)
            for i in range(sample_count)
        ]

        frame_scores = []
        frame_offsets = []
        scored_frames = 0
        face_frames = 0

        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            scored_frames += 1
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            detections = face_detector.detectMultiScale(
                gray,
                scaleFactor=1.15,
                minNeighbors=5,
                minSize=(50, 50)
            )

            if len(detections) == 0:
                continue

            face_frames += 1
            # Pick biggest face for scene focus.
            x, y, fw, fh = sorted(
                detections,
                key=lambda item: item[2] * item[3],
                reverse=True
            )[0]

            center_x = x + fw / 2.0
            center_y = y + fh / 2.0
            frame_w = max(1.0, float(w))
            frame_h = max(1.0, float(h))

            max_dist = math.hypot(frame_w / 2.0, frame_h / 2.0) + 1e-6
            dist_from_center = math.hypot(center_x - (frame_w / 2.0), center_y - (frame_h / 2.0))
            center_offset = min(1.0, dist_from_center / max_dist)
            face_ratio = (fw * fh) / (frame_w * frame_h)
            size_score = min(1.0, face_ratio * 14.0)
            frame_score = (1.0 - center_offset) * 0.68 + size_score * 0.32
            frame_scores.append(frame_score)
            frame_offsets.append(center_offset)

        cap.release()

        if not frame_scores:
            return {
                'face_score': 0.0,
                'face_presence': 0.0,
                'face_center_offset': 1.0,
                'face_frames_scored': scored_frames,
            }

        presence_ratio = face_frames / max(1, scored_frames)
        average_frame_score = sum(frame_scores) / len(frame_scores)
        average_offset = sum(frame_offsets) / len(frame_offsets)

        # Reward clips with stronger face persistence.
        final_score = max(0.0, min(1.0, average_frame_score * 0.86 + presence_ratio * 0.14))

        return {
            'face_score': round(final_score, 4),
            'face_presence': round(presence_ratio, 4),
            'face_center_offset': round(average_offset, 4),
            'face_frames_scored': scored_frames,
        }
    except Exception as exc:
        logger.debug(f"Face scoring failed for window {start:.2f}-{end:.2f}: {exc}")
        return {}


def _normalize_base_score(virality: Optional[int], rule_score: Optional[float]) -> float:
    if isinstance(virality, (int, float)) and not math.isnan(float(virality)):
        return max(0.0, min(10.0, float(virality)))
    if isinstance(rule_score, (int, float)) and not math.isnan(float(rule_score)):
        return max(0.0, min(10.0, float(rule_score)))
    return 5.0


# ========================================
# Main Entry Point
# ========================================


def detect_highlights(
    segments: List[Dict],
    video_duration: float,
    num_clips: int = 3,
    video_title: str = "",
    video_path: Optional[str] = None
) -> List[Dict]:
    """
    Main function to detect highlights in a video transcript.
    Uses AI when enabled, falls back to rules otherwise.

    Args:
        segments: Transcript segments from Whisper
        video_duration: Total video duration in seconds
        num_clips: Number of clips to generate
        video_title: Optional video title for better AI context
        video_path: Optional source path for face-scoring pass

    Returns:
        List of highlight dicts with start/end, reason, text, title, hook_caption,
        virality_score, face metrics.
    """
    return detect_highlights_ai(
        segments=segments,
        video_duration=video_duration,
        num_clips=num_clips,
        video_title=video_title,
        video_path=video_path
    )


if __name__ == "__main__":
    # Test with sample segments
    test_segments = [
        {'start': 0, 'end': 5, 'text': "Hey guys, welcome to my channel!"},
        {'start': 10, 'end': 20, 'text': "Here's the thing - most people don't realize this."},
        {'start': 25, 'end': 35, 'text': "What do you think is the biggest mistake?"},
        {'start': 40, 'end': 50, 'text': "This is absolutely incredible, it changed my life."},
        {'start': 55, 'end': 65, 'text': "But wait, there's something even more important."},
        {'start': 70, 'end': 80, 'text': "Thanks for watching, hit subscribe!"},
    ]
    
    results = detect_highlights(test_segments, video_duration=85, num_clips=3)
    for r in results:
        print(f"\n[{r['start']:.1f} - {r['end']:.1f}] ({r['reason']})")
        print(f"  Title: {r.get('title', 'N/A')}")
        print(f"  Score: {r.get('virality_score', 'N/A')}/10")
        print(f"  Face Score: {r.get('face_score', 0):.3f}")
        print(f"  Face Presence: {r.get('face_presence', 0):.3f}")
        print(f"  {r['text']}")
