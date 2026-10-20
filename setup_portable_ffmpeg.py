"""Script to download and setup standalone portable FFmpeg binaries into bin/ folder."""

import io
import os
import shutil
import sys
import urllib.request
import zipfile


def download_ffmpeg():
    """Download official Gyan FFmpeg static build for Windows and unpack into bin/."""
    if sys.platform != "win32":
        print("This helper is intended for Windows. On Linux/macOS, install ffmpeg via your package manager (brew/apt).")
        return

    bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "bin"))
    os.makedirs(bin_dir, exist_ok=True)

    ffmpeg_exe = os.path.join(bin_dir, "ffmpeg.exe")
    ffprobe_exe = os.path.join(bin_dir, "ffprobe.exe")
    ffplay_exe = os.path.join(bin_dir, "ffplay.exe")

    if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
        print(f"✓ Standalone FFmpeg already exists in {bin_dir}!")
        return

    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    print(f"Downloading portable FFmpeg from: {url}")
    print("This may take 1-2 minutes depending on your internet connection...")

    try:
        # Download with progress
        def reporthook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100.0, downloaded * 100.0 / total_size)
                mb_down = downloaded / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                sys.stdout.write(f"\rProgress: {percent:.1f}% ({mb_down:.1f}/{mb_total:.1f} MB)")
                sys.stdout.flush()

        temp_zip = os.path.join(bin_dir, "ffmpeg_temp.zip")
        urllib.request.urlretrieve(url, temp_zip, reporthook)
        print("\nDownload complete! Unpacking binaries...")

        with zipfile.ZipFile(temp_zip, "r") as z:
            for member in z.namelist():
                base = os.path.basename(member).lower()
                if base in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe"):
                    target_file = os.path.join(bin_dir, base)
                    with z.open(member) as src, open(target_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    print(f"Extracted {base} -> {target_file}")

        if os.path.exists(temp_zip):
            os.remove(temp_zip)

        print("\n✓ Portable FFmpeg setup complete! KuroCompress is now 100% self-contained.")
    except Exception as e:
        print(f"\nError downloading FFmpeg: {e}")
        print("Note: If FFmpeg is already installed in your system PATH, KuroCompress can also use that directly.")


if __name__ == "__main__":
    download_ffmpeg()

