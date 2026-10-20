"""FFmpeg subprocess runner with real-time progress parsing and cancellation support."""

import os
import re
import shutil
import subprocess
import threading
from typing import Callable, List, Optional, Tuple


def get_project_root() -> str:
    """Get the root project directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_binary_path(name: str) -> str:
    """Locate binary, prioritizing local project bin/ directory for 100% portable offline use."""
    root = get_project_root()
    exe_name = f"{name}.exe" if os.name == "nt" else name

    # 1. Check local bin/ folder
    local_bin = os.path.join(root, "bin", exe_name)
    if os.path.isfile(local_bin):
        return local_bin

    # 2. Check project root folder
    root_bin = os.path.join(root, exe_name)
    if os.path.isfile(root_bin):
        return root_bin

    # 3. Fall back to system PATH
    sys_bin = shutil.which(name)
    if sys_bin:
        return sys_bin

    return name


def get_ffmpeg_path() -> str:
    """Find the path to the ffmpeg executable."""
    return get_binary_path("ffmpeg")


def get_ffprobe_path() -> str:
    """Find the path to the ffprobe executable."""
    return get_binary_path("ffprobe")


def get_ffplay_path() -> str:
    """Find the path to the ffplay executable."""
    return get_binary_path("ffplay")


def is_ffmpeg_local() -> bool:
    """Check if the resolved ffmpeg is from the local bin/ folder."""
    p = get_ffmpeg_path()
    return os.path.isabs(p) and os.path.isfile(p) and "bin" in p


def check_ffmpeg_available() -> Tuple[bool, str]:
    """Check if FFmpeg and FFprobe are accessible."""
    ffmpeg_bin = get_ffmpeg_path()
    ffprobe_bin = get_ffprobe_path()

    has_ffmpeg = os.path.isfile(ffmpeg_bin) or shutil.which(ffmpeg_bin) is not None
    has_ffprobe = os.path.isfile(ffprobe_bin) or shutil.which(ffprobe_bin) is not None

    if not has_ffmpeg:
        return False, "FFmpeg executable not found (neither in local bin/ nor in system PATH)."
    if not has_ffprobe:
        return False, "FFprobe executable not found (neither in local bin/ nor in system PATH)."

    msg = "Built-in local FFmpeg" if is_ffmpeg_local() else "System FFmpeg"
    return True, f"{msg} is available."


def get_available_hardware_encoders() -> List[str]:
    """Detect available hardware encoders."""
    available = []
    ffmpeg_bin = get_ffmpeg_path()
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        output = res.stdout
        checks = [
            ("h264_nvenc", "NVIDIA NVENC H.264"),
            ("hevc_nvenc", "NVIDIA NVENC HEVC"),
            ("av1_nvenc", "NVIDIA NVENC AV1"),
            ("h264_qsv", "Intel QSV H.264"),
            ("hevc_qsv", "Intel QSV HEVC"),
            ("h264_amf", "AMD AMF H.264"),
            ("hevc_amf", "AMD AMF HEVC"),
        ]
        for encoder_id, _ in checks:
            if re.search(rf"\b{re.escape(encoder_id)}\b", output):
                available.append(encoder_id)
    except Exception:
        pass
    return available


def parse_progress_time_us(time_str: str) -> Optional[float]:
    """Convert FFmpeg out_time_us or out_time string to seconds."""
    if not time_str:
        return None
    try:
        # If integer microseconds
        return int(time_str) / 1_000_000.0
    except ValueError:
        pass

    # If HH:MM:SS.micro format
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        try:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600.0 + m * 60.0 + s
        except ValueError:
            pass
    return None


def run_ffmpeg(
    cmd: List[str],
    total_duration: float,
    progress_callback: Optional[Callable[[float, float, str, float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[bool, str]:
    """Run an FFmpeg command while monitoring progress.

    Args:
        cmd: Full FFmpeg command arguments.
        total_duration: Expected total video duration in seconds.
        progress_callback: Callback receiving (percent 0-100, elapsed_seconds, speed_str, fps).
        cancel_event: Event to trigger graceful termination.

    Returns:
        (success: bool, error_message: str)
    """
    # Ensure progress output via pipe:1
    full_cmd = list(cmd)
    if "-progress" not in full_cmd:
        full_cmd.extend(["-progress", "pipe:1", "-nostats"])

    # Creation flag for Windows to prevent popping up console windows if inside GUI
    creation_flags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW = 0x08000000
        creation_flags = 0x08000000

    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
            bufsize=1,
        )
    except Exception as e:
        return False, f"Failed to start FFmpeg: {e}"

    stderr_output = []

    def read_stderr():
        for line in proc.stderr:
            stderr_output.append(line)

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    current_fps = 0.0
    current_speed = "1.0x"
    last_reported_percent = 0.0

    try:
        for raw_line in proc.stdout:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return False, "Compression cancelled by user."

            line = raw_line.strip()
            if not line:
                continue

            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()

                if key == "fps":
                    try:
                        current_fps = float(val)
                    except ValueError:
                        pass
                elif key == "speed":
                    current_speed = val if val else "1.0x"
                elif key in ("out_time_us", "out_time_ms", "out_time"):
                    out_s = parse_progress_time_us(val)
                    if out_s is not None and total_duration > 0:
                        pct = min(100.0, max(0.0, (out_s / total_duration) * 100.0))
                        last_reported_percent = pct
                        if progress_callback:
                            progress_callback(pct, out_s, current_speed, current_fps)
                elif key == "progress" and val == "end":
                    if progress_callback:
                        progress_callback(100.0, total_duration, current_speed, current_fps)

        proc.wait()
        stderr_thread.join(timeout=1)

        if cancel_event and cancel_event.is_set():
            return False, "Compression cancelled by user."

        if proc.returncode != 0:
            err_text = "".join(stderr_output[-20:]).strip()
            return False, err_text or f"FFmpeg exited with error code {proc.returncode}"

        if progress_callback and last_reported_percent < 100.0:
            progress_callback(100.0, total_duration, current_speed, current_fps)

        return True, ""

    except Exception as e:
        if proc.poll() is None:
            proc.kill()
        return False, str(e)

