"""
transcription.py - Speech-to-text using Groq Whisper API

Primary: Groq Whisper API with word timestamps
Fallback: Local Whisper model (if Groq key not configured)

Groq API Key: https://console.groq.com/keys
"""

import os
import json
import logging
import subprocess
import tempfile
from typing import List, Dict, Optional
from pathlib import Path
from utils.binaries import ensure_ffmpeg_on_path, resolve_binary
from utils.env_loader import load_dotenv_file

logger = logging.getLogger(__name__)

# ========================================
# Configuration
# ========================================

BASE_DIR = Path(__file__).parent.parent
CLERK_RUNTIME_KEYS = ("CLERK_ISSUER", "CLERK_AUDIENCE", "CLERK_JWKS_URL")
load_dotenv_file(BASE_DIR / ".env", override_keys=CLERK_RUNTIME_KEYS, clear_missing_keys=CLERK_RUNTIME_KEYS)
CONFIG_FILE = BASE_DIR / ".env.json"

ensure_ffmpeg_on_path()

GROQ_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36 ShortMaker/1.0"
)


def get_groq_api_key() -> Optional[str]:
    """Get the Groq API key from config or environment."""
    # Check environment variable first
    key = os.environ.get("GROQ_API_KEY", "")
    if key:
        return key
    
    # Check .env.json
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                key = config.get("groq_api_key", "")
                if key:
                    return key
    except Exception:
        pass
    
    return None


def get_groq_model_name() -> str:
    """
    Prefer Groq's faster Whisper model by default. Users can override with
    GROQ_WHISPER_MODEL.
    """
    return (
        os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo").strip()
        or "whisper-large-v3-turbo"
    )


