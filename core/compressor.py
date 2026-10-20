"""High-level video compression orchestrator supporting single-pass, two-pass, and batch jobs."""

import glob
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .calculator import calculate_target_bitrate, parse_resolution_scale, parse_size
from .ffmpeg_runner import check_ffmpeg_available, get_ffmpeg_path, run_ffmpeg
from .probe import VideoMetadata, format_size, probe_video


@dataclass
class CompressionOptions:
    """Settings configuring how a video is compressed."""
    # Compression mode: 'target_size' or 'quality'
    mode: str = "quality"

    # Size-based compression
    target_size_bytes: Optional[int] = None

    # Quality-based compression (CRF: 18=high quality, 23=balanced, 28=high compression)
    crf: int = 24

    # Speed preset ('ultrafast', 'veryfast', 'fast', 'medium', 'slow')
    preset: str = "medium"

    # Codec: 'libx264', 'libx265', 'libsvtav1', 'h264_nvenc', 'hevc_nvenc'
    codec: str = "libx264"

    # Resolution downscaling: None, '1080p', '720p', '480p', '360p', '50%'
    resolution: Optional[str] = None

    # Audio setting: 'aac', 'copy', 'mute'
    audio_mode: str = "aac"
    audio_bitrate_kbps: int = 128

    # Optional framerate override
    fps: Optional[float] = None

    # Force two-pass encoding (default True when mode is 'target_size')
    two_pass: Optional[bool] = None

    # Overwrite destination file if already exists
    overwrite: bool = True

    # Suffix for auto-generated output filenames
    filename_suffix: str = "_compressed"


@dataclass
class CompressionResult:
    """Outcome and stats of a compression task."""
    input_path: str
    output_path: str
    success: bool
    original_size: int = 0
    compressed_size: int = 0
    saved_bytes: int = 0
    saved_percent: float = 0.0
    duration: float = 0.0
    elapsed_time: float = 0.0
    error_message: str = ""


# Common supported video file extensions
SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv",
    ".wmv", ".m4v", ".ts", ".mts", ".m2ts", ".3gp",
}


def is_video_file(path: str) -> bool:
    """Check if file extension is a recognized video container."""
    _, ext = os.path.splitext(path.lower())
    return ext in SUPPORTED_VIDEO_EXTENSIONS


def get_default_output_path(input_path: str, suffix: str = "_compressed", output_dir: Optional[str] = None) -> str:
    """Generate a clean output filename."""
    dir_name = output_dir if output_dir else os.path.dirname(input_path)
    base_name, _ = os.path.splitext(os.path.basename(input_path))
    out_filename = f"{base_name}{suffix}.mp4"
    return os.path.join(dir_name, out_filename)


def build_filter_string(
    meta: VideoMetadata,
    options: CompressionOptions,
) -> Optional[str]:
    """Construct FFmpeg -vf video filter graph (scale, fps)."""
    filters = []

    # Resolution scaling
    if options.resolution:
        scaled = parse_resolution_scale(options.resolution, meta.width, meta.height)
        if scaled:
            w, h = scaled
            filters.append(f"scale={w}:{h}")

    # FPS adjustment
    if options.fps and options.fps > 0 and abs(options.fps - meta.fps) > 0.5:
        filters.append(f"fps={options.fps}")

    return ",".join(filters) if filters else None


