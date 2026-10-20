"""KuroCompress — Modern Video Compressor Application.

Can be run in two modes:
1. User-Friendly Desktop GUI: Simply run `python app.py` (or double click).
2. Command-Line Interface (CLI): Pass arguments like `python app.py my_video.mp4 -s 25MB`.
"""

import argparse
import os
import sys
from typing import List

from core.calculator import parse_size
from core.compressor import CompressionOptions, is_video_file
from core.probe import probe_video
from ui.cli import print_banner, print_video_info, run_batch_cli, run_single_cli


def collect_input_files(target: str, recursive: bool = False) -> List[str]:
    """Collect valid video file paths from a file or folder."""
    files = []
    if os.path.isfile(target):
        if is_video_file(target):
            files.append(os.path.abspath(target))
    elif os.path.isdir(target):
        if recursive:
            for root_dir, _, filenames in os.walk(target):
                for fn in filenames:
                    fp = os.path.join(root_dir, fn)
                    if is_video_file(fp):
                        files.append(os.path.abspath(fp))
        else:
            for fn in os.listdir(target):
                fp = os.path.join(target, fn)
                if os.path.isfile(fp) and is_video_file(fp):
                    files.append(os.path.abspath(fp))
    return sorted(files)


def main():
    # If no arguments provided or --gui passed, launch user-friendly GUI
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        try:
            from ui.gui import launch_gui
            launch_gui()
            return
        except Exception as e:
            print(f"[!] Unable to launch graphical interface: {e}")
            print("[*] Falling back to CLI mode...")

    parser = argparse.ArgumentParser(
        prog="KuroCompress",
        description="High-performance, user-friendly video compression tool for Python.",
    )

    parser.add_argument(
        "input",
        nargs="?",
        help="Input video file path or directory of videos.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (for single video) or destination directory (for batch).",
    )
    parser.add_argument(
        "-s", "--target-size",
        help="Target maximum file size (e.g. '25MB', '8MB' for Discord, '10M', '500KB').",
    )
    parser.add_argument(
        "-c", "--crf",
        type=int,
        default=24,
        help="Constant Rate Factor (CRF) quality (18=near lossless, 24=balanced, 28=small). Default: 24.",
    )
    parser.add_argument(
        "-p", "--preset",
        default="medium",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"],
        help="Encoding speed preset. Default: medium.",
    )
    parser.add_argument(
        "-r", "--resolution",
        help="Output resolution limit (e.g. '1080p', '720p', '480p', '360p', '50%%', '1280x720').",
    )
    parser.add_argument(
        "-v", "--codec",
        default="libx264",
        help="Video codec: libx264 (H.264), libx265 (HEVC), libsvtav1 (AV1), h264_nvenc, hevc_nvenc. Default: libx264.",
    )
    parser.add_argument(
        "-a", "--audio",
        default="aac",
        choices=["aac", "copy", "mute"],
        help="Audio mode: aac (re-encode), copy (keep original), mute (remove audio). Default: aac.",
    )
    parser.add_argument(
        "--audio-bitrate",
        type=int,
        default=128,
        help="Audio bitrate in kbps when re-encoding (e.g. 128, 96, 64). Default: 128.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        help="Target framerate (e.g. 30, 24, 60).",
    )
    parser.add_argument(
        "--two-pass",
        action="store_true",
        help="Force 2-pass encoding (auto-enabled when --target-size is used).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process subdirectories recursively when input is a folder.",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Display video metadata and exit without compressing.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop Graphical User Interface.",
    )
    parser.add_argument(
        "--create-shortcut",
        action="store_true",
        help="Create a Windows desktop shortcut with the custom KuroCompress icon.",
    )

    args = parser.parse_args()

    if args.create_shortcut:
        from create_shortcut import create_desktop_shortcut
        create_desktop_shortcut()
        return

    if not args.input:
        from ui.gui import launch_gui
        launch_gui()
        return

    print_banner()

    # Collect files
    files = collect_input_files(args.input, recursive=args.recursive)
    if not files:
        print(f"[!] Error: No valid video files found at '{args.input}'.")
        sys.exit(1)

    # Info only mode
    if args.info:
        for f in files:
            meta = probe_video(f)
            if meta:
                print_video_info(meta)
        return

    # Determine mode & parse target size
    mode = "quality"
    target_bytes = None
    if args.target_size:
        mode = "target_size"
        try:
            target_bytes = parse_size(args.target_size)
        except ValueError as e:
            print(f"[!] Error parsing target size: {e}")
            sys.exit(1)

    # Normalize codec name
    codec = args.codec
    codec_map = {
        "h264": "libx264",
        "x264": "libx264",
        "h265": "libx265",
        "x265": "libx265",
        "hevc": "libx265",
        "av1": "libsvtav1",
        "nvenc": "h264_nvenc",
    }
    codec = codec_map.get(codec.lower(), codec)

    options = CompressionOptions(
        mode=mode,
        target_size_bytes=target_bytes,
        crf=args.crf,
        preset=args.preset,
        codec=codec,
        resolution=args.resolution,
        audio_mode=args.audio,
        audio_bitrate_kbps=args.audio_bitrate,
        fps=args.fps,
        two_pass=args.two_pass if args.two_pass else None,
    )

    if len(files) == 1:
        run_single_cli(files[0], args.output, options)
    else:
        run_batch_cli(files, args.output, options)


if __name__ == "__main__":
    main()

