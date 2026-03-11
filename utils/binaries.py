from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Optional


_WINDOWS_FFMPEG_DIRS = (
    os.environ.get("SHORTMAKER_FFMPEG_BIN", "").strip(),
    os.environ.get("FFMPEG_BIN", "").strip(),
    os.environ.get("FFMPEG_HOME", "").strip(),
    r"C:\ffmpeg\ffmpeg-8.0.1-essentials_build\bin",
    r"C:\ffmpeg\bin",
)


def _iter_candidate_paths(binary_name: str):
    executable = binary_name if binary_name.lower().endswith(".exe") else f"{binary_name}.exe"
    for raw_dir in _WINDOWS_FFMPEG_DIRS:
        if not raw_dir:
            continue
        base = Path(raw_dir)
        if base.is_file() and base.name.lower() == executable.lower():
            yield base
            continue
        candidate = base / executable
        if candidate.exists():
            yield candidate


@lru_cache(maxsize=8)
def resolve_binary(binary_name: str, *, required: bool = False) -> Optional[str]:
    direct = shutil.which(binary_name) or shutil.which(f"{binary_name}.exe")
    if direct:
        return direct

    for candidate in _iter_candidate_paths(binary_name):
        return str(candidate)

    if required:
        raise FileNotFoundError(
            f"Could not find '{binary_name}'. Install FFmpeg and ensure it is on PATH "
            "or set SHORTMAKER_FFMPEG_BIN/FFMPEG_BIN."
        )
    return None


def ensure_ffmpeg_on_path() -> None:
    ffmpeg_path = resolve_binary("ffmpeg", required=False)
    if not ffmpeg_path:
        return

    ffmpeg_dir = str(Path(ffmpeg_path).parent)
    path_value = os.environ.get("PATH", "")
    if ffmpeg_dir not in path_value.split(os.pathsep):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + path_value

