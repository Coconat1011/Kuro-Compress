"""Bitrate, file size, and resolution calculation utilities."""

import re
from typing import Optional, Tuple


def parse_size(size_str: str) -> int:
    """Parse a size string (e.g. '25MB', '25M', '500kb', '1.5GB', '1048576') to bytes.

    Raises:
        ValueError: If size string format is invalid or value <= 0.
    """
    if not size_str or not isinstance(size_str, str):
        raise ValueError("Size string cannot be empty.")

    cleaned = size_str.strip().upper()

    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Z]*)$", cleaned)
    if not match:
        raise ValueError(f"Invalid size specification: '{size_str}'. Examples: '25MB', '10M', '500KB'.")

    num_part, unit_part = match.groups()
    val = float(num_part)

    if val <= 0:
        raise ValueError("Target size must be greater than zero.")

    unit_multipliers = {
        "": 1,
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "KIB": 1024,
        "M": 1024 * 1024,
        "MB": 1024 * 1024,
        "MIB": 1024 * 1024,
        "G": 1024 * 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
        "GIB": 1024 * 1024 * 1024,
    }

    if unit_part not in unit_multipliers:
        raise ValueError(f"Unknown size unit: '{unit_part}'. Use KB, MB, or GB.")

    return int(val * unit_multipliers[unit_part])


def calculate_target_bitrate(
    duration_seconds: float,
    target_bytes: int,
    desired_audio_kbps: int = 128,
    safety_margin: float = 0.95,
) -> Tuple[int, int]:
    """Calculate target video and audio bitrates in kbps from target file size and duration.

    Args:
        duration_seconds: Total video duration.
        target_bytes: Target maximum file size in bytes.
        desired_audio_kbps: Preferred audio bitrate in kbps.
        safety_margin: Multiplying factor (e.g. 0.95 = 95%) to absorb container muxing overhead.

    Returns:
        Tuple of (video_bitrate_kbps, audio_bitrate_kbps).
    """
    if duration_seconds <= 0:
        raise ValueError("Duration must be positive.")
    if target_bytes <= 0:
        raise ValueError("Target bytes must be positive.")

    # Usable bits for audio + video streams
    usable_bits = target_bytes * 8 * safety_margin
    total_kbps = usable_bits / duration_seconds / 1000.0

    # Dynamically scale audio bitrate if total budget is constrained
    audio_kbps = desired_audio_kbps
    if total_kbps < 200:
        audio_kbps = min(audio_kbps, 48)
    elif total_kbps < 400:
        audio_kbps = min(audio_kbps, 64)
    elif total_kbps < 800:
        audio_kbps = min(audio_kbps, 96)

    # Audio should never take more than 35% of total budget
    max_audio_share = total_kbps * 0.35
    if audio_kbps > max_audio_share:
        audio_kbps = max(24, int(max_audio_share))

    video_kbps = int(total_kbps - audio_kbps)
    if video_kbps < 32:
        # Absolute minimum video bitrate floor
        video_kbps = 32

    return video_kbps, audio_kbps


def parse_resolution_scale(
    target_res: str,
    orig_w: int,
    orig_h: int,
    no_upscale: bool = True,
) -> Optional[Tuple[int, int]]:
    """Parse a resolution string ('1080p', '720p', '480p', '1280x720', '50%')

    Returns:
        (new_width, new_height) where both dimensions are even integers,
        or None if keeping original resolution.
    """
    if not target_res or not target_res.strip() or orig_w <= 0 or orig_h <= 0:
        return None

    res = target_res.strip().lower()

    # Percentage: e.g. "50%", "75%"
    if res.endswith("%"):
        try:
            percent = float(res[:-1]) / 100.0
            if percent <= 0:
                return None
            new_w = max(2, int(orig_w * percent))
            new_h = max(2, int(orig_h * percent))
            return (new_w - (new_w % 2), new_h - (new_h % 2))
        except ValueError:
            return None

    # Presets mapping by max height
    height_presets = {
        "4k": 2160,
        "2160p": 2160,
        "2k": 1440,
        "1440p": 1440,
        "1080p": 1080,
        "fhd": 1080,
        "720p": 720,
        "hd": 720,
        "480p": 480,
        "sd": 480,
        "360p": 360,
        "240p": 240,
    }

    if res in height_presets:
        target_h = height_presets[res]
        if no_upscale and orig_h <= target_h:
            return None  # Don't upscale
        aspect = orig_w / float(orig_h)
        target_w = int(round(target_h * aspect))
        # Ensure dimensions are even
        target_w = target_w - (target_w % 2)
        target_h = target_h - (target_h % 2)
        return (target_w, target_h)

    # Custom WxH or W:H (e.g. "1280x720", "1920:1080")
    custom_match = re.match(r"^(\d+)[x:](\d+)$", res)
    if custom_match:
        w = int(custom_match.group(1))
        h = int(custom_match.group(2))
        w = max(2, w - (w % 2))
        h = max(2, h - (h % 2))
        return (w, h)

    return None
