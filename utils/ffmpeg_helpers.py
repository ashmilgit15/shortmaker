"""
ffmpeg_helpers.py - Higher quality FFmpeg operations for short-form video.

Handles:
- Vertical reframing with a wide-video fallback layout
- Hook overlays plus realtime karaoke subtitles
- Higher quality H.264 rendering for mobile platforms
"""

import json
import os
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional

# Use absolute import for better compatibility
try:
    from utils.binaries import ensure_ffmpeg_on_path, resolve_binary
except ImportError:
    from .binaries import ensure_ffmpeg_on_path, resolve_binary

ensure_ffmpeg_on_path()

TARGET_FPS = 30
VIDEO_CRF = os.environ.get("SHORTMAKER_VIDEO_CRF", "16")
VIDEO_PRESET = os.environ.get("SHORTMAKER_VIDEO_PRESET", "medium")
AUDIO_BITRATE = os.environ.get("SHORTMAKER_AUDIO_BITRATE", "192k")
AUDIO_FILTER = os.environ.get(
    "SHORTMAKER_AUDIO_FILTER",
    "loudnorm=I=-14:TP=-1.5:LRA=11",
)
FFMPEG_THREADS = os.environ.get("SHORTMAKER_FFMPEG_THREADS", "0")
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
WIDE_LAYOUT_MODE = os.environ.get("SHORTMAKER_WIDE_LAYOUT", "crop").strip().lower()
SHORTS_MAX_DURATION_SECONDS = 59.0


def get_video_info(video_path: str) -> Dict[str, Any]:
    """
    Get video metadata using ffprobe.
    """
    ffprobe_path = resolve_binary("ffprobe", required=False)
    if not ffprobe_path:
        return _get_video_info_with_cv2(video_path)

    cmd = [
        ffprobe_path,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        video_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
        
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    if not video_stream:
        raise ValueError("No video stream found")

    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        try:
            num, den = map(int, fps_str.split("/"))
            fps = num / den if den else 30.0
        except:
            fps = 30.0
    else:
        fps = _safe_float(fps_str, 30.0)

    format_data = data.get("format") or {}
    duration = _safe_float(format_data.get("duration"), 0.0)

    return {
        "width": int(video_stream.get("width") or 1920),
        "height": int(video_stream.get("height") or 1080),
        "duration": duration,
        "fps": fps,
        "has_audio": has_audio,
    }


def _get_video_info_with_cv2(video_path: str) -> Dict[str, Any]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("ffprobe is unavailable and OpenCV metadata fallback is not installed.") from exc

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError("Unable to open video for metadata extraction.")

    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        if fps <= 0:
            fps = 30.0
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        duration = frame_count / fps if frame_count > 0 and fps > 0 else 0.0
    finally:
        capture.release()

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "has_audio": True,
    }


def calculate_center_crop(width: int, height: int) -> Dict:
    """
    Calculate crop parameters for 9:16 vertical format.

    Used for portrait or near-square sources where a full-frame crop looks better
    than a framed layout.
    """
    target_ratio = 9 / 16
    current_ratio = width / max(height, 1)

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        new_height = height
        x_offset = (width - new_width) // 2
        y_offset = 0
    else:
        new_width = width
        new_height = int(width / target_ratio)
        x_offset = 0
        y_offset = (height - new_height) // 2

    return {
        "width": new_width,
        "height": new_height,
        "x": x_offset,
        "y": y_offset,
    }


def _safe_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value) # type: ignore
    except (TypeError, ValueError):
        return default


def _escape_ass_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _escape_filter_path(path: str) -> str:
    return (
        str(path)
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace(",", r"\,")
        .replace("'", r"\'")
    )


def _format_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = max(0.0, seconds % 60)
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _wrap_plain_text(text: str, max_chars: int = 22, max_lines: int = 2) -> str:
    words = _escape_ass_text(text).split()
    if not words:
        return ""

    lines: List[str] = []
    current: List[str] = []
    current_len = 0

    for word in words:
        projected = current_len + len(word) + (1 if current else 0)
        if current and projected > max_chars and len(lines) + 1 < max_lines:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = projected if current_len else len(word)

    if current:
        lines.append(" ".join(current))

    if len(lines) > max_lines:
        # Explicit slicing and typed assignment
        tail: List[str] = lines[max_lines - 1:]
        last_line = " ".join(tail)
        lines = lines[:max_lines - 1] + [last_line]

    result_text = r"\N".join(lines[:max_lines])
    return result_text