def _attach_word_timestamps(segments: List[Dict], words: List[Dict]) -> List[Dict]:
    """
    Merge top-level word timestamps into their corresponding segments.
    """
    if not segments:
        return []

    normalized_words = []
    for word in words or []:
        text = (word.get("word") or word.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(word.get("start"))
            end = float(word.get("end"))
        except (TypeError, ValueError):
            continue
        normalized_words.append(
            {
                "start": start,
                "end": max(end, start + 0.12),
                "word": text,
            }
        )

    for segment in segments:
        seg_start = float(segment.get("start", 0))
        seg_end = float(segment.get("end", seg_start))
        segment_words = [
            word
            for word in normalized_words
            if word["end"] >= seg_start and word["start"] <= seg_end
        ]
        segment["words"] = segment_words

    return segments


# ========================================
# Groq Whisper API (Primary - Free & Fast)
# ========================================

def extract_audio(video_path: str, output_path: str) -> str:
    """
    Extract audio from video using FFmpeg.
    Converts to mp3 for smaller file size (Groq has 25MB limit).
    """
    ffmpeg_bin = resolve_binary("ffmpeg", required=True)
    cmd = [
        ffmpeg_bin, "-y",
        "-i", video_path,
        "-vn",  # No video
        "-acodec", "libmp3lame",
        "-ar", "16000",  # 16kHz sample rate (good for speech)
        "-ac", "1",  # Mono
        "-b:a", "64k",  # Low bitrate for smaller files
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.error(f"FFmpeg audio extraction failed: {result.stderr}")
        raise RuntimeError(f"Failed to extract audio: {result.stderr}")
    
    return output_path


def split_audio_chunks(audio_path: str, max_size_mb: float = 24.0) -> List[str]:
    """
    Split audio into chunks if file is larger than Groq's 25MB limit.
    Returns list of chunk file paths.
    """
    file_size = os.path.getsize(audio_path) / (1024 * 1024)  # MB
    
    if file_size <= max_size_mb:
        return [audio_path]
    
    # Get audio duration
    ffprobe_bin = resolve_binary("ffprobe", required=False)
    if ffprobe_bin:
        cmd = [
            ffprobe_bin, "-v", "quiet", "-show_entries", "format=duration",
            "-of", "json", audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        duration = float(json.loads(result.stdout)["format"]["duration"])
    else:
        # Audio is encoded at a constant 64 kbps in extract_audio().
        duration = (os.path.getsize(audio_path) * 8) / 64_000
    
    # Calculate chunk duration to keep each under max_size
    num_chunks = int(file_size / max_size_mb) + 1
    chunk_duration = duration / num_chunks
    
    chunks = []
    base_dir = os.path.dirname(audio_path)
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    
    for i in range(num_chunks):
        start = i * chunk_duration
        chunk_path = os.path.join(base_dir, f"{base_name}_chunk{i}.mp3")
        ffmpeg_bin = resolve_binary("ffmpeg", required=True)
        
        cmd = [
            ffmpeg_bin, "-y",
            "-i", audio_path,
            "-ss", str(start),
            "-t", str(chunk_duration),
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "64k",
            chunk_path
        ]
        
        subprocess.run(cmd, capture_output=True, text=True)
        if os.path.exists(chunk_path):
            chunks.append(chunk_path)
    
    return chunks


def transcribe_with_groq(video_path: str, api_key: str) -> List[Dict]:
    """
    Transcribe audio using Groq's Whisper API.
    
    Groq offers whisper-large-v3-turbo for free:
    - Blazing fast (real-time or faster)
    - High accuracy
    - Free tier: ~15,000 audio-seconds/day
    """
    import urllib.request
    import urllib.error
    
    model_name = get_groq_model_name()
    
    logger.info(f"🎙️ Using Groq Whisper API for transcription ({model_name})")
    
    # Extract audio from video
    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.mp3")
    
    try:
        extract_audio(video_path, audio_path)
        logger.info(f"Audio extracted: {os.path.getsize(audio_path) / (1024*1024):.1f} MB")
        
        # Split if needed
        chunks = split_audio_chunks(audio_path)
        
        all_segments = []
        time_offset = 0.0
        
        for chunk_idx, chunk_path in enumerate(chunks):
            logger.info(f"Transcribing chunk {chunk_idx + 1}/{len(chunks)}...")
            
            # Build multipart form data
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            
            with open(chunk_path, 'rb') as f:
                audio_data = f.read()
            
            # Construct multipart body
            body = b""
            
            # model field
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"model\"\r\n\r\n"
            body += model_name.encode("utf-8") + b"\r\n"
            
            # response_format field
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"response_format\"\r\n\r\n"
            body += b"verbose_json\r\n"
            
            # timestamp_granularities field
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"timestamp_granularities[]\"\r\n\r\n"
            body += b"segment\r\n"

            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"timestamp_granularities[]\"\r\n\r\n"
            body += b"word\r\n"
            
            # language field (optional, improves accuracy)
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"language\"\r\n\r\n"
            body += b"en\r\n"
            
            # file field
            body += f"--{boundary}\r\n".encode()
            body += f"Content-Disposition: form-data; name=\"file\"; filename=\"audio.mp3\"\r\n".encode()
            body += b"Content-Type: audio/mpeg\r\n\r\n"
            body += audio_data
            body += b"\r\n"
            
            # End boundary
            body += f"--{boundary}--\r\n".encode()
            
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Accept": "application/json",
                    "User-Agent": GROQ_HTTP_USER_AGENT,
                },
                method="POST"
            )
            
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.loads(response.read().decode('utf-8'))
                
                chunk_segments = []
                for segment in result.get("segments", []):
                    chunk_segments.append({
                        'start': segment['start'] + time_offset,
                        'end': segment['end'] + time_offset,
                        'text': segment.get('text', '').strip(),
                        'words': [],
                    })

                chunk_words = []
                for word in result.get("words", []) or []:
                    try:
                        chunk_words.append(
                            {
                                "start": float(word.get("start", 0)) + time_offset,
                                "end": float(word.get("end", 0)) + time_offset,
                                "word": (word.get("word") or word.get("text") or "").strip(),
                            }
                        )
                    except (TypeError, ValueError):
                        continue

                all_segments.extend(_attach_word_timestamps(chunk_segments, chunk_words))
                
                # Update time offset for next chunk
                if result.get("duration"):
                    time_offset += result["duration"]
                elif all_segments:
                    time_offset = all_segments[-1]['end']
                    
            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if e.fp else ""
                logger.error(f"Groq API error {e.code}: {error_body}")
                if e.code == 403 and "1010" in error_body:
                    raise RuntimeError(
                        "Groq request blocked by Cloudflare (error 1010). "
                        "This usually means the client signature or IP was blocked before "
                        "the request reached the transcription model."
                    )
                if e.code == 429:
                    logger.warning("Groq rate limited, falling back to local Whisper")
                    raise RuntimeError("Groq rate limited")
                raise RuntimeError(f"Groq API error: {error_body}")
        
        total_words = sum(len(segment.get("words", [])) for segment in all_segments)
        logger.info(
            f"✅ Groq transcription complete: {len(all_segments)} segments, {total_words} words"
        )
        
        # Clean up temp files
        for chunk in chunks:
            try:
                os.remove(chunk)
            except:
                pass
        try:
            os.remove(audio_path)
            os.rmdir(temp_dir)
        except:
            pass
        
        return all_segments
        
    except Exception as e:
        # Clean up on error
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
        raise


# ========================================
# Local Whisper (Fallback)
# ========================================

_whisper_model = None


def get_whisper_model(model_size: str = "base"):
    """Load and cache the local Whisper model."""
    global _whisper_model
    
    if _whisper_model is None:
        import whisper
        logger.info(f"Loading local Whisper model: {model_size}")
        _whisper_model = whisper.load_model(model_size)
        logger.info("Local Whisper model loaded successfully")
    
    return _whisper_model


def transcribe_with_local_whisper(video_path: str, model_size: str = "tiny") -> List[Dict]:
    """
    Transcribe using local Whisper model (slower, but no API needed).
    """
    try:
        import whisper
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "Local Whisper is not installed. Install optional dependencies with: "
            "`python -m pip install -r requirements-local.txt`."
        ) from exc
    
    logger.info(f"📏 Using local Whisper model ({model_size}) for transcription")
    
    model = get_whisper_model(model_size)
    
    result = model.transcribe(
        video_path,
        verbose=None,
        word_timestamps=True,
        task="transcribe",
        fp16=torch.cuda.is_available(),
    )
    
    segments = []
    for segment in result.get('segments', []):
        segments.append({
            'start': segment['start'],
            'end': segment['end'],
            'text': segment['text'].strip(),
            'words': segment.get('words', [])
        })
    
    logger.info(f"Local Whisper transcription complete: {len(segments)} segments")
    return segments


