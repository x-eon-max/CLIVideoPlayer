#!/usr/bin/env python3
"""
🎬 CLI Video Player v3.0 - High-Performance Terminal Video & ASCII Engine
https://github.com/x-eon-max/CLIVideoPlayer
"""

import os
import sys
import time
import shutil
import signal
import atexit
import argparse
import tempfile
import subprocess
import threading
from queue import Queue, Empty

# Suppress Pygame welcome banner
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import cv2
import numpy as np
import pygame

# ANSI Terminal Codes
ANSI_RESET = b"\033[0m"
ANSI_HOME = b"\033[H"
ANSI_CLEAR = b"\033[2J"
ANSI_HIDE_CURSOR = b"\033[?25l"
ANSI_SHOW_CURSOR = b"\033[?25h"

DEFAULT_WIDTH = 120
QUEUE_SIZE = 64

# ASCII Luminance Ramp
ASCII_CHARS = np.array(list(" ░▒▓█"))
ASCII_CHARS_BYTES = [c.encode("utf-8") for c in ASCII_CHARS]

# Known standard resolution presets
KNOWN_RESOLUTIONS = [
    ("auto", "Auto (Fit current terminal window)"),
    ("80", "Compact (80 cols - Classic 80x24)"),
    ("100", "Medium (100 cols)"),
    ("120", "Standard (120 cols - CLIVideoPlayer Default)"),
    ("160", "HD (160 cols - High Detail)"),
    ("200", "Full HD (200 cols - Ultra Detail)"),
    ("240", "Ultra HD (240 cols - Extreme Detail)"),
    ("custom", "Custom width..."),
]

# Known standard framerate presets
KNOWN_FPS = [
    ("native", "Native Framerate (Original video FPS)"),
    ("15", "15 FPS (Low CPU / Remote SSH / Light)"),
    ("24", "24 FPS (Cinematic standard)"),
    ("30", "30 FPS (Standard smooth)"),
    ("60", "60 FPS (Ultra smooth)"),
    ("custom", "Custom framerate..."),
]

# Available color rendering modes
COLOR_MODES = [
    ("ansi16", "16 ANSI Colors (Vibrant & ultra-fast - Recommended)"),
    ("256", "256 Colors (Extended xterm color cube)"),
    ("ansi8", "8 ANSI Colors (Classic retro terminal palette)"),
    ("gray", "Grayscale ASCII (High-contrast monochrome art)"),
    ("truecolor", "24-bit TrueColor RGB (Pixel-accurate RGB)"),
]

# Temporary files to clean up on exit
_temp_files = []


def cleanup_temp_files():
    """Clean up extracted temporary audio or scratch files."""
    for path in _temp_files:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


atexit.register(cleanup_temp_files)


def restore_terminal():
    """Ensure cursor and colors are restored on exit."""
    try:
        sys.stdout.buffer.write(ANSI_SHOW_CURSOR + ANSI_RESET + b"\n")
        sys.stdout.buffer.flush()
    except Exception:
        pass


atexit.register(restore_terminal)


# ---------------------------------------------------------------------------
# Audio Extractor
# ---------------------------------------------------------------------------

def extract_audio(video_path: str) -> str | None:
    """Extract audio track from video to temporary WAV file using ffmpeg."""
    if not shutil.which("ffmpeg") or not os.path.exists(video_path):
        return None
    try:
        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_path = temp_file.name
        temp_file.close()
        _temp_files.append(temp_path)

        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", video_path,
            "-vn", "-ac", "2", "-ar", "44100",
            temp_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            return temp_path
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Non-blocking Keyboard Input Handler
# ---------------------------------------------------------------------------

class KeyboardHandler:
    """Cross-platform non-blocking keyboard input."""
    def __init__(self):
        self.is_windows = sys.platform == "win32"
        self.old_settings = None

    def __enter__(self):
        if not self.is_windows and sys.stdin.isatty():
            try:
                import termios
                import tty
                self.old_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.is_windows and self.old_settings is not None and sys.stdin.isatty():
            try:
                import termios
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass

    def get_char(self) -> str | None:
        if self.is_windows:
            try:
                import msvcrt
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    return ch.decode("utf-8", errors="ignore")
            except Exception:
                pass
            return None
        else:
            try:
                import select
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    return sys.stdin.read(1)
            except Exception:
                pass
            return None