def _display_word(word: str) -> str:
    cleaned = _escape_ass_text(word).strip()
    if not cleaned:
        return ""
    if re.fullmatch(r"[.,!?;:]+", cleaned):
        return cleaned
    return cleaned.upper()


def _approximate_words(segment: Dict) -> List[Dict]:
    text = str(segment.get("text", "")).strip()
    if not text:
        return []

    words = [word for word in re.split(r"\s+", text) if word]
    if not words:
        return []

    seg_start = _safe_float(segment.get("start"), 0.0)
    seg_end = max(seg_start + 0.15, _safe_float(segment.get("end"), seg_start + 0.15))
    slice_duration = (seg_end - seg_start) / max(len(words), 1)

    approximated = []
    for index, word in enumerate(words):
        word_start = seg_start + (index * slice_duration)
        word_end = seg_start + ((index + 1) * slice_duration)
        approximated.append(
            {
                "start": word_start,
                "end": word_end,
                "word": word,
            }
        )

    return approximated


def _flatten_words(segments: List[Dict], clip_duration: float) -> List[Dict]:
    tokens: List[Dict] = []

    for segment in segments:
        raw_words = segment.get("words") or _approximate_words(segment)
        for raw_word in raw_words:
            raw_text = raw_word.get("word") or raw_word.get("text") or ""
            display = _display_word(raw_text)
            if not display:
                continue

            start = max(0.0, _safe_float(raw_word.get("start"), _safe_float(segment.get("start"), 0.0)))
            end = _safe_float(raw_word.get("end"), start + 0.14)
            if end <= start:
                end = start + 0.14
            if start >= clip_duration:
                continue

            token = {
                "start": min(start, clip_duration),
                "end": min(end, clip_duration),
                "display": display,
            }

            if re.fullmatch(r"[.,!?;:]+", display) and tokens:
                last_token = tokens[-1]
                last_token["display"] = (last_token.get("display") or "") + display
                last_token["end"] = max(_safe_float(last_token.get("end")), _safe_float(token.get("end")))
                continue

            tokens.append(token)

    cleaned: List[Dict] = []
    for token in tokens:
        if cleaned and token["start"] < cleaned[-1]["start"]:
            token["start"] = cleaned[-1]["start"]
        if token["end"] <= token["start"]:
            token["end"] = token["start"] + 0.1
        cleaned.append(token)

    return cleaned


def _split_caption_lines(words: List[Dict], max_chars_per_line: int = 16, max_lines: int = 2) -> List[List[Dict]]:
    lines: List[List[Dict]] = [[]]
    current_length = 0

    for word in words:
        last_line = lines[-1]
        projected = current_length + len(str(word.get("display", ""))) + (1 if last_line else 0)
        
        if last_line and projected > max_chars_per_line and len(lines) < max_lines:
            lines.append([word])
            current_length = len(str(word.get("display", "")))
            continue

        lines[-1].append(word)
        current_length = projected if lines[-1] else len(str(word.get("display", "")))

    return [line for line in lines if line]


def _build_karaoke_chunks(segments: List[Dict], clip_duration: float) -> List[Dict]:
    words = _flatten_words(segments, clip_duration)
    if not words:
        return []

    max_words_per_chunk = 6
    max_chunk_duration = 2.4
    max_gap = 0.55
    max_chars = 28

    chunks: List[List[Dict]] = []
    current: List[Dict] = []
    current_chars = 0

    for word in words:
        gap = word["start"] - current[-1]["end"] if current else 0.0
        duration = (word["end"] - current[0]["start"]) if current else (word["end"] - word["start"])
        projected_chars = current_chars + len(word["display"]) + (1 if current else 0)

        should_split = bool(
            current
            and (
                gap > max_gap
                or len(current) >= max_words_per_chunk
                or duration > max_chunk_duration
                or projected_chars > max_chars
            )
        )

        if should_split:
            chunks.append(current)
            current = []
            current_chars = 0

        current.append(word)
        current_chars += len(word["display"]) + (1 if len(current) > 1 else 0)

    if current:
        chunks.append(current)

    caption_chunks: List[Dict] = []
    for words_chunk in chunks:
        lines = _split_caption_lines(words_chunk)
        line_parts: List[str] = []

        for line_words in lines:
            karaoke_words: List[str] = []
            for token in line_words:
                duration_cs = max(6, int(round((token["end"] - token["start"]) * 100)))
                karaoke_words.append(
                    f"{{\\kf{duration_cs}}}{_escape_ass_text(token['display'])}"
                )
            line_parts.append(" ".join(karaoke_words))

        caption_chunks.append(
            {
                "start": max(0.0, words_chunk[0]["start"] - 0.02),
                "end": min(clip_duration, words_chunk[-1]["end"] + 0.05),
                "text": r"\N".join(line_parts),
            }
        )

    return caption_chunks


