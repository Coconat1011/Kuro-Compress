"""Video probing and metadata extraction utilities using ffprobe."""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .ffmpeg_runner import get_ffprobe_path


@dataclass
class VideoMetadata:
    """Parsed video metadata container."""
    path: str
    filename: str
    duration: float  # In seconds
    size_bytes: int
    width: int
    height: int
    video_codec: str
    audio_codec: Optional[str]
    fps: float
    video_bitrate: int  # in bps
    audio_bitrate: int  # in bps
    total_bitrate: int  # in bps
    has_audio: bool
    format_name: str


def format_size(bytes_val: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if bytes_val < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    val = float(bytes_val)
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} {units[unit_idx]}"
    return f"{val:.2f} {units[unit_idx]}"


def format_duration(seconds: float) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS string."""
    if seconds < 0:
        seconds = 0
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_bitrate(bps: int) -> str:
    """Format bitrate in bps to kbps or Mbps."""
    if bps <= 0:
        return "Unknown"
    kbps = bps / 1000.0
    if kbps >= 1000:
        return f"{kbps / 1000.0:.2f} Mbps"
    return f"{kbps:.0f} kbps"


def parse_fps(rate_str: str) -> float:
    """Parse FPS string like '30/1' or '29.97' into float."""
    try:
        if "/" in rate_str:
            num, denom = rate_str.split("/")
            denom_f = float(denom)
            if denom_f != 0:
                return float(num) / denom_f
        return float(rate_str)
    except Exception:
        return 30.0


def probe_video(file_path: str) -> Optional[VideoMetadata]:
    """Inspect video file with ffprobe and extract metadata."""
    if not os.path.isfile(file_path):
        return None

    ffprobe_cmd = get_ffprobe_path()

    cmd = [
        ffprobe_cmd,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        data = json.loads(result.stdout)
    except Exception:
        return None

    streams = data.get("streams", [])
    format_info = data.get("format", {})

    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"), None
    )
    if not video_stream:
        return None

    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"), None
    )

    # Duration: prefer format duration, fallback to stream duration
    try:
        duration = float(
            format_info.get("duration") or video_stream.get("duration") or 0.0
        )
    except (ValueError, TypeError):
        duration = 0.0

    # File size
    try:
        size_bytes = int(
            format_info.get("size") or os.path.getsize(file_path)
        )
    except (ValueError, TypeError, OSError):
        size_bytes = 0

    # Dimensions
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)

    # FPS
    r_frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
    fps = parse_fps(r_frame_rate)

    # Video Codec
    video_codec = video_stream.get("codec_name", "unknown")

    # Audio details
    has_audio = audio_stream is not None
    audio_codec = audio_stream.get("codec_name") if audio_stream else None

    # Bitrates
    try:
        total_bitrate = int(format_info.get("bit_rate") or 0)
    except (ValueError, TypeError):
        total_bitrate = 0

    try:
        video_bitrate = int(video_stream.get("bit_rate") or 0)
    except (ValueError, TypeError):
        video_bitrate = 0

    try:
        audio_bitrate = int(audio_stream.get("bit_rate") or 0) if audio_stream else 0
    except (ValueError, TypeError):
        audio_bitrate = 0

    # If stream bitrates are 0, estimate from total and duration
    if total_bitrate == 0 and duration > 0 and size_bytes > 0:
        total_bitrate = int((size_bytes * 8) / duration)

    if video_bitrate == 0 and total_bitrate > 0:
        if audio_bitrate > 0:
            video_bitrate = max(0, total_bitrate - audio_bitrate)
        else:
            video_bitrate = total_bitrate

    return VideoMetadata(
        path=os.path.abspath(file_path),
        filename=os.path.basename(file_path),
        duration=duration,
        size_bytes=size_bytes,
        width=width,
        height=height,
        video_codec=video_codec,
        audio_codec=audio_codec,
        fps=fps,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        total_bitrate=total_bitrate,
        has_audio=has_audio,
        format_name=format_info.get("format_name", "unknown"),
    )