# ---------------------------------------------------------------------------
# High-Performance Frame Renderers
# ---------------------------------------------------------------------------

class BaseRenderer:
    def render(self, frame: np.ndarray) -> bytes:
        raise NotImplementedError


class ANSI16Renderer(BaseRenderer):
    """16 ANSI Colors (8 Standard + 8 Bright) using precomputed 3D LUT."""
    def __init__(self):
        codes = [
            b"\033[30m", b"\033[31m", b"\033[32m", b"\033[33m",
            b"\033[34m", b"\033[35m", b"\033[36m", b"\033[37m",
            b"\033[90m", b"\033[91m", b"\033[92m", b"\033[93m",
            b"\033[94m", b"\033[95m", b"\033[96m", b"\033[97m"
        ]
        self.combo = np.array([col + ch for col in codes for ch in ASCII_CHARS_BYTES], dtype=object)

        rgb = np.array([
            (0, 0, 0),       (170, 0, 0),     (0, 170, 0),     (170, 85, 0),
            (0, 0, 170),     (170, 0, 170),   (0, 170, 170),   (170, 170, 170),
            (85, 85, 85),    (255, 85, 85),   (85, 255, 85),   (255, 255, 85),
            (85, 85, 255),   (255, 85, 255),  (85, 255, 255),  (255, 255, 255)
        ], dtype=np.int32)
        bgr = rgb[:, [2, 1, 0]]
        grid = np.arange(32, dtype=np.int32) * 8 + 4
        b_grid, g_grid, r_grid = np.meshgrid(grid, grid, grid, indexing="ij")
        pts = np.stack([b_grid, g_grid, r_grid], axis=-1)
        diff = pts[:, :, :, np.newaxis, :] - bgr[np.newaxis, np.newaxis, np.newaxis, :, :]
        self.lut = np.argmin(np.sum(diff**2, axis=-1), axis=-1).astype(np.uint8)

    def render(self, frame: np.ndarray) -> bytes:
        b3 = frame[:, :, 0] >> 3
        g3 = frame[:, :, 1] >> 3
        r3 = frame[:, :, 2] >> 3
        c_idx = self.lut[b3, g3, r3]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        a_idx = (gray.astype(np.uint16) * 4 // 255).astype(np.uint8)
        comb = c_idx * 5 + a_idx
        mapped = self.combo[comb]
        return b"\n".join([b"".join(r) for r in mapped]) + ANSI_RESET


class ANSI8Renderer(BaseRenderer):
    """8 Classic ANSI Colors using bitwise quantization."""
    def __init__(self):
        codes = [
            b"\033[30m", b"\033[34m", b"\033[32m", b"\033[36m",
            b"\033[31m", b"\033[35m", b"\033[33m", b"\033[37m"
        ]
        self.combo = np.array([col + ch for col in codes for ch in ASCII_CHARS_BYTES], dtype=object)

    def render(self, frame: np.ndarray) -> bytes:
        b = (frame[:, :, 0] >= 128).astype(np.uint8)
        g = (frame[:, :, 1] >= 128).astype(np.uint8)
        r = (frame[:, :, 2] >= 128).astype(np.uint8)
        c_idx = b | (g << 1) | (r << 2)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        a_idx = (gray.astype(np.uint16) * 4 // 255).astype(np.uint8)
        comb = c_idx * 5 + a_idx
        mapped = self.combo[comb]
        return b"\n".join([b"".join(r) for r in mapped]) + ANSI_RESET


class Color256Renderer(BaseRenderer):
    """256 Colors (xterm color cube) using fast indexing."""
    def __init__(self):
        codes = [f"\033[38;5;{c}m".encode("utf-8") for c in range(256)]
        self.combo = np.array([col + ch for col in codes for ch in ASCII_CHARS_BYTES], dtype=object)

    def render(self, frame: np.ndarray) -> bytes:
        b6 = (frame[:, :, 0].astype(np.uint16) * 6) >> 8
        g6 = (frame[:, :, 1].astype(np.uint16) * 6) >> 8
        r6 = (frame[:, :, 2].astype(np.uint16) * 6) >> 8
        c_idx = 16 + 36 * r6 + 6 * g6 + b6
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        a_idx = (gray.astype(np.uint16) * 4 // 255).astype(np.uint8)
        comb = c_idx * 5 + a_idx
        mapped = self.combo[comb]
        return b"\n".join([b"".join(r) for r in mapped]) + ANSI_RESET


class GrayscaleRenderer(BaseRenderer):
    """Monochrome ASCII renderer with minimal bandwidth."""
    def __init__(self):
        self.combo = np.array(ASCII_CHARS_BYTES, dtype=object)

    def render(self, frame: np.ndarray) -> bytes:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        a_idx = (gray.astype(np.uint16) * 4 // 255).astype(np.uint8)
        mapped = self.combo[a_idx]
        return b"\033[97m" + b"\n".join([b"".join(r) for r in mapped]) + ANSI_RESET


class TrueColorRenderer(BaseRenderer):
    """24-bit TrueColor RGB renderer."""
    def __init__(self):
        self.chars = ASCII_CHARS

    def render(self, frame: np.ndarray) -> bytes:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        a_idx = (gray.astype(np.uint16) * 4 // 255).astype(np.uint8)
        chars = self.chars[a_idx]
        b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
        lines = []
        for y in range(h):
            row_r, row_g, row_b = r[y], g[y], b[y]
            row_c = chars[y]
            line_str = "".join(f"\033[38;2;{row_r[x]};{row_g[x]};{row_b[x]}m{row_c[x]}" for x in range(w))
            lines.append(line_str.encode("utf-8"))
        return b"\n".join(lines) + ANSI_RESET


def get_renderer(mode: str) -> BaseRenderer:
    mode = str(mode).lower()
    if mode in ("ansi16", "16", "default"):
        return ANSI16Renderer()
    elif mode in ("256", "color256", "xterm"):
        return Color256Renderer()
    elif mode in ("ansi8", "8"):
        return ANSI8Renderer()
    elif mode in ("gray", "grayscale", "mono"):
        return GrayscaleRenderer()
    elif mode in ("truecolor", "24bit", "rgb"):
        return TrueColorRenderer()
    return ANSI16Renderer()


# ---------------------------------------------------------------------------
# Dimension and Duration Formatters
# ---------------------------------------------------------------------------

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def calculate_dimensions(width_choice, video_w: int, video_h: int) -> tuple[int, int]:
    """Calculate terminal display width and height preserving aspect ratio."""
    aspect_ratio = video_h / video_w if video_w > 0 else 9 / 16
    if width_choice == "auto":
        cols, lines = shutil.get_terminal_size((80, 24))
        w = max(20, cols - 2)
        max_h = max(8, lines - 3)
        h = max(1, int(w * aspect_ratio * 0.55))
        if h > max_h:
            h = max_h
            w = max(20, int(h / (aspect_ratio * 0.55)))
        return w, h
    else:
        try:
            w = int(width_choice)
        except ValueError:
            w = 120
        h = max(1, int(w * aspect_ratio * 0.55))
        return w, h


# ---------------------------------------------------------------------------
# Interactive Selectors
# ---------------------------------------------------------------------------

def scan_video_files() -> list[str]:
    """Scan current directory and common video locations for media files."""
    exts = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v"}
    found = []

    # Check current directory first
    for f in os.listdir("."):
        if any(f.lower().endswith(ext) for ext in exts):
            p = os.path.abspath(f)
            if os.path.isfile(p):
                found.append(p)

    # If few or none found, check home and common video directories
    if len(found) < 5:
        candidates = [
            os.path.expanduser("~"),
            os.path.expanduser("~/Videos"),
            os.path.expanduser("~/Vidéos"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Téléchargements"),
        ]
        for cdir in candidates:
            if os.path.isdir(cdir):
                try:
                    for f in os.listdir(cdir):
                        if any(f.lower().endswith(ext) for ext in exts):
                            p = os.path.abspath(os.path.join(cdir, f))
                            if os.path.isfile(p) and p not in found:
                                found.append(p)
                                if len(found) >= 30:
                                    break
                except Exception:
                    pass

    return sorted(found)


def probe_video_summary(video_path: str) -> str:
    """Probe video for quick summary details."""
    try:
        sz = format_size(os.path.getsize(video_path))
        cap = cv2.VideoCapture(video_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        dur = format_duration(frames / fps if fps > 0 else 0)
        cap.release()
        return f"{w}x{h}, {fps:.1f} fps, {dur}, {sz}"
    except Exception:
        return format_size(os.path.getsize(video_path))


def interactive_select_video() -> str:
    """Interactive video selector menu."""
    videos = scan_video_files()
    print("\n\033[1;36m╔═══════════════════════════════════════════════════════════════════════╗\033[0m")
    print("\033[1;36m║                      🎬 CLI VIDEO PLAYER v3.0                         ║\033[0m")
    print("\033[1;36m║            Ultra-Fast Multi-Threaded ASCII Video Engine               ║\033[0m")
    print("\033[1;36m╚═══════════════════════════════════════════════════════════════════════╝\033[0m\n")

    print("\033[1;33m📂 [1/4] Select Video File:\033[0m")
    display_limit = min(15, len(videos))
    for i in range(display_limit):
        p = videos[i]
        name = os.path.basename(p)
        info = probe_video_summary(p)
        print(f"  \033[1;32m[{i + 1}]\033[0m {name} \033[90m({info})\033[0m")

    if len(videos) > display_limit:
        print(f"  \033[90m... and {len(videos) - display_limit} more files\033[0m")

    print("  \033[1;33m[C]\033[0m Enter custom file path or URL")
    print("  \033[1;31m[Q]\033[0m Quit\n")

    while True:
        try:
            choice = input("\033[1mChoice [1..N / C / Q]: \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            sys.exit(0)

        if not choice and len(videos) > 0:
            return videos[0]
        if choice.lower() == "q":
            print("Exiting.")
            sys.exit(0)
        elif choice.lower() == "c":
            custom_path = input("Enter video file path: ").strip().strip("'\"")
            if os.path.exists(custom_path) and os.path.isfile(custom_path):
                return os.path.abspath(custom_path)
            else:
                print(f"\033[31mError: File not found: '{custom_path}'\033[0m")
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(videos):
                return videos[idx]
            else:
                print("\033[31mInvalid number. Try again.\033[0m")
        elif os.path.exists(choice) and os.path.isfile(choice):
            return os.path.abspath(choice)
        else:
            print("\033[31mInvalid option. Try again.\033[0m")


def interactive_select_resolution(video_w: int, video_h: int) -> int | str:
    """Interactive resolution selector menu among standard presets."""
    aspect_ratio = video_h / video_w if video_w > 0 else 9 / 16
    print("\n\033[1;33m📐 [2/4] Select Display Resolution:\033[0m")
    
    for i, (key, desc) in enumerate(KNOWN_RESOLUTIONS, 1):
        if key == "auto":
            cols, lines = shutil.get_terminal_size((80, 24))
            w, h = calculate_dimensions("auto", video_w, video_h)
            tag = f"\033[90m-> {w}x{h} (terminal: {cols}x{lines})\033[0m"
        elif key == "custom":
            tag = "\033[90m-> enter arbitrary width\033[0m"
        else:
            w, h = calculate_dimensions(int(key), video_w, video_h)
            tag = f"\033[90m-> {w} cols x {h} lines\033[0m"
        
        default_marker = " \033[1;36m(Default)\033[0m" if key == "120" else ""
        print(f"  \033[1;32m[{i}]\033[0m {desc:45s} {tag}{default_marker}")

    while True:
        try:
            choice = input("\n\033[1mSelect resolution [1-8] (default: 4): \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            sys.exit(0)

        if not choice:
            return 120
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(KNOWN_RESOLUTIONS):
                key = KNOWN_RESOLUTIONS[idx][0]
                if key == "custom":
                    try:
                        val = int(input("Enter custom terminal width (e.g. 140): ").strip())
                        return max(20, val)
                    except ValueError:
                        print("\033[31mInvalid number. Using 120.\033[0m")
                        return 120
                elif key == "auto":
                    return "auto"
                else:
                    return int(key)
        print("\033[31mInvalid selection. Try again.\033[0m")


def interactive_select_framerate(native_fps: float) -> float:
    """Interactive framerate selector menu."""
    print(f"\n\033[1;33m⏱️  [3/4] Select Playback Framerate (Native: {native_fps:.2f} FPS):\033[0m")
    
    for i, (key, desc) in enumerate(KNOWN_FPS, 1):
        default_marker = " \033[1;36m(Default)\033[0m" if key == "native" else ""
        print(f"  \033[1;32m[{i}]\033[0m {desc:50s}{default_marker}")

    while True:
        try:
            choice = input(f"\n\033[1mSelect framerate [1-6] (default: 1): \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            sys.exit(0)

        if not choice:
            return native_fps
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(KNOWN_FPS):
                key = KNOWN_FPS[idx][0]
                if key == "native":
                    return native_fps
                elif key == "custom":
                    try:
                        val = float(input("Enter custom FPS (e.g. 25.0): ").strip())
                        return max(1.0, val)
                    except ValueError:
                        print("\033[31mInvalid number. Using native FPS.\033[0m")
                        return native_fps
                else:
                    return float(key)
        print("\033[31mInvalid selection. Try again.\033[0m")


def interactive_select_color_mode() -> str:
    """Interactive color mode selector."""
    print("\n\033[1;33m🎨 [4/4] Select Color Palette:\033[0m")
    
    for i, (key, desc) in enumerate(COLOR_MODES, 1):
        default_marker = " \033[1;36m(Default)\033[0m" if key == "ansi16" else ""
        print(f"  \033[1;32m[{i}]\033[0m {desc:55s}{default_marker}")

    while True:
        try:
            choice = input(f"\n\033[1mSelect color mode [1-5] (default: 1): \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            sys.exit(0)

        if not choice:
            return "ansi16"
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(COLOR_MODES):
                return COLOR_MODES[idx][0]
        print("\033[31mInvalid selection. Try again.\033[0m")


# ---------------------------------------------------------------------------
# Main VideoPlayer Engine
# ---------------------------------------------------------------------------

class VideoPlayer:
    def __init__(
        self,
        video_path: str,
        audio_path: str = None,
        width: int | str = 120,
        target_fps: float = None,
        color_mode: str = "ansi16",
        enable_audio: bool = True,
        show_hud: bool = True
    ):
        self.video_path = video_path
        self.requested_width = width
        self.color_mode = color_mode
        self.renderer = get_renderer(color_mode)
        self.enable_audio = enable_audio
        self.show_hud = show_hud
        self.user_target_fps = target_fps

        self.running = False
        self.paused = False
        self.muted = False
        self.restart_requested = False
        self.frame_queue = Queue(maxsize=QUEUE_SIZE)

        # Probe video characteristics
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {self.video_path}")
        self.video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.total_frames / self.native_fps if self.native_fps > 0 else 0
        cap.release()

        # Compute display resolution
        self.render_w, self.render_h = calculate_dimensions(self.requested_width, self.video_w, self.video_h)

        # Playback FPS
        self.fps = float(target_fps) if target_fps else self.native_fps

        # Audio handling
        self.has_audio = False
        self.audio_path = audio_path
        if self.enable_audio:
            if self.audio_path and os.path.exists(self.audio_path):
                self.has_audio = True
            else:
                extracted = extract_audio(self.video_path)
                if extracted and os.path.exists(extracted):
                    self.audio_path = extracted
                    self.has_audio = True

    def frame_reader(self):
        """Worker thread decoding and converting frames to ASCII in the background."""
        cap = cv2.VideoCapture(self.video_path)
        step = self.native_fps / self.fps if self.fps > 0 else 1.0
        target_frame_count = 0
        src_frame_idx = 0

        while self.running:
            if self.restart_requested:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                with self.frame_queue.mutex:
                    self.frame_queue.queue.clear()
                target_frame_count = 0
                src_frame_idx = 0
                self.restart_requested = False
                continue

            if self.frame_queue.full():
                time.sleep(0.002)
                continue

            # Frame downsampling stride
            next_src_frame = int(target_frame_count * step)
            if src_frame_idx < next_src_frame:
                if not cap.grab():
                    break
                src_frame_idx += 1
                continue

            ret, frame = cap.read()
            if not ret:
                break
            src_frame_idx += 1
            target_frame_count += 1

            resized = cv2.resize(frame, (self.render_w, self.render_h), interpolation=cv2.INTER_NEAREST)
            ascii_bytes = self.renderer.render(resized)
            self.frame_queue.put(ascii_bytes)

        cap.release()
        self.running = False

    def play(self):
        """Main playback loop with audio sync, HUD, and keyboard controls."""
        if self.has_audio and self.audio_path and os.path.exists(self.audio_path):
            try:
                pygame.mixer.init()
                pygame.mixer.music.load(self.audio_path)
            except Exception:
                self.has_audio = False

        self.running = True
        reader_thread = threading.Thread(target=self.frame_reader, daemon=True)
        reader_thread.start()

        # Buffer initial frames
        while self.frame_queue.qsize() < min(QUEUE_SIZE, 10) and self.running:
            time.sleep(0.005)

        # Clear screen and hide cursor
        sys.stdout.buffer.write(ANSI_CLEAR + ANSI_HOME + ANSI_HIDE_CURSOR)
        sys.stdout.buffer.flush()

        if self.has_audio:
            pygame.mixer.music.play()
        start_time = time.perf_counter()
        paused_duration = 0.0

        with KeyboardHandler() as kb:
            try:
                current_frame_idx = 0
                last_frame_bytes = b""
                fps_clock = time.perf_counter()
                fps_count = 0
                displayed_fps = self.fps

                while self.running or not self.frame_queue.empty():
                    # Check keyboard events
                    key = kb.get_char()
                    if key:
                        if key in ("q", "Q", "\x1b"):  # q, Q or Escape
                            self.running = False
                            break
                        elif key == " ":  # Space: Pause/Resume
                            self.paused = not self.paused
                            if self.paused:
                                pause_start = time.perf_counter()
                                if self.has_audio:
                                    pygame.mixer.music.pause()
                            else:
                                paused_duration += time.perf_counter() - pause_start
                                if self.has_audio:
                                    pygame.mixer.music.unpause()
                        elif key in ("r", "R"):  # Restart
                            self.restart_requested = True
                            time.sleep(0.02)
                            start_time = time.perf_counter()
                            paused_duration = 0.0
                            current_frame_idx = 0
                            if self.has_audio:
                                pygame.mixer.music.play()
                        elif key in ("m", "M"):  # Mute
                            self.muted = not self.muted
                            if self.has_audio:
                                pygame.mixer.music.set_volume(0.0 if self.muted else 1.0)
                        elif key in ("h", "H"):  # Toggle HUD
                            self.show_hud = not self.show_hud

                    # Handle pause state
                    if self.paused:
                        pause_banner = (
                            ANSI_HOME
                            + last_frame_bytes
                            + b"\n\033[1;41;37m [PAUSED] Press SPACE to resume | [R] Restart | [Q] Quit \033[0m\033[K"
                        )
                        sys.stdout.buffer.write(pause_banner)
                        sys.stdout.buffer.flush()
                        time.sleep(0.02)
                        continue

                    # Synchronization clock
                    if self.has_audio and pygame.mixer.music.get_busy():
                        audio_pos = pygame.mixer.music.get_pos() / 1000.0
                        if audio_pos >= 0:
                            playback_time = audio_pos
                        else:
                            playback_time = time.perf_counter() - start_time - paused_duration
                    else:
                        playback_time = time.perf_counter() - start_time - paused_duration

                    target_frame_idx = int(playback_time * self.fps)

                    # Lag compensation: drop late frames
                    if current_frame_idx < target_frame_idx:
                        frames_to_skip = target_frame_idx - current_frame_idx
                        for _ in range(frames_to_skip):
                            try:
                                _ = self.frame_queue.get_nowait()
                                current_frame_idx += 1
                            except Empty:
                                break
                    elif current_frame_idx > target_frame_idx:
                        time.sleep(0.001)
                        continue

                    # Render next frame
                    try:
                        ascii_art = self.frame_queue.get_nowait()
                        current_frame_idx += 1
                        last_frame_bytes = ascii_art
                        fps_count += 1

                        # Periodic FPS counter calculation
                        now = time.perf_counter()
                        if now - fps_clock >= 0.5:
                            displayed_fps = fps_count / (now - fps_clock)
                            fps_count = 0
                            fps_clock = now

                        # Optional HUD overlay
                        hud_str = b""
                        if self.show_hud:
                            cur_time_s = min(self.duration, current_frame_idx / self.fps if self.fps > 0 else 0)
                            pct = min(1.0, cur_time_s / self.duration) if self.duration > 0 else 0.0
                            bar_len = 16
                            filled = int(pct * bar_len)
                            bar = "━" * filled + "╸" + " " * (bar_len - filled)
                            hud_text = (
                                f"\n\033[1;30;47m {format_duration(cur_time_s)}/{format_duration(self.duration)} "
                                f"[{bar}] {displayed_fps:.1f} FPS | {self.render_w}x{self.render_h} "
                                f"| {self.color_mode.upper()} "
                                f"| [SPACE] Pause [R] Restart [M] Mute [Q] Quit \033[0m\033[K"
                            )
                            hud_str = hud_text.encode("utf-8")

                        sys.stdout.buffer.write(ANSI_HOME + ascii_art + hud_str)
                        sys.stdout.buffer.flush()
                    except Empty:
                        time.sleep(0.001)

            except KeyboardInterrupt:
                pass
            finally:
                self.running = False
                reader_thread.join(timeout=1.0)
                sys.stdout.buffer.write(ANSI_SHOW_CURSOR + ANSI_RESET + b"\n")
                sys.stdout.buffer.flush()
                if self.has_audio:
                    try:
                        pygame.mixer.quit()
                    except Exception:
                        pass


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="🎬 CLI Video Player v3.0 - High-Performance Multi-Threaded Terminal ASCII Video Player",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "video",
        nargs="?",
        default=None,
        help="Path to video file (if omitted, interactive selector is launched)"
    )
    parser.add_argument(
        "-a", "--audio",
        default=None,
        help="Path to audio file (optional; automatically extracted via ffmpeg if omitted)"
    )
    parser.add_argument(
        "-w", "--width",
        default=None,
        help="Terminal width resolution (e.g. 'auto', 80, 100, 120, 160, 200, 240)"
    )
    parser.add_argument(
        "-f", "--fps",
        type=float,
        default=None,
        help="Playback framerate in FPS (e.g. 15, 24, 30, 60 or native)"
    )
    parser.add_argument(
        "-c", "--color",
        choices=["ansi16", "256", "ansi8", "gray", "truecolor"],
        default=None,
        help="Color rendering mode:\n"
             "  ansi16    : 16 ANSI Colors (Recommended, ultra-fast)\n"
             "  256       : 256 Colors (Extended xterm color cube)\n"
             "  ansi8     : 8 Classic ANSI Colors (Retro)\n"
             "  gray      : Grayscale monochrome ASCII\n"
             "  truecolor : 24-bit TrueColor RGB"
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable audio playback (silent mode)"
    )
    parser.add_argument(
        "--no-hud",
        action="store_true",
        help="Hide bottom HUD status line during playback"
    )

    args = parser.parse_args()

    # If no video passed, launch interactive wizard
    video_path = args.video
    if not video_path:
        video_path = interactive_select_video()

    if not os.path.exists(video_path):
        print(f"\033[31mError: Video file not found: '{video_path}'\033[0m")
        sys.exit(1)

    # Probe video to help with resolution and framerate choices
    cap = cv2.VideoCapture(video_path)
    video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    # Resolution selection
    width_choice = args.width
    if width_choice is None and args.video is None:
        width_choice = interactive_select_resolution(video_w, video_h)
    elif width_choice is None:
        width_choice = 120

    # Framerate selection
    fps_choice = args.fps
    if fps_choice is None and args.video is None:
        fps_choice = interactive_select_framerate(native_fps)
    elif fps_choice is None:
        fps_choice = native_fps

    # Color mode selection
    color_choice = args.color
    if color_choice is None and args.video is None:
        color_choice = interactive_select_color_mode()
    elif color_choice is None:
        color_choice = "ansi16"

    # Ready to play
    player = VideoPlayer(
        video_path=video_path,
        audio_path=args.audio,
        width=width_choice,
        target_fps=fps_choice,
        color_mode=color_choice,
        enable_audio=not args.no_audio,
        show_hud=not args.no_hud,
    )

    player.play()


if __name__ == "__main__":
    main()
