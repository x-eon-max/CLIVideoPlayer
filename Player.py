import cv2
import numpy as np
import os
import sys
import time
import threading
from queue import Queue

# Suppress pygame welcome message
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame

VIDEO_PATH = "video.mp4"
AUDIO_PATH = "audio.mp3"
DEFAULT_WIDTH = 120
QUEUE_SIZE = 64

ANSI_RESET = b"\033[0m"
ANSI_HOME = b"\033[H"
ANSI_HIDE_CURSOR = b"\033[?25l"
ANSI_SHOW_CURSOR = b"\033[?25h"

ASCII_CHARS = np.array(list(" ░▒▓█"))
ASCII_CHARS_BYTES = [c.encode("utf-8") for c in ASCII_CHARS]


class ANSI16Renderer:
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


class ANSI8Renderer:
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


class Color256Renderer:
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


class GrayscaleRenderer:
    """Monochrome ASCII renderer with minimal terminal bandwidth."""
    def __init__(self):
        self.combo = np.array(ASCII_CHARS_BYTES, dtype=object)

    def render(self, frame: np.ndarray) -> bytes:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        a_idx = (gray.astype(np.uint16) * 4 // 255).astype(np.uint8)
        mapped = self.combo[a_idx]
        return b"\033[97m" + b"\n".join([b"".join(r) for r in mapped]) + ANSI_RESET


class TrueColorRenderer:
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


def get_renderer(mode: str):
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


class VideoPlayer:
    def __init__(self, video_path: str, audio_path: str = None, width: int = DEFAULT_WIDTH, color_mode: str = "ansi16"):
        self.video_path = video_path
        self.audio_path = audio_path
        self.width = width
        self.color_mode = color_mode
        self.renderer = get_renderer(color_mode)
        self.running = False
        self.frame_queue = Queue(maxsize=QUEUE_SIZE)
        
    def get_video_info(self):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"Impossible d'ouvrir {self.video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return fps, total_frames

    def frame_reader(self):
        cap = cv2.VideoCapture(self.video_path)
        while self.running:
            if self.frame_queue.full():
                time.sleep(0.002)
                continue
            
            ret, frame = cap.read()
            if not ret:
                self.running = False
                break
            
            h, w = frame.shape[:2]
            aspect_ratio = h / w
            new_height = max(1, int(self.width * aspect_ratio * 0.55))
            resized = cv2.resize(frame, (self.width, new_height), interpolation=cv2.INTER_NEAREST)
            ascii_bytes = self.renderer.render(resized)
            self.frame_queue.put(ascii_bytes)
        cap.release()
    
    def play(self):
        fps, total_frames = self.get_video_info()
        has_audio = False
        
        if self.audio_path and os.path.exists(self.audio_path):
            try:
                pygame.mixer.init()
                pygame.mixer.music.load(self.audio_path)
                has_audio = True
            except Exception:
                has_audio = False

        self.running = True
        reader_thread = threading.Thread(target=self.frame_reader, daemon=True)
        reader_thread.start()

        # Buffer initial frames
        while self.frame_queue.qsize() < min(QUEUE_SIZE, 10) and self.running:
            time.sleep(0.005)

        os.system("cls" if os.name == "nt" else "clear")
        sys.stdout.buffer.write(ANSI_HIDE_CURSOR)
        sys.stdout.buffer.flush()
        
        if has_audio:
            pygame.mixer.music.play()
        start_time = time.perf_counter()
        
        try:
            current_frame_idx = 0
            
            while self.running and (not self.frame_queue.empty() or (has_audio and pygame.mixer.music.get_busy())):
                if has_audio and pygame.mixer.music.get_busy():
                    audio_time = pygame.mixer.music.get_pos() / 1000.0
                    if audio_time < 0:
                        audio_time = time.perf_counter() - start_time
                else:
                    audio_time = time.perf_counter() - start_time

                target_frame_idx = int(audio_time * fps)
                
                # Drop frames if lagging
                if current_frame_idx < target_frame_idx:
                    frames_to_skip = target_frame_idx - current_frame_idx
                    for _ in range(frames_to_skip):
                        if not self.frame_queue.empty():
                            _ = self.frame_queue.get_nowait()
                            current_frame_idx += 1
                elif current_frame_idx > target_frame_idx:
                    time.sleep(0.001)
                    continue

                if not self.frame_queue.empty():
                    ascii_art = self.frame_queue.get_nowait()
                    current_frame_idx += 1
                    sys.stdout.buffer.write(ANSI_HOME + ascii_art)
                    sys.stdout.buffer.flush()
                else:
                    time.sleep(0.001)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            reader_thread.join(timeout=1.0)
            sys.stdout.buffer.write(ANSI_SHOW_CURSOR + ANSI_RESET + b"\n")
            sys.stdout.buffer.flush()
            if has_audio:
                try:
                    pygame.mixer.quit()
                except Exception:
                    pass


if __name__ == "__main__":
    if not os.path.exists("video.mp4") or not os.path.exists("audio.mp3"):
        print("Erreur: Place 'video.mp4' et 'audio.mp3' dans le dossier.")
    else:
        player = VideoPlayer("video.mp4", "audio.mp3", width=120)
        player.play()
