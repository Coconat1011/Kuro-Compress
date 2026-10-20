"""Terminal CLI interface with Rich formatting and progress bars."""

import os
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from core.compressor import (
    CompressionOptions,
    CompressionResult,
    compress_video,
    get_default_output_path,
    is_video_file,
)
from core.probe import VideoMetadata, format_duration, format_size, probe_video

console = Console()


def print_banner():
    """Display stylish ASCII / Rich banner."""
    raw_banner = r"""
  _  __                 ____                                            
 | |/ /   _ _ __ ___   / ___|___  _ __ ___  _ __  _ __ ___  ___ ___ 
 | ' / | | | '__/ _ \ | |   / _ \| '_ ` _ \| '_ \| '__/ _ \/ __/ __|
 | . \ |_| | | | (_) || |__| (_) | | | | | | |_) | | |  __/\__ \__ \
 |_|\_\__,_|_|  \___/  \____\___/|_| |_| |_| .__/|_|  \___||___/___/
                                            |_|                     
"""
    console.print(raw_banner, style="bold white")
    console.print(
        Panel(
            "[bold white]KuroCompress[/bold white] — High-Performance Video Compression Tool\n"
            "[grey70]Supports Target File Sizes (Discord/WhatsApp), Quality Presets, Hardware Acceleration[/grey70]",
            border_style="white",
            padding=(0, 2),
        )
    )


def print_video_info(meta: VideoMetadata):
    """Print metadata in a neat table."""
    table = Table(title=f"📹 Video Info: [bold white]{meta.filename}[/bold white]", border_style="grey50")
    table.add_column("Property", style="bold white")
    table.add_column("Value", style="grey85")

    table.add_row("Resolution", f"{meta.width} x {meta.height}")
    table.add_row("Duration", format_duration(meta.duration))
    table.add_row("File Size", format_size(meta.size_bytes))
    table.add_row("Video Codec", meta.video_codec.upper())
    table.add_row("Audio Codec", (meta.audio_codec or "None").upper())
    table.add_row("Frame Rate", f"{meta.fps:.2f} fps")
    table.add_row("Total Bitrate", f"{meta.total_bitrate / 1000:.0f} kbps" if meta.total_bitrate else "Unknown")

    console.print(table)


def run_single_cli(
    input_path: str,
    output_path: Optional[str],
    options: CompressionOptions,
) -> CompressionResult:
    """Run single video compression with Rich live progress."""
    meta = probe_video(input_path)
    if not meta:
        console.print(f"[bold white]Error:[/bold white] [grey70]Could not probe video: {input_path}[/grey70]")
        return CompressionResult(input_path=input_path, output_path="", success=False, error_message="Probe failed")

    print_video_info(meta)

    dest = output_path or get_default_output_path(input_path, options.filename_suffix)
    console.print(f"\n[bold white]→ Compressing to:[/bold white] [grey70]{dest}[/grey70]\n")

    with Progress(
        SpinnerColumn(style="white"),
        TextColumn("[bold white]{task.description}"),
        BarColumn(bar_width=40, style="grey23", complete_style="white", finished_style="white"),
        TextColumn("[white]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("[grey70]{task.fields[speed]}"),
        TextColumn("•"),
        TextColumn("[grey70]{task.fields[fps]}"),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(
            "Compressing",
            total=100.0,
            speed="1.0x",
            fps="",
        )

        def progress_cb(pct, status_msg, speed, fps_str):
            progress.update(
                task_id,
                completed=pct,
                description=status_msg,
                speed=f"Speed: {speed}",
                fps=fps_str,
            )

        res = compress_video(
            input_path=input_path,
            output_path=dest,
            options=options,
            progress_callback=progress_cb,
        )

    if res.success:
        console.print("\n[bold white]✓ Compression Completed Successfully![/bold white]")
        summary = Table(show_header=False, border_style="grey50")
        summary.add_row("Original Size", format_size(res.original_size))
        summary.add_row("Compressed Size", format_size(res.compressed_size))
        summary.add_row("Space Saved", f"[bold white]{format_size(res.saved_bytes)} ({res.saved_percent:.1f}% reduction)[/bold white]")
        summary.add_row("Time Elapsed", f"{res.elapsed_time:.1f} seconds")
        summary.add_row("Output Location", res.output_path)
        console.print(summary)
    else:
        console.print(f"\n[bold white]✕ Compression Failed:[/bold white] [grey70]{res.error_message}[/grey70]")

    return res


def run_batch_cli(
    file_list: List[str],
    output_dir: Optional[str],
    options: CompressionOptions,
):
    """Run batch compression across multiple files."""
    console.print(f"\n[bold white]Found {len(file_list)} videos for batch processing.[/bold white]\n")
    results = []

    for idx, path in enumerate(file_list, 1):
        console.rule(f"[bold white]Video {idx} of {len(file_list)}: {os.path.basename(path)}[/bold white]")
        dest = get_default_output_path(path, options.filename_suffix, output_dir=output_dir)
        res = run_single_cli(path, dest, options)
        results.append(res)
        console.print()

    # Overall Summary Table
    table = Table(title="📊 Batch Compression Summary", border_style="grey50")
    table.add_column("File", style="white")
    table.add_column("Original", justify="right")
    table.add_column("Compressed", justify="right")
    table.add_column("Saved", justify="right", style="bold white")
    table.add_column("Status", justify="center")

    total_orig = sum(r.original_size for r in results if r.success)
    total_comp = sum(r.compressed_size for r in results if r.success)
    total_saved = max(0, total_orig - total_comp)

    for r in results:
        status_str = "[white]✓ Done[/white]" if r.success else "[grey50]✕ Failed[/grey50]"
        orig_s = format_size(r.original_size) if r.success else "-"
        comp_s = format_size(r.compressed_size) if r.success else "-"
        save_s = f"{r.saved_percent:.1f}%" if r.success else "-"
        table.add_row(os.path.basename(r.input_path), orig_s, comp_s, save_s, status_str)

    console.print(table)
    pct_total = (total_saved / total_orig * 100.0) if total_orig > 0 else 0.0
    console.print(
        f"\n[bold white]Total Space Saved:[/bold white] [bold white]{format_size(total_saved)}[/bold white] "
        f"([white]{pct_total:.1f}% total reduction[/white]) across {len(results)} videos."
    )
