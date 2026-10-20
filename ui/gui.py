"""Modern, user-friendly desktop GUI for KuroCompress using CustomTkinter and TkinterDnD2."""

import os
import re
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

try:
    import tkinterdnd2
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

from core.calculator import calculate_target_bitrate, parse_resolution_scale, parse_size
from core.compressor import (
    CompressionOptions,
    CompressionResult,
    compress_video,
    get_default_output_path,
    is_video_file,
)
from core.ffmpeg_runner import (
    check_ffmpeg_available,
    get_available_hardware_encoders,
    get_ffplay_path,
    is_ffmpeg_local,
)
from core.probe import VideoMetadata, format_duration, format_size, probe_video


# Define App Base Class with or without TkinterDnD
if DND_AVAILABLE:
    class AppBase(ctk.CTk, tkinterdnd2.TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            ctk.CTk.__init__(self, *args, **kwargs)
            self.TkdndVersion = tkinterdnd2.TkinterDnD._require(self)
else:
    class AppBase(ctk.CTk):
        pass


class VideoCompressorGUI(AppBase):
    """Main application window for KuroCompress."""

    def __init__(self):
        super().__init__()

        # Register explicit Windows AppUserModelID so taskbar groups & displays custom icon
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kurocompress.video.compressor.app")
            except Exception:
                pass

        # Window configuration
        self.title("KuroCompress — Modern Video Compressor")
        self.geometry("980x740")
        self.minsize(880, 680)

        # Apply Window Icon
        self._setup_window_icon()

        # Set appearance theme: Pure Black, White, and Grey
        ctk.set_appearance_mode("Dark")
        self.configure(fg_color="#0e0e10")

        # State tracking
        self.video_queue: List[Dict] = []  # List of {'path': str, 'meta': VideoMetadata}
        self.active_index: int = -1
        self.is_compressing: bool = False
        self.cancel_event = threading.Event()
        self.custom_output_dir: Optional[str] = None
        self.last_results: List[CompressionResult] = []

        # Available hardware encoders
        self.hardware_encoders = get_available_hardware_encoders()

        # Build UI layout
        self._build_header()
        self._build_main_layout()
        self._build_footer()

        # Check FFmpeg readiness
        self._verify_ffmpeg()

        # Register Drag and Drop if available
        if DND_AVAILABLE:
            self._setup_drag_and_drop()

    def _setup_window_icon(self):
        """Set window and taskbar icon from assets."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ico_path = os.path.join(base_dir, "assets", "icon.ico")
        png_path = os.path.join(base_dir, "assets", "icon.png")

        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        if os.path.exists(png_path):
            try:
                self._icon_photo_ref = ImageTk.PhotoImage(file=png_path)
                self.iconphoto(False, self._icon_photo_ref)
            except Exception:
                pass

    # ================= UI BUILDERS =================

    def _build_header(self):
        """Build the top navigation and title bar."""
        header = ctk.CTkFrame(self, corner_radius=0, height=60, fg_color="#141416", border_width=1, border_color="#222225")
        header.pack(fill="x", padx=0, pady=0)

        # Title & Logo
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=10)

        # Display Custom App Icon in Header
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        png_path = os.path.join(base_dir, "assets", "icon.png")
        if os.path.exists(png_path):
            try:
                pil_img = Image.open(png_path)
                self.header_logo = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(36, 36))
                logo_lbl = ctk.CTkLabel(title_box, image=self.header_logo, text="")
                logo_lbl.pack(side="left", padx=(0, 10))
            except Exception:
                pass

        title = ctk.CTkLabel(
            title_box,
            text="KuroCompress",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#ffffff",
        )
        title.pack(side="left")

        subtitle = ctk.CTkLabel(
            title_box,
            text="• Monochrome Video Compressor",
            font=ctk.CTkFont(size=12),
            text_color="#888888",
        )
        subtitle.pack(side="left", padx=(10, 0))

        # Right Controls: Desktop Shortcut + FFmpeg status + Dark/Light toggle
        controls_box = ctk.CTkFrame(header, fg_color="transparent")
        controls_box.pack(side="right", padx=20, pady=10)

        shortcut_btn = ctk.CTkButton(
            controls_box,
            text="📌 Desktop Shortcut",
            width=130,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
            command=self._create_desktop_shortcut_ui,
        )
        shortcut_btn.pack(side="left", padx=(0, 14))

        self.ffmpeg_badge = ctk.CTkLabel(
            controls_box,
            text="Checking FFmpeg...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a3a3a3",
        )
        self.ffmpeg_badge.pack(side="left", padx=(0, 16))

        self.theme_switch = ctk.CTkSwitch(
            controls_box,
            text="Dark",
            command=self._toggle_theme,
            onvalue="Dark",
            offvalue="Light",
            width=46,
            progress_color="#444444",
            button_color="#ffffff",
            button_hover_color="#d4d4d4",
            fg_color="#222222",
            text_color="#cccccc",
        )
        self.theme_switch.select()
        self.theme_switch.pack(side="left")

    def _build_main_layout(self):
        """Build the split pane: left file queue, right settings panel."""
        self.main_pane = ctk.CTkFrame(self, fg_color="transparent")
        self.main_pane.pack(fill="both", expand=True, padx=20, pady=(15, 10))

        # 2-column grid layout
        self.main_pane.grid_columnconfigure(0, weight=4)  # Queue (40%)
        self.main_pane.grid_columnconfigure(1, weight=5)  # Settings (60%)
        self.main_pane.grid_rowconfigure(0, weight=1)

        self._build_queue_section(self.main_pane)
        self._build_settings_section(self.main_pane)

    def _build_queue_section(self, parent):
        """Build the left column: Drop zone and queue list."""
        queue_card = ctk.CTkFrame(parent, corner_radius=12, fg_color="#18181b", border_width=1, border_color="#27272a")
        queue_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)

        # Drop Zone Button Card
        self.drop_zone = ctk.CTkFrame(
            queue_card,
            corner_radius=10,
            border_width=2,
            border_color="#3f3f46",
            fg_color="#121214",
        )
        self.drop_zone.pack(fill="x", padx=15, pady=15)

        drop_icon = ctk.CTkLabel(
            self.drop_zone,
            text="📥",
            font=ctk.CTkFont(size=32),
        )
        drop_icon.pack(pady=(12, 4))

        self.drop_text = ctk.CTkLabel(
            self.drop_zone,
            text="Drag & Drop videos here\nor browse from computer",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f4f4f5",
            justify="center",
        )
        self.drop_text.pack(pady=(0, 10))

        btn_row = ctk.CTkFrame(self.drop_zone, fg_color="transparent")
        btn_row.pack(pady=(0, 12))

        add_files_btn = ctk.CTkButton(
            btn_row,
            text="+ Add File(s)",
            width=100,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#ffffff",
            text_color="#000000",
            hover_color="#e4e4e7",
            command=self._on_browse_files,
        )
        add_files_btn.pack(side="left", padx=5)

        add_folder_btn = ctk.CTkButton(
            btn_row,
            text="+ Add Folder",
            width=100,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
            command=self._on_browse_folder,
        )
        add_folder_btn.pack(side="left", padx=5)

        # Queue Header Row
        queue_header = ctk.CTkFrame(queue_card, fg_color="transparent")
        queue_header.pack(fill="x", padx=15, pady=(5, 6))

        self.queue_count_label = ctk.CTkLabel(
            queue_header,
            text="Queue: 0 videos",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f4f4f5",
        )
        self.queue_count_label.pack(side="left")

        clear_btn = ctk.CTkButton(
            queue_header,
            text="Clear All",
            width=65,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color="#a1a1aa",
            hover_color="#27272a",
            command=self._clear_queue,
        )
        clear_btn.pack(side="right")

        # Scrollable list for loaded videos
        self.queue_scroll = ctk.CTkScrollableFrame(
            queue_card,
            corner_radius=8,
            fg_color="#121214",
        )
        self.queue_scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def _build_settings_section(self, parent):
        """Build the right column: Compression parameters, presets, and switches."""
        settings_card = ctk.CTkScrollableFrame(
            parent,
            corner_radius=12,
            fg_color="#18181b",
            border_width=1,
            border_color="#27272a",
        )
        settings_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=0)

        # Title
        settings_title = ctk.CTkLabel(
            settings_card,
            text="Compression Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#ffffff",
        )
        settings_title.pack(anchor="w", padx=15, pady=(15, 10))

        # 1. MODE SELECTION (Target Size vs Quality CRF)
        mode_label = ctk.CTkLabel(
            settings_card,
            text="COMPRESSION MODE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a1a1aa",
        )
        mode_label.pack(anchor="w", padx=15, pady=(5, 4))

        self.mode_segment = ctk.CTkSegmentedButton(
            settings_card,
            values=["🎯 Target File Size", "✨ Quality (CRF)"],
            command=self._on_mode_change,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            selected_color="#3f3f46",
            selected_hover_color="#52525b",
            unselected_color="#18181b",
            unselected_hover_color="#27272a",
            text_color="#ffffff",
        )
        self.mode_segment.set("🎯 Target File Size")
        self.mode_segment.pack(fill="x", padx=15, pady=(0, 12))

        # --- CONTAINER A: Target Size Options ---
        self.target_size_frame = ctk.CTkFrame(
            settings_card,
            corner_radius=8,
            fg_color="#121214",
            border_width=1,
            border_color="#27272a",
        )
        self.target_size_frame.pack(fill="x", padx=15, pady=(0, 12))

        preset_row = ctk.CTkFrame(self.target_size_frame, fg_color="transparent")
        preset_row.pack(fill="x", padx=12, pady=10)

        size_presets = [
            ("Discord 8MB", "8"),
            ("Discord 25MB", "25"),
            ("WhatsApp 16MB", "16"),
            ("Nitro 500MB", "500"),
        ]
        self.size_preset_var = ctk.StringVar(value="25")
        for label, val in size_presets:
            btn = ctk.CTkRadioButton(
                preset_row,
                text=label,
                value=val,
                variable=self.size_preset_var,
                command=lambda v=val: self._on_size_preset_clicked(v),
                font=ctk.CTkFont(size=12),
                fg_color="#ffffff",
                border_color="#71717a",
                hover_color="#e4e4e7",
                text_color="#f4f4f5",
            )
            btn.pack(side="left", padx=(0, 10))

        custom_row = ctk.CTkFrame(self.target_size_frame, fg_color="transparent")
        custom_row.pack(fill="x", padx=12, pady=(0, 10))

        custom_lbl = ctk.CTkLabel(
            custom_row,
            text="Desired Maximum Size:",
            font=ctk.CTkFont(size=12),
            text_color="#d4d4d8",
        )
        custom_lbl.pack(side="left", padx=(0, 10))

        self.size_entry = ctk.CTkEntry(
            custom_row,
            width=70,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#18181b",
            border_color="#3f3f46",
            text_color="#ffffff",
        )
        self.size_entry.insert(0, "25")
        self.size_entry.pack(side="left", padx=(0, 6))

        self.size_unit = ctk.CTkComboBox(
            custom_row,
            values=["MB", "GB", "KB"],
            width=75,
            state="readonly",
            fg_color="#18181b",
            button_color="#27272a",
            button_hover_color="#3f3f46",
            border_color="#3f3f46",
            text_color="#ffffff",
        )
        self.size_unit.set("MB")
        self.size_unit.pack(side="left")

        size_hint = ctk.CTkLabel(
            self.target_size_frame,
            text="💡 Uses smart 2-pass encoding to ensure output fits strictly under this limit.",
            font=ctk.CTkFont(size=11),
            text_color="#a1a1aa",
            anchor="w",
        )
        size_hint.pack(fill="x", padx=12, pady=(0, 10))

        # --- CONTAINER B: Quality CRF Options (Hidden by default until toggled) ---
        self.quality_frame = ctk.CTkFrame(
            settings_card,
            corner_radius=8,
            fg_color="#121214",
            border_width=1,
            border_color="#27272a",
        )

        crf_title_row = ctk.CTkFrame(self.quality_frame, fg_color="transparent")
        crf_title_row.pack(fill="x", padx=12, pady=(10, 2))

        crf_lbl = ctk.CTkLabel(
            crf_title_row,
            text="Quality Factor (CRF):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f4f4f5",
        )
        crf_lbl.pack(side="left")

        self.crf_val_lbl = ctk.CTkLabel(
            crf_title_row,
            text="24 (Balanced)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#ffffff",
        )
        self.crf_val_lbl.pack(side="right")

        self.crf_slider = ctk.CTkSlider(
            self.quality_frame,
            from_=18,
            to=36,
            number_of_steps=18,
            command=self._on_crf_slider_changed,
            button_color="#ffffff",
            button_hover_color="#e4e4e7",
            progress_color="#71717a",
            fg_color="#27272a",
        )
        self.crf_slider.set(24)
        self.crf_slider.pack(fill="x", padx=12, pady=6)

        self.crf_hint_lbl = ctk.CTkLabel(
            self.quality_frame,
            text="Optimal balance of visual clarity and file size reduction.",
            font=ctk.CTkFont(size=11),
            text_color="#a1a1aa",
            anchor="w",
        )
        self.crf_hint_lbl.pack(fill="x", padx=12, pady=(0, 10))

        # 2. RESOLUTION SCALING
        res_label = ctk.CTkLabel(
            settings_card,
            text="OUTPUT RESOLUTION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a1a1aa",
        )
        res_label.pack(anchor="w", padx=15, pady=(8, 4))

        self.res_combo = ctk.CTkComboBox(
            settings_card,
            values=[
                "Keep Original Resolution",
                "1080p (Full HD)",
                "720p (HD - Great for Web)",
                "480p (SD - Smallest)",
                "360p (Ultra Compressed)",
                "50% Scale",
            ],
            state="readonly",
            height=32,
            fg_color="#18181b",
            button_color="#27272a",
            button_hover_color="#3f3f46",
            border_color="#3f3f46",
            text_color="#ffffff",
        )
        self.res_combo.set("Keep Original Resolution")
        self.res_combo.pack(fill="x", padx=15, pady=(0, 12))

        # 3. CODEC & HARDWARE ACCELERATION
        codec_label = ctk.CTkLabel(
            settings_card,
            text="VIDEO CODEC & ACCELERATION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a1a1aa",
        )
        codec_label.pack(anchor="w", padx=15, pady=(5, 4))

        codec_options = ["H.264 / AVC (Most Compatible)", "H.265 / HEVC (High Efficiency)", "AV1 (Next-Gen)"]
        if "h264_nvenc" in self.hardware_encoders:
            codec_options.append("NVIDIA NVENC H.264 (Blazing Fast GPU)")
        if "hevc_nvenc" in self.hardware_encoders:
            codec_options.append("NVIDIA NVENC HEVC (Blazing Fast GPU)")

        self.codec_combo = ctk.CTkComboBox(
            settings_card,
            values=codec_options,
            state="readonly",
            height=32,
            fg_color="#18181b",
            button_color="#27272a",
            button_hover_color="#3f3f46",
            border_color="#3f3f46",
            text_color="#ffffff",
        )
        self.codec_combo.set(codec_options[0])
        self.codec_combo.pack(fill="x", padx=15, pady=(0, 12))

        # 4. AUDIO & SPEED PRESETS (2-columns)
        adv_grid = ctk.CTkFrame(settings_card, fg_color="transparent")
        adv_grid.pack(fill="x", padx=15, pady=(0, 12))
        adv_grid.grid_columnconfigure(0, weight=1)
        adv_grid.grid_columnconfigure(1, weight=1)

        # Audio
        audio_lbl = ctk.CTkLabel(
            adv_grid,
            text="AUDIO OPTION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a1a1aa",
        )
        audio_lbl.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.audio_combo = ctk.CTkComboBox(
            adv_grid,
            values=["Re-encode AAC (128 kbps)", "Re-encode AAC (96 kbps)", "Copy Audio", "Mute (Remove Audio)"],
            state="readonly",
            height=30,
            fg_color="#18181b",
            button_color="#27272a",
            button_hover_color="#3f3f46",
            border_color="#3f3f46",
            text_color="#ffffff",
        )
        self.audio_combo.set("Re-encode AAC (128 kbps)")
        self.audio_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        # Speed / Preset
        speed_lbl = ctk.CTkLabel(
            adv_grid,
            text="ENCODING SPEED",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a1a1aa",
        )
        speed_lbl.grid(row=0, column=1, sticky="w", pady=(0, 4))

        self.speed_combo = ctk.CTkComboBox(
            adv_grid,
            values=["Medium (Recommended)", "Fast", "Very Fast", "Ultrafast", "Slow (Best Compression)"],
            state="readonly",
            height=30,
            fg_color="#18181b",
            button_color="#27272a",
            button_hover_color="#3f3f46",
            border_color="#3f3f46",
            text_color="#ffffff",
        )
        self.speed_combo.set("Medium (Recommended)")
        self.speed_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0))

        # 5. OUTPUT DESTINATION
        out_lbl = ctk.CTkLabel(
            settings_card,
            text="OUTPUT DESTINATION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#a1a1aa",
        )
        out_lbl.pack(anchor="w", padx=15, pady=(8, 4))

        out_box = ctk.CTkFrame(settings_card, fg_color="#121214", corner_radius=8, border_width=1, border_color="#27272a")
        out_box.pack(fill="x", padx=15, pady=(0, 15))

        self.out_mode_var = ctk.StringVar(value="same")

        r1 = ctk.CTkRadioButton(
            out_box,
            text="Save in same folder as original (appends '_compressed')",
            value="same",
            variable=self.out_mode_var,
            command=self._on_out_mode_toggle,
            font=ctk.CTkFont(size=12),
            fg_color="#ffffff",
            border_color="#71717a",
            hover_color="#e4e4e7",
            text_color="#f4f4f5",
        )
        r1.pack(anchor="w", padx=12, pady=(10, 6))

        r2_row = ctk.CTkFrame(out_box, fg_color="transparent")
        r2_row.pack(fill="x", padx=12, pady=(0, 10))

        self.r2 = ctk.CTkRadioButton(
            r2_row,
            text="Custom Folder:",
            value="custom",
            variable=self.out_mode_var,
            command=self._on_out_mode_toggle,
            font=ctk.CTkFont(size=12),
            fg_color="#ffffff",
            border_color="#71717a",
            hover_color="#e4e4e7",
            text_color="#f4f4f5",
        )
        self.r2.pack(side="left")

        self.out_dir_btn = ctk.CTkButton(
            r2_row,
            text="Select Folder...",
            width=110,
            height=26,
            font=ctk.CTkFont(size=11),
            command=self._on_select_output_dir,
            state="disabled",
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
        )
        self.out_dir_btn.pack(side="left", padx=10)

        self.out_dir_label = ctk.CTkLabel(
            r2_row,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#a1a1aa",
        )
        self.out_dir_label.pack(side="left", fill="x", expand=True)

    def _build_footer(self):
        """Build the bottom status, live progress bar, and primary action buttons."""
        footer = ctk.CTkFrame(self, corner_radius=0, fg_color="#141416", border_width=1, border_color="#222225")
        footer.pack(fill="x", side="bottom", padx=0, pady=0)

        inner = ctk.CTkFrame(footer, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        # Status text & Progress Info
        status_row = ctk.CTkFrame(inner, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 6))

        self.status_label = ctk.CTkLabel(
            status_row,
            text="Ready. Add videos to begin.",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
            anchor="w",
        )
        self.status_label.pack(side="left")

        self.stats_label = ctk.CTkLabel(
            status_row,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
            anchor="e",
        )
        self.stats_label.pack(side="right")

        # Smooth Progress Bar (Monochrome white on dark grey)
        self.progress_bar = ctk.CTkProgressBar(
            inner,
            height=10,
            corner_radius=5,
            progress_color="#ffffff",
            fg_color="#27272a",
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", pady=(0, 12))

        # Bottom Buttons Row
        action_row = ctk.CTkFrame(inner, fg_color="transparent")
        action_row.pack(fill="x")

        # Open Output Folder Button
        self.open_output_btn = ctk.CTkButton(
            action_row,
            text="📂 Open Output Folder",
            width=150,
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_output_btn.pack(side="left")

        # Cancel Button
        self.cancel_btn = ctk.CTkButton(
            action_row,
            text="⏹️ Cancel",
            width=110,
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
            command=self._cancel_compression,
            state="disabled",
        )
        self.cancel_btn.pack(side="right", padx=(10, 0))

        # Primary Compress Action Button (Crisp White with Jet Black text)
        self.compress_btn = ctk.CTkButton(
            action_row,
            text="🚀 Compress 0 Videos",
            width=180,
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#ffffff",
            text_color="#000000",
            hover_color="#d4d4d8",
            command=self._start_compression,
            state="disabled",
        )
        self.compress_btn.pack(side="right")

    # ================= LOGIC & EVENT HANDLERS =================

    def _create_desktop_shortcut_ui(self):
        """Create a desktop shortcut from GUI button click."""
        try:
            from create_shortcut import create_desktop_shortcut
            ok = create_desktop_shortcut()
            if ok:
                messagebox.showinfo("Desktop Shortcut", "✓ KuroCompress desktop shortcut created with custom icon!")
            else:
                messagebox.showwarning("Desktop Shortcut", "Could not create desktop shortcut automatically.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create shortcut: {e}")

    def _verify_ffmpeg(self):
        """Check FFmpeg availability and update badge."""
        ok, msg = check_ffmpeg_available()
        if ok:
            badge_text = "● Portable FFmpeg (Local)" if is_ffmpeg_local() else "● FFmpeg Ready"
            self.ffmpeg_badge.configure(
                text=badge_text,
                text_color="#ffffff",
            )
        else:
            self.ffmpeg_badge.configure(
                text="○ FFmpeg Missing!",
                text_color="#737373",
            )
            messagebox.showerror(
                "FFmpeg Not Found",
                "FFmpeg was not detected in project bin/ or on system PATH.\nPlease make sure FFmpeg is available to encode videos.",
            )

    def _setup_drag_and_drop(self):
        """Configure drag and drop event listeners."""
        try:
            self.drop_target_register(tkinterdnd2.DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except Exception:
            pass

    def _on_dnd_drop(self, event):
        """Handle dropped files or directories."""
        raw_data = event.data
        if not raw_data:
            return
        # Parse curly braced or whitespace-separated paths
        matches = re.findall(r"\{([^}]+)\}|(\S+)", raw_data)
        paths = [m[0] or m[1] for m in matches]
        self._add_paths_to_queue(paths)

    def _on_browse_files(self):
        """Open file dialog for videos."""
        files = filedialog.askopenfilenames(
            title="Select Video Files",
            filetypes=[
                ("Video Files", "*.mp4;*.mov;*.mkv;*.avi;*.webm;*.flv;*.wmv;*.m4v;*.ts"),
                ("All Files", "*.*"),
            ],
        )
        if files:
            self._add_paths_to_queue(list(files))

    def _on_browse_folder(self):
        """Open folder dialog to add all videos in directory."""
        folder = filedialog.askdirectory(title="Select Folder Containing Videos")
        if folder:
            self._add_paths_to_queue([folder])

    def _add_paths_to_queue(self, paths: List[str]):
        """Scan input paths and populate video queue with probed metadata."""
        collected = []
        for p in paths:
            if os.path.isfile(p):
                if is_video_file(p):
                    collected.append(p)
            elif os.path.isdir(p):
                for root_dir, _, filenames in os.walk(p):
                    for fn in filenames:
                        fp = os.path.join(root_dir, fn)
                        if is_video_file(fp):
                            collected.append(fp)

        # Remove duplicates
        existing_paths = {item["path"] for item in self.video_queue}
        new_items = [f for f in collected if f not in existing_paths]

        if not new_items:
            return

        for path in new_items:
            meta = probe_video(path)
            if meta:
                self.video_queue.append({"path": path, "meta": meta, "status": "Ready"})

        self._refresh_queue_display()

    def _refresh_queue_display(self):
        """Update the queue scroll view and counts."""
        # Clear existing widgets in scroll view
        for child in self.queue_scroll.winfo_children():
            child.destroy()

        count = len(self.video_queue)
        self.queue_count_label.configure(text=f"Queue: {count} video{'s' if count != 1 else ''}")

        if count == 0:
            empty_lbl = ctk.CTkLabel(
                self.queue_scroll,
                text="No videos added yet.\nUse the drop zone above to add videos.",
                text_color=("gray50", "gray55"),
                justify="center",
                font=ctk.CTkFont(size=12),
            )
            empty_lbl.pack(pady=40)
            self.compress_btn.configure(text="🚀 Compress 0 Videos", state="disabled")
            self.status_label.configure(text="Ready. Add videos to begin.")
            return

        total_bytes = sum(item["meta"].size_bytes for item in self.video_queue)
        self.status_label.configure(
            text=f"Ready to compress {count} video{'s' if count != 1 else ''} ({format_size(total_bytes)})"
        )
        self.compress_btn.configure(
            text=f"🚀 Compress {count} Video{'s' if count != 1 else ''}",
            state="normal",
        )

        for idx, item in enumerate(self.video_queue):
            meta: VideoMetadata = item["meta"]
            card = ctk.CTkFrame(self.queue_scroll, fg_color="#18181b", corner_radius=6, border_width=1, border_color="#27272a")
            card.pack(fill="x", padx=4, pady=3)

            # Left Info
            info_frame = ctk.CTkFrame(card, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True, padx=8, pady=6)

            name_lbl = ctk.CTkLabel(
                info_frame,
                text=meta.filename,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#ffffff",
                anchor="w",
            )
            name_lbl.pack(fill="x")

            sub_info = f"{meta.width}x{meta.height} • {format_duration(meta.duration)} • {format_size(meta.size_bytes)}"
            sub_lbl = ctk.CTkLabel(
                info_frame,
                text=sub_info,
                font=ctk.CTkFont(size=11),
                text_color="#a1a1aa",
                anchor="w",
            )
            sub_lbl.pack(fill="x")

            # Right: Status & Remove button
            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.pack(side="right", padx=6, pady=6)

            status_color = "#ffffff" if item["status"] == "Done" else ("#d4d4d8" if item["status"] == "Compressing" else "#71717a")
            status_lbl = ctk.CTkLabel(
                action_frame,
                text=item["status"],
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=status_color,
            )
            status_lbl.pack(side="left", padx=(0, 6))

            remove_btn = ctk.CTkButton(
                action_frame,
                text="✕",
                width=24,
                height=24,
                font=ctk.CTkFont(size=11),
                fg_color="transparent",
                hover_color="#27272a",
                text_color="#a1a1aa",
                command=lambda i=idx: self._remove_from_queue(i),
            )
            remove_btn.pack(side="right")

    def _remove_from_queue(self, index: int):
        """Remove item from queue if not currently compressing."""
        if self.is_compressing:
            return
        if 0 <= index < len(self.video_queue):
            self.video_queue.pop(index)
            self._refresh_queue_display()

    def _clear_queue(self):
        """Clear all items from queue."""
        if self.is_compressing:
            return
        self.video_queue.clear()
        self._refresh_queue_display()

    def _toggle_theme(self):
        """Toggle dark/light mode."""
        mode = self.theme_switch.get()
        ctk.set_appearance_mode(mode)
        self.theme_switch.configure(text=mode)

    def _on_mode_change(self, mode_str: str):
        """Switch between Target Size and Quality CRF cards."""
        if "Target" in mode_str:
            self.quality_frame.pack_forget()
            self.target_size_frame.pack(fill="x", padx=15, pady=(0, 12), before=self.res_combo)
        else:
            self.target_size_frame.pack_forget()
            self.quality_frame.pack(fill="x", padx=15, pady=(0, 12), before=self.res_combo)

    def _on_size_preset_clicked(self, val_str: str):
        """When a size radio preset is selected."""
        self.size_entry.delete(0, "end")
        self.size_entry.insert(0, val_str)
        self.size_unit.set("MB")

    def _on_crf_slider_changed(self, value):
        """Update CRF slider display and advice text."""
        val = int(round(value))
        if val <= 20:
            desc = "Near Lossless (minimal compression, maximum quality)"
        elif val <= 25:
            desc = "Balanced (optimal quality with great size reduction)"
        elif val <= 30:
            desc = "High Compression (very small file, slight detail loss)"
        else:
            desc = "Maximum Crunch (extreme file size reduction)"

        self.crf_val_lbl.configure(text=f"{val}")
        self.crf_hint_lbl.configure(text=desc)

    def _on_out_mode_toggle(self):
        """Handle output mode toggle."""
        if self.out_mode_var.get() == "custom":
            self.out_dir_btn.configure(state="normal")
            if not self.custom_output_dir:
                self._on_select_output_dir()
        else:
            self.out_dir_btn.configure(state="disabled")
            self.out_dir_label.configure(text="")

    def _on_select_output_dir(self):
        """Pick a custom output folder."""
        folder = filedialog.askdirectory(title="Choose Destination Folder")
        if folder:
            self.custom_output_dir = folder
            short_name = os.path.basename(folder) or folder
            self.out_dir_label.configure(text=short_name)
        else:
            if not self.custom_output_dir:
                self.out_mode_var.set("same")
                self.out_dir_btn.configure(state="disabled")

    def _get_selected_options(self) -> CompressionOptions:
        """Parse current UI configuration into CompressionOptions."""
        mode_str = self.mode_segment.get()
        mode = "target_size" if "Target" in mode_str else "quality"

        target_size_bytes = None
        if mode == "target_size":
            try:
                num = self.size_entry.get().strip()
                unit = self.size_unit.get().strip()
                target_size_bytes = parse_size(f"{num}{unit}")
            except Exception:
                target_size_bytes = 25 * 1024 * 1024  # Default 25 MB

        crf = int(round(self.crf_slider.get()))

        # Codec map
        codec_choice = self.codec_combo.get()
        codec = "libx264"
        if "H.265" in codec_choice:
            codec = "libx265"
        elif "AV1" in codec_choice:
            codec = "libsvtav1"
        elif "NVIDIA NVENC H.264" in codec_choice:
            codec = "h264_nvenc"
        elif "NVIDIA NVENC HEVC" in codec_choice:
            codec = "hevc_nvenc"

        # Resolution map
        res_choice = self.res_combo.get()
        res_str = None
        if "1080p" in res_choice:
            res_str = "1080p"
        elif "720p" in res_choice:
            res_str = "720p"
        elif "480p" in res_choice:
            res_str = "480p"
        elif "360p" in res_choice:
            res_str = "360p"
        elif "50%" in res_choice:
            res_str = "50%"

        # Audio map
        audio_choice = self.audio_combo.get()
        audio_mode = "aac"
        audio_bitrate = 128
        if "96 kbps" in audio_choice:
            audio_bitrate = 96
        elif "Copy Audio" in audio_choice:
            audio_mode = "copy"
        elif "Mute" in audio_choice:
            audio_mode = "mute"

        # Speed preset map
        speed_choice = self.speed_combo.get().lower()
        preset = "medium"
        if "ultrafast" in speed_choice:
            preset = "ultrafast"
        elif "very fast" in speed_choice:
            preset = "veryfast"
        elif "fast" in speed_choice:
            preset = "fast"
        elif "slow" in speed_choice:
            preset = "slow"

        return CompressionOptions(
            mode=mode,
            target_size_bytes=target_size_bytes,
            crf=crf,
            preset=preset,
            codec=codec,
            resolution=res_str,
            audio_mode=audio_mode,
            audio_bitrate_kbps=audio_bitrate,
        )

    def _start_compression(self):
        """Initiate background compression job."""
        if not self.video_queue:
            return

        self.is_compressing = True
        self.cancel_event.clear()
        self.last_results.clear()

        # Update controls
        self.compress_btn.configure(state="disabled", text="⏳ Compressing...")
        self.cancel_btn.configure(state="normal")
        self.open_output_btn.configure(state="disabled")
        self.progress_bar.set(0.0)

        opts = self._get_selected_options()

        # Start thread
        worker = threading.Thread(
            target=self._compression_worker,
            args=(opts,),
            daemon=True,
        )
        worker.start()

    def _cancel_compression(self):
        """Signal background worker to cancel."""
        if self.is_compressing:
            self.cancel_event.set()
            self.status_label.configure(text="Cancelling compression...")
            self.cancel_btn.configure(state="disabled")

    def _compression_worker(self, options: CompressionOptions):
        """Worker thread processing queue sequentially."""
        total_files = len(self.video_queue)
        results = []

        out_dir = self.custom_output_dir if self.out_mode_var.get() == "custom" else None

        for idx, item in enumerate(self.video_queue):
            if self.cancel_event.is_set():
                break

            self.active_index = idx
            in_path = item["path"]
            item["status"] = "Compressing"
            self.after(0, self._refresh_queue_display)

            out_path = get_default_output_path(in_path, options.filename_suffix, output_dir=out_dir)

            def progress_hook(pct, msg, speed, fps_str):
                # Calculate overall batch progress
                overall_batch_pct = ((idx + (pct / 100.0)) / total_files)
                self.after(
                    0,
                    lambda p=overall_batch_pct, m=msg, s=speed, f=fps_str: self._update_progress_ui(
                        p, f"[{idx+1}/{total_files}] {m}", s, f
                    ),
                )

            res = compress_video(
                input_path=in_path,
                output_path=out_path,
                options=options,
                progress_callback=progress_hook,
                cancel_event=self.cancel_event,
            )
            results.append(res)
            item["status"] = "Done" if res.success else "Failed"
            self.after(0, self._refresh_queue_display)

        self.last_results = results
        self.after(0, lambda: self._on_compression_finished(results))

    def _update_progress_ui(self, fraction: float, status_msg: str, speed: str, fps_str: str):
        """Safe UI update for progress metrics."""
        self.progress_bar.set(min(1.0, max(0.0, fraction)))
        self.status_label.configure(text=status_msg)
        stats = []
        if speed and speed != "1.0x":
            stats.append(f"Speed: {speed}")
        if fps_str and "0" not in fps_str:
            stats.append(fps_str)
        self.stats_label.configure(text="  •  ".join(stats))

    def _on_compression_finished(self, results: List[CompressionResult]):
        """Clean up and present completion results."""
        self.is_compressing = False
        self.compress_btn.configure(
            state="normal",
            text=f"🚀 Compress {len(self.video_queue)} Video{'s' if len(self.video_queue) != 1 else ''}",
        )
        self.cancel_btn.configure(state="disabled")

        if self.cancel_event.is_set():
            self.status_label.configure(text="Compression cancelled.")
            self.stats_label.configure(text="")
            return

        successful = [r for r in results if r.success]
        if not successful:
            self.status_label.configure(text="Compression failed for all files.")
            self.stats_label.configure(text="")
            messagebox.showerror("Error", "None of the videos could be compressed.")
            return

        self.open_output_btn.configure(state="normal")
        self.progress_bar.set(1.0)

        total_orig = sum(r.original_size for r in successful)
        total_comp = sum(r.compressed_size for r in successful)
        total_saved = max(0, total_orig - total_comp)
        pct_saved = (total_saved / total_orig * 100.0) if total_orig > 0 else 0.0

        summary_msg = f"Done! {len(successful)} videos saved {format_size(total_saved)} ({pct_saved:.1f}% reduction)"
        self.status_label.configure(text=summary_msg)
        self.stats_label.configure(text=f"Total: {format_size(total_comp)}")

        # Show result dialog
        self._show_results_dialog(successful, total_orig, total_comp, total_saved, pct_saved)

    def _show_results_dialog(self, successful, total_orig, total_comp, total_saved, pct_saved):
        """Pop up celebratory results card in monochrome styling."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("🎉 Compression Complete!")
        dialog.geometry("520x360")
        dialog.resizable(False, False)
        dialog.configure(fg_color="#121214")
        dialog.transient(self)
        dialog.grab_set()

        card = ctk.CTkFrame(dialog, fg_color="transparent")
        card.pack(fill="both", expand=True, padx=25, pady=20)

        header_lbl = ctk.CTkLabel(
            card,
            text="🎉 Compression Finished Successfully!",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ffffff",
        )
        header_lbl.pack(pady=(0, 15))

        stats_box = ctk.CTkFrame(card, corner_radius=10, fg_color="#18181b", border_width=1, border_color="#27272a")
        stats_box.pack(fill="x", pady=(0, 15), padx=10)

        orig_row = ctk.CTkLabel(
            stats_box,
            text=f"Original Total:  {format_size(total_orig)}",
            font=ctk.CTkFont(size=13),
            text_color="#a1a1aa",
        )
        orig_row.pack(anchor="w", padx=16, pady=(12, 4))

        comp_row = ctk.CTkLabel(
            stats_box,
            text=f"Compressed Total:  {format_size(total_comp)}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        comp_row.pack(anchor="w", padx=16, pady=4)

        saved_row = ctk.CTkLabel(
            stats_box,
            text=f"Space Saved:  {format_size(total_saved)}  ({pct_saved:.1f}% reduction)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ffffff",
        )
        saved_row.pack(anchor="w", padx=16, pady=(4, 12))

        # Action Buttons
        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(fill="x", pady=(10, 0))

        open_folder_btn = ctk.CTkButton(
            btn_box,
            text="📂 Open Output Folder",
            height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
            command=lambda: [self._open_output_folder(), dialog.destroy()],
        )
        open_folder_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        if len(successful) == 1:
            play_btn = ctk.CTkButton(
                btn_box,
                text="▶️ Play Video",
                height=36,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#ffffff",
                text_color="#000000",
                hover_color="#d4d4d8",
                command=lambda: self._play_file(successful[0].output_path),
            )
            play_btn.pack(side="left", fill="x", expand=True, padx=6)

        close_btn = ctk.CTkButton(
            btn_box,
            text="Close",
            height=36,
            fg_color="#27272a",
            text_color="#f4f4f5",
            hover_color="#3f3f46",
            command=dialog.destroy,
        )
        close_btn.pack(side="right", padx=(6, 0))

    def _open_output_folder(self):
        """Open destination directory in OS File Explorer."""
        target_dir = None
        if self.last_results:
            first_successful = next((r for r in self.last_results if r.success), None)
            if first_successful and os.path.exists(first_successful.output_path):
                target_dir = os.path.dirname(first_successful.output_path)

        if not target_dir:
            target_dir = self.custom_output_dir or os.getcwd()

        if sys.platform == "win32":
            os.startfile(target_dir)
        elif sys.platform == "darwin":
            subprocess.run(["open", target_dir])
        else:
            subprocess.run(["xdg-open", target_dir])

    def _play_file(self, file_path: str):
        """Launch video player with compressed file, using portable ffplay if present."""
        if not os.path.exists(file_path):
            return
        ffplay_bin = get_ffplay_path()
        if os.path.isfile(ffplay_bin):
            try:
                subprocess.Popen([ffplay_bin, "-autoexit", file_path])
                return
            except Exception:
                pass
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", file_path])
        else:
            subprocess.run(["xdg-open", file_path])


def launch_gui():
    """Start the GUI event loop."""
    app = VideoCompressorGUI()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()

