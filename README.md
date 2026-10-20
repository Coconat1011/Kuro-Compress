# 🎬 KuroCompress — Modern Video Compressor App

**KuroCompress** is a modern, high-performance, and user-friendly video compression desktop application built with Python and FFmpeg.

It provides a sleek graphical user interface (GUI) with drag-and-drop support, quick presets for common platforms (Discord, WhatsApp, Email), quality sliders, batch processing, and live real-time encoding stats. It also doubles as a versatile Command-Line Interface (CLI) for scripting and automation.

---

## ✨ Features

- **📦 100% Offline & Fully Portable**:
  - **Built-in FFmpeg Suite**: Bundles standalone `ffmpeg.exe`, `ffprobe.exe`, and `ffplay.exe` directly inside the `bin/` directory.
  - Zero external installation or system PATH configuration required.
  - Portable video playback preview with built-in `ffplay`.
- **🎨 Sleek Monochrome Aesthetic**:
  - High-contrast black, white, and grey design inspired by its name (*Kuro*).
  - Built with CustomTkinter featuring dark and light modes.
  - **Custom KuroCompress Icon**: Integrated title bar icon, taskbar identity, header branding, and desktop shortcut icon.
  - **Drag & Drop**: Drop video files or entire folders straight into the app.
  - **Batch Queue**: Compress multiple videos in a single batch with individual file status and overall progress.
- **🎯 Target File Size Mode (2-Pass Encoding)**:
  - Compress videos to fit strictly under specific size limits.
  - **One-click presets**:
    - 🟣 **Discord Free** (8 MB)
    - 🟣 **Discord Nitro Basic** (25 MB)
    - 🟣 **Discord Nitro** (500 MB)
    - 🟢 **WhatsApp** (16 MB)
    - ⚙️ **Custom Size** (e.g., `15 MB`, `100 MB`, `1.2 GB`)
  - Automatically calculates ideal video and audio bitrates based on duration to avoid overshooting.
- **✨ Quality (CRF) Mode**:
  - Keep visual clarity while slashing file size.
  - Interactive CRF slider (18–36) with real-time guidance (Near Lossless, Balanced, High Compression).
- **📐 Resolution Downscaling**:
  - Keep Original, 1080p (Full HD), 720p (HD), 480p (SD), 360p, or 50% scale.
- **⚡ Codec & GPU Acceleration**:
  - **H.264 / AVC** (Default, universal compatibility across all devices and browsers).
  - **H.265 / HEVC** (Up to 50% smaller at identical quality).
  - **AV1** (Next-gen open efficiency).
  - **NVIDIA NVENC (GPU)**: Automatic detection of hardware GPU encoders for blazing fast encoding.
- **🔊 Audio Controls**:
  - Re-encode AAC (128 kbps, 96 kbps).
  - Copy original audio without re-encoding.
  - Mute (strip audio stream).
- **📊 Real-time Progress & Metrics**:
  - Smooth progress bar showing live speed multiplier (e.g. `2.5x`), current FPS, and time remaining.
  - Safe background threading — the GUI never freezes.
  - Ability to cancel compression at any time.
- **🎉 Instant Results**:
  - View exact space saved (e.g. `Saved 160.9 MB — 87.0% reduction`).
  - One-click buttons to **Open Output Folder** and **Play Video**.

---

## 🚀 Quick Start

### 1. Requirements

Ensure you have **Python 3.10+** installed. (FFmpeg is already built-in and bundled in `bin/`!).

Install the Python dependencies:
```bash
pip install -r requirements.txt
```

### 2. Launching the GUI

Simply run:
```bash
python app.py
```
*(Or double-click `app.py` on Windows).*

### 3. Create Desktop Shortcut with Icon
To create a Windows desktop shortcut with the KuroCompress icon:
```bash
python app.py --create-shortcut
```
*(You can also click the **"📌 Desktop Shortcut"** button inside the app header!)*

---

## 💻 Command-Line Interface (CLI)

KuroCompress also includes a full-featured CLI for terminal users and batch scripts:

### Basic Compression
```bash
# Compress using balanced quality preset (CRF 24)
python app.py my_video.mp4

# Compress to fit Discord 25MB limit (uses 2-pass encoding)
python app.py my_video.mp4 -s 25MB

# Compress to 8MB and downscale to 720p
python app.py my_video.mp4 -s 8MB -r 720p
```

### Advanced CLI Examples
```bash
# Inspect video metadata without compressing
python app.py my_video.mp4 --info

# Batch compress an entire folder of videos to 1080p H.265
python app.py ./videos/ -o ./compressed/ -v hevc -r 1080p

# Use ultra-fast speed preset and mute audio
python app.py input.mp4 -s 10MB -p ultrafast -a mute
```

### CLI Flag Reference
| Flag | Description | Example |
|------|-------------|---------|
| `input` | Input video file or directory | `video.mp4` or `./folder/` |
| `-o, --output` | Output destination file or folder | `-o compressed.mp4` |
| `-s, --target-size` | Target maximum file size | `-s 25MB`, `-s 8M` |
| `-c, --crf` | Constant Rate Factor (18-36) | `-c 26` |
| `-r, --resolution` | Max resolution or scale | `-r 1080p`, `-r 720p`, `-r 50%` |
| `-v, --codec` | Codec (`h264`, `hevc`, `av1`, `nvenc`) | `-v hevc` |
| `-p, --preset` | Speed preset (`fast`, `medium`, `slow`) | `-p fast` |
| `-a, --audio` | Audio mode (`aac`, `copy`, `mute`) | `-a copy` |
| `--fps` | Override framerate | `--fps 30` |
| `--recursive` | Process subdirectories recursively | `--recursive` |
| `--info` | Show metadata only | `--info` |
| `--gui` | Force launch desktop GUI | `--gui` |

---

## 📁 Project Architecture

```
Video Compressing App/
├── app.py                  # Main entrypoint (GUI launcher & CLI parser)
├── requirements.txt        # Dependencies
├── README.md               # Documentation & usage guide
├── core/
│   ├── probe.py            # ffprobe metadata extractor (resolution, fps, bitrate)
│   ├── calculator.py       # Bitrate from target size & aspect ratio calculators
│   ├── ffmpeg_runner.py    # Subprocess runner with real-time progress parsing
│   └── compressor.py       # 1-pass and 2-pass compression engine
└── ui/
    ├── gui.py              # CustomTkinter modern desktop GUI with Drag & Drop
    └── cli.py              # Rich terminal CLI output, tables, and progress bars
```

