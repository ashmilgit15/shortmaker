"""
shorts.py - Main processing orchestration

Coordinates the full pipeline:
1. Download video
2. Transcribe with Whisper
3. Detect highlights
4. Generate short clips
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional
import time

from .video import download_video, get_video_info
from .transcription import transcribe_video, get_segments_in_range
from .highlights import detect_highlights

import sys
sys.path.append(str(Path(__file__).parent.parent))
from utils.ffmpeg_helpers import create_shorts, get_video_info as ffmpeg_get_info


class ProcessingStatus:
    """Track processing status for frontend updates."""
    
    def __init__(self):
        self.stage = "idle"
        self.progress = 0
        self.message = ""
        self.error = None
        self.results = []
    
    def update(self, stage: str, progress: int, message: str):
        self.stage = stage
        self.progress = progress
        self.message = message
        print(f"[{stage}] {progress}% - {message}")
    
    def to_dict(self) -> Dict:
        return {
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "results": self.results
        }


def process_video(
    youtube_url: str,
    output_dir: str = "outputs",
    num_clips: int = 3,
    status: Optional[ProcessingStatus] = None
) -> Dict:
    """
    Main pipeline: Download → Transcribe → Detect → Generate shorts.
    
    Args:
        youtube_url: YouTube video URL
        output_dir: Directory to save outputs
        num_clips: Number of clips to generate
        status: Optional status tracker
        
    Returns:
        Dict with processing results
    """
    if status is None:
        status = ProcessingStatus()
    
    start_time = time.time()
    temp_dir = os.path.join(output_dir, "temp")
    shorts_dir = os.path.join(output_dir, "shorts")
    
    try:
        # Clean up any previous temp files
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        Path(shorts_dir).mkdir(parents=True, exist_ok=True)
        
        # ========================================
        # STAGE 1: Download Video
        # ========================================
        status.update("downloading", 10, "Downloading video from YouTube...")
        
        download_result = download_video(youtube_url, temp_dir)
        video_path = download_result['path']
        video_info = download_result['info']
        
        status.update("downloading", 25, f"Downloaded: {video_info['title']}")
        
        # Get video duration from ffprobe for accuracy
        ffmpeg_info = ffmpeg_get_info(video_path)
        video_duration = ffmpeg_info['duration']
        
        # ========================================
        # STAGE 2: Transcribe with Whisper
        # ========================================
        status.update("transcribing", 30, "Transcribing audio with Whisper AI...")
        
        # Use 'base' model for good balance of speed and accuracy
        # Switch to 'tiny' for faster processing, 'small' or 'medium' for better accuracy
        segments = transcribe_video(video_path, model_size="base")
        
        status.update("transcribing", 50, f"Transcribed {len(segments)} segments")
        
        # ========================================
        # STAGE 3: Detect Highlights
        # ========================================
        status.update("analyzing", 55, "Analyzing transcript for highlights...")
        
        highlights = detect_highlights(
            segments=segments,
            video_duration=video_duration,
            num_clips=num_clips
        )
        
        status.update("analyzing", 65, f"Found {len(highlights)} highlight segments")
        
        if not highlights:
            raise ValueError("No highlights detected. Video may be too short or transcript empty.")
        
        # ========================================
        # STAGE 4: Generate Short Clips
        # ========================================
        status.update("generating", 70, "Generating vertical short clips...")
        
        output_files = create_shorts(
            input_video=video_path,
            highlights=highlights,
            segments=segments,
            output_dir=shorts_dir
        )
        
        # ========================================
        # COMPLETE
        # ========================================
        elapsed = time.time() - start_time
        
        status.update("complete", 100, f"Generated {len(output_files)} shorts in {elapsed:.1f}s")
        status.results = [os.path.basename(f) for f in output_files]
        
        # Clean up temp files
        shutil.rmtree(temp_dir)
        
        return {
            "success": True,
            "video_title": video_info['title'],
            "video_duration": video_duration,
            "num_segments": len(segments),
            "num_highlights": len(highlights),
            "shorts": status.results,
            "processing_time": elapsed,
            "highlights_info": [
                {
                    "filename": os.path.basename(output_files[i]),
                    "start": highlights[i]['start'],
                    "end": highlights[i]['end'],
                    "duration": highlights[i]['end'] - highlights[i]['start'],
                    "reason": highlights[i]['reason']
                }
                for i in range(len(output_files))
            ]
        }
        
    except Exception as e:
        status.error = str(e)
        status.update("error", 0, f"Error: {str(e)}")
        
        # Clean up on error
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    # Test the pipeline
    import sys
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    result = process_video(url, output_dir="./test_outputs")
    print("\n" + "="*50)
    print("RESULT:")
    print(result)