# ========================================
# Main Entry Point
# ========================================

def transcribe_video(video_path: str, model_size: str = "tiny") -> List[Dict]:
    """
    Transcribe a video file using Groq Whisper API (primary) or local Whisper (fallback).
    
    Args:
        video_path: Path to the video file
        model_size: Local Whisper model size (only used as fallback)
        
    Returns:
        List of segments with start, end, text
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Try Groq API first (fast & free)
    groq_key = get_groq_api_key()
    
    if groq_key:
        try:
            return transcribe_with_groq(video_path, groq_key)
        except Exception as e:
            logger.warning(f"Groq transcription failed: {e}. Falling back to local Whisper.")
    else:
        logger.info("No Groq API key configured. Using local Whisper.")
    
    # Fallback to local Whisper
    return transcribe_with_local_whisper(video_path, model_size)


# ========================================
# Utility Functions
# ========================================

def get_transcript_text(segments: List[Dict]) -> str:
    """Get the full transcript as plain text."""
    return ' '.join(seg['text'] for seg in segments)


def get_segments_in_range(segments: List[Dict], start: float, end: float) -> List[Dict]:
    """Get transcript segments within a time range."""
    return [
        seg for seg in segments
        if seg['start'] >= start and seg['end'] <= end
    ]


def format_timestamp(seconds: float) -> str:
    """Format seconds to SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(segments: List[Dict], output_path: str) -> str:
    """Generate an SRT subtitle file from segments."""
    srt_content = []
    
    for i, segment in enumerate(segments, 1):
        start_time = format_timestamp(segment['start'])
        end_time = format_timestamp(segment['end'])
        text = segment['text']
        
        srt_content.append(f"{i}")
        srt_content.append(f"{start_time} --> {end_time}")
        srt_content.append(text)
        srt_content.append("")
    
    srt_text = '\n'.join(srt_content)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt_text)
    
    return output_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        segments = transcribe_video(video_path)
        for seg in segments[:5]:
            print(f"[{seg['start']:.2f} - {seg['end']:.2f}] {seg['text']}")