def compress_video(
    input_path: str,
    output_path: Optional[str] = None,
    options: Optional[CompressionOptions] = None,
    progress_callback: Optional[Callable[[float, str, str, str], None]] = None,
    cancel_event=None,
) -> CompressionResult:
    """Compress a single video file according to specified options.

    Args:
        input_path: Path to the input video.
        output_path: Optional path for compressed output.
        options: CompressionOptions instance.
        progress_callback: Callback receiving (overall_percent, status_message, speed, fps).
        cancel_event: threading.Event to abort compression.

    Returns:
        CompressionResult with before/after statistics.
    """
    if options is None:
        options = CompressionOptions()

    start_time = time.time()
    ok, err = check_ffmpeg_available()
    if not ok:
        return CompressionResult(
            input_path=input_path,
            output_path="",
            success=False,
            error_message=err,
        )

    meta = probe_video(input_path)
    if not meta:
        return CompressionResult(
            input_path=input_path,
            output_path="",
            success=False,
            error_message="Could not inspect or read video metadata with ffprobe.",
        )

    dest_path = output_path or get_default_output_path(input_path, options.filename_suffix)
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

    # Check if target file already exists
    if os.path.abspath(input_path) == os.path.abspath(dest_path):
        return CompressionResult(
            input_path=input_path,
            output_path=dest_path,
            success=False,
            error_message="Output file cannot be identical to input file.",
        )

    # Determine whether two-pass is needed
    use_two_pass = options.two_pass
    if use_two_pass is None:
        use_two_pass = (options.mode == "target_size" and "nvenc" not in options.codec)

    # Video filters
    vf_string = build_filter_string(meta, options)
    ffmpeg_bin = get_ffmpeg_path()

    # Calculate bitrates if in target size mode
    video_bitrate_kbps = None
    audio_bitrate_kbps = options.audio_bitrate_kbps

    if options.mode == "target_size":
        if not options.target_size_bytes or options.target_size_bytes <= 0:
            return CompressionResult(
                input_path=input_path,
                output_path=dest_path,
                success=False,
                error_message="Target size mode selected but target size is invalid.",
            )
        video_bitrate_kbps, audio_bitrate_kbps = calculate_target_bitrate(
            duration_seconds=meta.duration,
            target_bytes=options.target_size_bytes,
            desired_audio_kbps=options.audio_bitrate_kbps,
        )

    # Temporary prefix for two-pass log files
    temp_pass_prefix = os.path.join(
        tempfile.gettempdir(),
        f"ffmpeg2pass_{os.getpid()}_{int(time.time() * 1000)}",
    )

    try:
        if use_two_pass and video_bitrate_kbps:
            # === TWO-PASS ENCODING ===
            # PASS 1
            def pass1_progress(pct, out_s, speed, fps):
                if progress_callback:
                    # Pass 1 maps to 0% - 50%
                    overall = pct * 0.5
                    msg = f"Pass 1/2 (Analyzing): {pct:.0f}%"
                    progress_callback(overall, msg, speed, f"{fps:.0f} fps")

            cmd_pass1 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-c:v", options.codec,
                "-b:v", f"{video_bitrate_kbps}k",
                "-pass", "1",
                "-passlogfile", temp_pass_prefix,
                "-preset", options.preset,
                "-an",
                "-f", "null",
                "-",
            ]
            if vf_string:
                cmd_pass1.extend(["-vf", vf_string])

            p1_ok, p1_err = run_ffmpeg(
                cmd_pass1,
                meta.duration,
                pass1_progress,
                cancel_event,
            )
            if not p1_ok:
                return CompressionResult(
                    input_path=input_path,
                    output_path=dest_path,
                    success=False,
                    error_message=f"Pass 1 failed: {p1_err}",
                    duration=meta.duration,
                    elapsed_time=time.time() - start_time,
                )

            # PASS 2
            def pass2_progress(pct, out_s, speed, fps):
                if progress_callback:
                    # Pass 2 maps to 50% - 100%
                    overall = 50.0 + (pct * 0.5)
                    msg = f"Pass 2/2 (Compressing): {pct:.0f}%"
                    progress_callback(overall, msg, speed, f"{fps:.0f} fps")

            cmd_pass2 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-c:v", options.codec,
                "-b:v", f"{video_bitrate_kbps}k",
                "-pass", "2",
                "-passlogfile", temp_pass_prefix,
                "-preset", options.preset,
                "-pix_fmt", "yuv420p",
            ]
            if vf_string:
                cmd_pass2.extend(["-vf", vf_string])

            # Audio setup for Pass 2
            _apply_audio_options(cmd_pass2, options, meta.has_audio, audio_bitrate_kbps)

            # Faststart for streaming MP4
            cmd_pass2.extend(["-movflags", "+faststart", dest_path])

            p2_ok, p2_err = run_ffmpeg(
                cmd_pass2,
                meta.duration,
                pass2_progress,
                cancel_event,
            )
            if not p2_ok:
                return CompressionResult(
                    input_path=input_path,
                    output_path=dest_path,
                    success=False,
                    error_message=f"Pass 2 failed: {p2_err}",
                    duration=meta.duration,
                    elapsed_time=time.time() - start_time,
                )

        else:
            # === SINGLE-PASS ENCODING ===
            def single_progress(pct, out_s, speed, fps):
                if progress_callback:
                    msg = f"Compressing: {pct:.0f}%"
                    progress_callback(pct, msg, speed, f"{fps:.0f} fps")

            cmd = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-c:v", options.codec,
            ]

            # Bitrate or CRF
            if options.mode == "target_size" and video_bitrate_kbps:
                cmd.extend([
                    "-b:v", f"{video_bitrate_kbps}k",
                    "-maxrate", f"{int(video_bitrate_kbps * 1.5)}k",
                    "-bufsize", f"{int(video_bitrate_kbps * 2)}k",
                ])
            else:
                # CRF Quality Mode
                if "nvenc" in options.codec:
                    cmd.extend(["-cq", str(options.crf)])
                else:
                    cmd.extend(["-crf", str(options.crf)])

            cmd.extend([
                "-preset", options.preset,
                "-pix_fmt", "yuv420p",
            ])

            if vf_string:
                cmd.extend(["-vf", vf_string])

            # Audio setup
            _apply_audio_options(cmd, options, meta.has_audio, audio_bitrate_kbps)

            cmd.extend(["-movflags", "+faststart", dest_path])

            sp_ok, sp_err = run_ffmpeg(
                cmd,
                meta.duration,
                single_progress,
                cancel_event,
            )
            if not sp_ok:
                return CompressionResult(
                    input_path=input_path,
                    output_path=dest_path,
                    success=False,
                    error_message=sp_err,
                    duration=meta.duration,
                    elapsed_time=time.time() - start_time,
                )

    finally:
        # Clean up temporary pass log files
        for f in glob.glob(f"{temp_pass_prefix}*"):
            try:
                os.remove(f)
            except OSError:
                pass

    elapsed = time.time() - start_time
    if not os.path.isfile(dest_path):
        return CompressionResult(
            input_path=input_path,
            output_path=dest_path,
            success=False,
            error_message="Output file was not created.",
            duration=meta.duration,
            elapsed_time=elapsed,
        )

    new_size = os.path.getsize(dest_path)
    old_size = meta.size_bytes
    saved = max(0, old_size - new_size)
    saved_pct = (saved / old_size * 100.0) if old_size > 0 else 0.0

    return CompressionResult(
        input_path=input_path,
        output_path=dest_path,
        success=True,
        original_size=old_size,
        compressed_size=new_size,
        saved_bytes=saved,
        saved_percent=saved_pct,
        duration=meta.duration,
        elapsed_time=elapsed,
    )


def _apply_audio_options(
    cmd: List[str],
    options: CompressionOptions,
    has_audio: bool,
    audio_bitrate_kbps: int,
):
    """Append appropriate audio codec and bitrate arguments to FFmpeg command."""
    if not has_audio or options.audio_mode == "mute":
        cmd.extend(["-an"])
    elif options.audio_mode == "copy":
        cmd.extend(["-c:a", "copy"])
    else:
        # Default: AAC re-encode
        cmd.extend([
            "-c:a", "aac",
            "-b:a", f"{audio_bitrate_kbps}k",
        ])

