import cv2
import numpy as np
import pygame
from pygame import mixer
import time
import os
import sys
import threading
from queue import Queue

VIDEO_PATH = "video.mp4"
AUDIO_PATH = "audio.mp3"
WIDTH = 120
QUEUE_SIZE = 64

ANSI_RESET = b"\033[0m"
ANSI_HOME = b"\033[H"
ANSI_HIDE_CURSOR = b"\033[?25l"
ANSI_SHOW_CURSOR = b"\033[?25h"

ANSI_COLORS_BYTES = np.array([
    b"\033[30m", b"\033[34m", b"\033[32m", b"\033[36m",
    b"\033[31m", b"\033[35m", b"\033[33m", b"\033[37m"
])

ASCII_CHARS = np.array(list(" ░▒▓█"))
COLORS_REF = np.array([
    (0, 0, 0), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)
], dtype=np.int16)

class VideoPlayer:
    def __init__(self, video_path, audio_path, width):
        self.video_path = video_path
        self.audio_path = audio_path
        self.width = width
        self.running = False
        self.frame_queue = Queue(maxsize=QUEUE_SIZE)
        
    def get_video_info(self):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"Impossible d'ouvrir {self.video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return fps, total_frames

    def frame_reader(self):
        cap = cv2.VideoCapture(self.video_path)
        while self.running:
            if self.frame_queue.full():
                time.sleep(0.01)
                continue
            
            ret, frame = cap.read()
            if not ret:
                self.running = False
                break
            
            h, w = frame.shape[:2]
            aspect_ratio = h / w
            new_height = int(self.width * aspect_ratio * 0.55)
            resized = cv2.resize(frame, (self.width, new_height), interpolation=cv2.INTER_NEAREST)
            
            self.frame_queue.put(resized)
        cap.release()
        
def process_frame_vectorized(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ascii_indices = (gray * (len(ASCII_CHARS) - 1) // 255).astype(np.uint8)
        diff = frame[:, :, np.newaxis, :] - COLORS_REF[np.newaxis, np.newaxis, :, :]
        dists_sq = np.sum(diff**2, axis=3)
        color_indices = np.argmin(dists_sq, axis=2)
        mapped_chars = ASCII_CHARS[ascii_indices]
        mapped_colors = ANSI_COLORS_BYTES[color_indices]
        char_bytes = np.char.encode(mapped_chars, 'utf-8')
        pixels = np.char.add(mapped_colors, char_bytes)
        rows = [b"".join(row) for row in pixels]
        return b"\n".join(rows) + ANSI_RESET
    
    def play(self):
        fps, total_frames = self.get_video_info()
        
        pygame.mixer.init()
        try:
            pygame.mixer.music.load(self.audio_path)
        except Exception as e:
            return

        self.running = True
        reader_thread = threading.Thread(target=self.frame_reader)
        reader_thread.daemon = True
        reader_thread.start()

        while self.frame_queue.qsize() < min(QUEUE_SIZE, 10) and self.running:
            time.sleep(0.01)

        os.system('cls' if os.name == 'nt' else 'clear')
        sys.stdout.buffer.write(ANSI_HIDE_CURSOR)
        
        pygame.mixer.music.play()
        start_time = time.time()
        
        try:
            current_frame_idx = 0
            
            while self.running and (pygame.mixer.music.get_busy() or not self.frame_queue.empty()):
                audio_time = pygame.mixer.music.get_pos() / 1000.0
                
                if audio_time < 0: 
                    audio_time = time.time() - start_time

                target_frame_idx = int(audio_time * fps)
                
                if current_frame_idx < target_frame_idx:
                    frames_to_skip = target_frame_idx - current_frame_idx
                    for _ in range(frames_to_skip):
                        if not self.frame_queue.empty():
                            _ = self.frame_queue.get()
                            current_frame_idx += 1
                
                elif current_frame_idx > target_frame_idx:
                    time.sleep(0.001)
                    continue

                if not self.frame_queue.empty():
                    frame = self.frame_queue.get()
                    current_frame_idx += 1
                    
                    ascii_art = self.process_frame_vectorized(frame)
                    
                    sys.stdout.buffer.write(ANSI_HOME + ascii_art)
                    sys.stdout.buffer.flush()
                else:
                    time.sleep(0.001)

        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            reader_thread.join()
            sys.stdout.buffer.write(ANSI_SHOW_CURSOR + ANSI_RESET)
            pygame.mixer.quit()

if __name__ == "__main__":
    if not os.path.exists("video.mp4") or not os.path.exists("audio.mp3"):
        print("Erreur: Place 'video.mp4' et 'audio.mp3' dans le dossier.")
    else:
        player = VideoPlayer("video.mp4", "audio.mp3", width=120)
        player.play()