def generate_ass_subtitles(
    segments: List[Dict],
    output_path: str,
    video_width: int = 1080,
    video_height: int = 1920,
    caption_text: Optional[str] = None,
    clip_duration: Optional[float] = None,
) -> str:
    """
    Generate an ASS subtitle file with a hook headline and realtime karaoke captions.
    """
    normalized_duration = max(0.25, float(clip_duration or 0.25))

    ass_header = f"""[Script Info]
Title: ShortMaker Dynamic Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 2
ScaledBorderAndShadow: yes
Collisions: Normal

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial Black,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H3C000000,1,0,0,0,100,100,0,0,1,5,0,8,72,72,170,1
Style: Karaoke,Arial Black,76,&H0040CFFF,&H00FFFFFF,&H00000000,&H28000000,1,0,0,0,100,100,1,0,1,6,0,2,70,70,275,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: List[str] = []

    if caption_text:
        hook_text_raw = caption_text[:90]
        hook_text = _wrap_plain_text(hook_text_raw, max_chars=20, max_lines=2)
        hook_end = min(
            max(1.8, normalized_duration * 0.38),
            max(0.35, normalized_duration - 0.15),
        )
        if hook_text and hook_end > 0.3:
            hook_override = (
                r"{\an8\pos(540,220)\q2\fad(120,180)\blur0.4\bord5\shad0"
                r"\t(0,160,\fscx106\fscy106)\t(160,320,\fscx100\fscy100)}"
            )
            events.append(
                "Dialogue: 5,"
                f"{_format_ass_time(0.08)},{_format_ass_time(hook_end)},"
                f"Hook,,0,0,0,,{hook_override}{hook_text}"
            )

    karaoke_chunks = _build_karaoke_chunks(segments, normalized_duration)
    for chunk in karaoke_chunks:
        dialogue_override = (
            r"{\an2\pos(540,1560)\q2\fad(70,110)\blur0.2\bord6\shad0"
            r"\t(0,140,\fscx104\fscy104)\t(140,280,\fscx100\fscy100)}"
        )
        events.append(
            "Dialogue: 2,"
            f"{_format_ass_time(chunk['start'])},{_format_ass_time(chunk['end'])},"
            f"Karaoke,,0,0,0,,{dialogue_override}{chunk['text']}"
        )

    if not events:
        fallback_text = _wrap_plain_text(caption_text or "", max_chars=20, max_lines=2)
        if fallback_text:
            events.append(
                "Dialogue: 2,"
                f"{_format_ass_time(0.08)},{_format_ass_time(max(0.35, normalized_duration - 0.1))},"
                r"Karaoke,,0,0,0,,{\an2\pos(540,1560)\q2\fad(80,120)\bord6\shad0}"
                f"{fallback_text}"
            )

    ass_content = ass_header + "\n".join(events)

    with open(output_path, "w", encoding="utf-8") as subtitle_file:
        subtitle_file.write(ass_content)

    return output_path


def _build_subtitle_filter(subtitle_path: str, target_width: int, target_height: int) -> str:
    escaped_subtitle_path = _escape_filter_path(subtitle_path)
    fonts_dir = _escape_filter_path(str(FONT_DIR)) if FONT_DIR.exists() else ""
    options = [f"filename='{escaped_subtitle_path}'", f"original_size={target_width}x{target_height}"]
    if fonts_dir:
        options.append(f"fontsdir='{fonts_dir}'")
    return "subtitles=" + ":".join(options)


def _build_video_filter(
    src_width: int,
    src_height: int,
    target_width: int,
    target_height: int,
    subtitle_path: Optional[str] = None,
) -> str:
    aspect_ratio = src_width / max(src_height, 1)
    subtitle_filter = (
        _build_subtitle_filter(subtitle_path, target_width, target_height)
        if subtitle_path
        else None
    )

    post_filters = [subtitle_filter, f"fps={TARGET_FPS}", "setsar=1", "format=yuv420p"]
    post_chain = ",".join(filter(None, post_filters))

    # Use a full-frame crop by default so shorts read as genuinely vertical.
    # The older framed layout is still available via SHORTMAKER_WIDE_LAYOUT=framed.
    if aspect_ratio >= 1.35 and WIDE_LAYOUT_MODE == "framed":
        background_chain = ",".join(
            [
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase",
                f"crop={target_width}:{target_height}",
                "boxblur=24:3",
                "eq=saturation=1.08:contrast=1.04:brightness=-0.02",
            ]
        )
        foreground_chain = ",".join(
            [
                f"scale={int(target_width * 0.94)}:{int(target_height * 0.74)}:force_original_aspect_ratio=decrease",
                "eq=saturation=1.12:contrast=1.07:brightness=0.01",
                "unsharp=5:5:0.8:3:3:0.4",
            ]
        )
        final_chain = ",".join(
            [
                "overlay=(W-w)/2:(H-h)/2-110:format=auto",
                post_chain,
            ]
        )
        return (
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]{background_chain}[bg];"
            f"[fgsrc]{foreground_chain}[fg];"
            f"[bg][fg]{final_chain}[v]"
        )

    crop = calculate_center_crop(src_width, src_height)
    crop_fill_chain = ",".join(
        [
            f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}",
            f"scale={target_width}:{target_height}:flags=lanczos",
            "eq=saturation=1.10:contrast=1.06:brightness=0.01",
            "unsharp=5:5:0.7:3:3:0.35",
            post_chain,
        ]
    )
    return f"[0:v]{crop_fill_chain}[v]"


def _run_ffmpeg_render(
    input_video: str,
    output_video: str,
    start_time: float,
    duration: float,
    video_filter: str,
    has_audio: bool,
) -> subprocess.CompletedProcess:
    ffmpeg_path = resolve_binary("ffmpeg", required=False) or resolve_binary("ffmpeg", required=True)
    cmd = [
        ffmpeg_path,
        "-y",
        "-ss",
        f"{start_time:.3f}",
        "-i",
        input_video,
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        video_filter,
        "-map",
        "[v]",
    ]

    if has_audio:
        cmd.extend(
            [
                "-map",
                "0:a:0?",
                "-c:a",
                "aac",
                "-b:a",
                AUDIO_BITRATE,
                "-af",
                AUDIO_FILTER,
            ]
        )
    else:
        cmd.append("-an")

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            VIDEO_PRESET,
            "-crf",
            VIDEO_CRF,
            "-threads",
            FFMPEG_THREADS,
            "-profile:v",
            "high",
            "-level:v",
            "4.2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            output_video,
        ]
    )

    print(f"Running FFmpeg render: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def extract_clip_with_captions(
    input_video: str,
    output_video: str,
    start_time: float,
    end_time: float,
    segments: List[Dict],
    target_width: int = 1080,
    target_height: int = 1920,
    caption_text: Optional[str] = None,
    video_info: Optional[Dict] = None,
) -> str:
    """
    Extract a clip, compose a vertical layout, and burn in realtime captions.
    """
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)

    resolved_video_info = video_info or get_video_info(input_video)
    src_width = resolved_video_info["width"]
    src_height = resolved_video_info["height"]
    has_audio = bool(resolved_video_info.get("has_audio"))
    capped_end_time = min(end_time, start_time + SHORTS_MAX_DURATION_SECONDS)
    clip_duration = max(0.25, capped_end_time - start_time)

    adjusted_segments: List[Dict] = []
    for segment in segments:
        seg_start = _safe_float(segment.get("start"), 0.0)
        seg_end = _safe_float(segment.get("end"), seg_start)
        if seg_end < start_time or seg_start > capped_end_time:
            continue

        adjusted_words = []
        for word in segment.get("words", []) or []:
            word_start = _safe_float(word.get("start"), seg_start) - start_time
            word_end = _safe_float(word.get("end"), word_start + 0.14) - start_time
            if word_end < 0 or word_start > clip_duration:
                continue
            adjusted_words.append(
                {
                    "start": max(0.0, word_start),
                    "end": min(clip_duration, max(word_end, word_start + 0.14)),
                    "word": word.get("word") or word.get("text") or "",
                }
            )

        adjusted_segments.append(
            {
                "start": max(0.0, seg_start - start_time),
                "end": min(clip_duration, max(seg_end - start_time, 0.0)),
                "text": segment.get("text", ""),
                "words": adjusted_words,
            }
        )

    subtitle_path = output_video.replace(".mp4", ".ass")
    generate_ass_subtitles(
        adjusted_segments,
        subtitle_path,
        target_width,
        target_height,
        caption_text=caption_text,
        clip_duration=clip_duration,
    )

    try:
        video_filter = _build_video_filter(
            src_width,
            src_height,
            target_width,
            target_height,
            subtitle_path=subtitle_path,
        )
        result = _run_ffmpeg_render(
            input_video=input_video,
            output_video=output_video,
            start_time=start_time,
            duration=clip_duration,
            video_filter=video_filter,
            has_audio=has_audio,
        )

        if result.returncode != 0:
            print(f"Subtitle render failed, retrying without subtitles: {result.stderr}")
            fallback_filter = _build_video_filter(
                src_width,
                src_height,
                target_width,
                target_height,
                subtitle_path=None,
            )
            fallback_result = _run_ffmpeg_render(
                input_video=input_video,
                output_video=output_video,
                start_time=start_time,
                duration=clip_duration,
                video_filter=fallback_filter,
                has_audio=has_audio,
            )
            if fallback_result.returncode != 0:
                raise RuntimeError(f"FFmpeg failed: {fallback_result.stderr}")

        return output_video
    finally:
        if os.path.exists(subtitle_path):
            os.remove(subtitle_path)


def create_shorts(
    input_video: str,
    highlights: List[Dict],
    segments: List[Dict],
    output_dir: str,
    output_prefix: str = "short",
    progress_callback: Optional[Callable[[int, int, str, Dict], None]] = None,
) -> List[str]:
    """
    Create multiple short clips from highlights.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_files = []
    source_video_info = get_video_info(input_video)

    for index, highlight in enumerate(highlights, 1):
        output_path = os.path.join(output_dir, f"{output_prefix}_{index}.mp4")
        caption_text = (
            highlight.get("hook_caption")
            or highlight.get("title")
            or highlight.get("trendy_caption")
        )

        clip_segments = [
            segment
            for segment in segments
            if _safe_float(segment.get("end"), 0.0) >= highlight["start"]
            and _safe_float(segment.get("start"), 0.0) <= highlight["end"]
        ]

        print(f"\nGenerating short {index}/{len(highlights)}")
        capped_end_time = min(highlight["end"], highlight["start"] + SHORTS_MAX_DURATION_SECONDS)
        print(f"  Time: {highlight['start']:.1f}s - {capped_end_time:.1f}s")
        print(f"  Reason: {highlight.get('reason', 'unknown')}")

        if progress_callback is not None:
            try:
                progress_callback(index - 1, len(highlights), output_path, highlight)
            except Exception as e:
                print(f"Warning: progress_callback error: {e}")

        started_at = perf_counter()
        extract_clip_with_captions(
            input_video=input_video,
            output_video=output_path,
            start_time=highlight["start"],
            end_time=capped_end_time,
            segments=clip_segments,
            caption_text=caption_text,
            video_info=source_video_info,
        )

        output_files.append(output_path)
        elapsed = perf_counter() - started_at
        print(f"  Saved: {output_path} ({elapsed:.1f}s)")
        
        if progress_callback is not None:
            try:
                progress_callback(index, len(highlights), output_path, highlight)
            except Exception as e:
                pass

    return output_files


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        info = get_video_info(video_path)
        print(f"Video info: {info}")

        crop = calculate_center_crop(info["width"], info["height"])
        print(f"Crop params: {crop}")
