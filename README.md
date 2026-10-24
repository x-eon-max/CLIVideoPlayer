# 🎬 High-Performance CLI Video Player (v3.0)

> A blazing fast, multi-threaded terminal video player written in Python. Converts video frames to colored ASCII art in real-time with automatic audio extraction, high-precision synchronization, interactive menus, and playback controls.

---

## ✨ Features

* **⚡ Ultra-Fast Vectorized Engine (>1500 FPS):** Employs precomputed **3D Lookup Tables (LUT)** and combo-token indexing to map pixels to ANSI colors and ASCII glyphs with zero python-level pixel loops.
* **📂 Interactive Video Selector:** Automatically scans current and user directories for video files (`.mp4`, `.mkv`, `.webm`, `.avi`, `.mov`, etc.), displaying resolution, framerate, duration, and file size. Supports custom paths and drag-and-drop.
* **📐 Standard Resolution Presets:** Choose from known standard resolutions or auto-fit dynamically:
  * **Auto** (Fits current terminal window preserving aspect ratio without vertical scrolling)
  * **Compact** (80 cols — Classic terminal standard)
  * **Medium** (100 cols)
  * **Standard** (120 cols — Default)
  * **HD** (160 cols — High detail)
  * **Full HD** (200 cols — Ultra detail)
  * **Ultra HD** (240 cols — Extreme widescreen)
  * **Custom** (Enter any arbitrary width)
* **⏱️ Framerate Selector & Downsampling:** Play videos at **Native FPS**, **15 FPS** (low CPU / SSH), **24 FPS** (cinematic), **30 FPS**, **60 FPS**, or **Custom FPS** with hardware-accelerated demuxer stride skipping (`cap.grab()`).
* **🎨 5 Color Rendering Modes:**
  * `ansi16` : 16 ANSI Colors (8 Standard + 8 Bright) via 3D LUT — vibrant and ultra-fast (~1500 FPS) *(Recommended)*
  * `256` : 256 Colors using extended xterm color cube (~1700 FPS)
  * `ansi8` : 8 Classic Retro ANSI Colors via bitwise quantization (~2000 FPS)
  * `gray` : Monochrome ASCII Art with brightness ramp (~4000 FPS)
  * `truecolor` : Full 24-bit RGB TrueColor
* **🎵 Automatic Audio Extraction & Lip-Sync:** Automatically extracts the audio track using `ffmpeg` on-the-fly and synchronizes playback against the Pygame mixer clock. Plays smoothly in silent mode if no audio track exists.
* **🎮 Live Playback Controls:**
  * `[SPACE]` : Pause / Resume (with instant audio pause/unpause)
  * `[R]` : Restart video from beginning
  * `[M]` : Mute / Unmute audio
  * `[H]` : Toggle real-time HUD status line
  * `[Q]` / `[ESC]` : Clean quit and terminal restoration
* **🧵 Parallel Multi-threaded Pipeline:** Background worker threads decode, resize, and convert frames to ASCII bytes ahead of time, ensuring the display loop has zero latency or jitter.
* **🐛 Bug Fixes & Stability:**
  * Fixed critical syntax/indentation error from v2.0.1.
  * Fixed signed 16-bit integer overflow in color distance computation (`diff**2` wrapping negative).
  * Fixed channel mismatch between OpenCV BGR and ANSI color mapping.
  * Added automated temp file cleanup (`atexit`) and terminal state restoration.

---

## 🛠️ Prerequisites & Installation

### 1. Python Dependencies

```bash
git clone https://github.com/x-eon-max/CLIVideoPlayer.git
cd CLIVideoPlayer
pip install -r requirements.txt
```

*(Dependencies: `opencv-python`, `numpy`, `pygame`)*

### 2. FFmpeg (Recommended)

To enable automatic audio extraction directly from video containers:

* **Arch Linux / Manjaro:** `sudo pacman -S ffmpeg`
* **Debian / Ubuntu:** `sudo apt install ffmpeg`
* **macOS:** `brew install ffmpeg`
* **Windows:** `winget install Gyan.FFmpeg` or download from [ffmpeg.org](https://ffmpeg.org/)

*(If FFmpeg is not installed, the player will still play videos smoothly in silent mode or with manually provided audio files).*

---

## 🚀 Usage

### 1. Interactive Mode (Wizard)

Simply launch the player without arguments:

```bash
python Player.py
```

The interactive menu will guide you step-by-step:
1. **Select Video File** (detected videos listed with size, fps, duration)
2. **Select Display Resolution** (presets + auto-detect)
3. **Select Framerate** (native, 15, 24, 30, 60, or custom)
4. **Select Color Palette** (16 ANSI, 256, 8 ANSI, Grayscale, TrueColor)

### 2. Command Line Arguments (Direct Mode)

Play any video directly with custom settings:

```bash
# Play video with default settings (120 cols, 16 ANSI colors, auto audio)
python Player.py my_video.mp4

# Auto-fit to terminal window at 30 FPS in 256-color mode
python Player.py my_video.mp4 -w auto -f 30 -c 256

# High Definition 160 cols with custom audio track
python Player.py my_video.mp4 -w 160 -a audio.mp3

# Low-resource mode (80 cols, 15 FPS, monochrome grayscale)
python Player.py my_video.mp4 -w 80 -f 15 -c gray --no-audio
```

### CLI Options

| Argument | Shorthand | Description |
| :--- | :--- | :--- |
| `video` | — | Path to video file (launches interactive selector if omitted) |
| `--width` | `-w` | Display resolution (`auto`, `80`, `100`, `120`, `160`, `200`, `240`, or custom integer) |
| `--fps` | `-f` | Playback framerate in FPS (`15`, `24`, `30`, `60`, or native) |
| `--color` | `-c` | Color palette (`ansi16`, `256`, `ansi8`, `gray`, `truecolor`) |
| `--audio` | `-a` | Path to separate audio file (auto-extracted if omitted) |
| `--no-audio` | — | Disable audio playback entirely |
| `--no-hud` | — | Hide the bottom status / progress bar |

---

## 🎮 Keyboard Controls

During playback, use the following keys in your terminal:

| Key | Action |
| :---: | :--- |
| **`[SPACE]`** | **Pause / Resume** playback |
| **`[R]`** | **Restart** video from the beginning |
| **`[M]`** | **Mute / Unmute** audio |
| **`[H]`** | **Toggle HUD** status overlay |
| **`[Q]`** / **`[ESC]`** | **Quit** and restore terminal cursor & colors |

---

## 🧠 Technical Architecture & Optimizations

### 1. Vectorized Combo LUT Acceleration
Previous versions iterated or broadcasted high-dimensional matrices across Euclidean color distances, allocating massive temporary arrays on every frame (~17 ms per frame).

In **v3.0**:
- **16-Color ANSI Engine:** Uses a precalculated 3D lookup table $(32 \times 32 \times 32)$ mapping $(B \gg 3, G \gg 3, R \gg 3)$ to palette indices in $\approx 0.05\text{ ms}$.
- **Combo Token Table:** Pre-generates combined ANSI color escape bytes and UTF-8 characters into a single flat array. Pixel bytes are assembled directly in memory without per-character allocations, achieving **$\approx 0.6\text{ ms}$ total frame rendering time ($>1,500\text{ FPS}$)**.

### 2. Multi-threaded Background Queue
Video decoding and ASCII rendering run in a dedicated background worker thread (`Queue(maxsize=64)`). The main display thread only handles timer pacing and non-blocking terminal I/O, guaranteeing butter-smooth playback without UI stutter.

### 3. Dynamic Terminal Fitting
In `auto` mode, the player queries `shutil.get_terminal_size()`, computes the font aspect-ratio correction factor ($0.55$), and automatically clamps lines to fit within the visible terminal viewport, preventing flickering and unwanted scrollbar jitter.

---

## 💡 Tips for Best Experience

* **Terminal Emulator:** For maximum framerate and lowest latency, use a GPU-accelerated terminal like **Alacritty**, **Kitty**, **Windows Terminal**, **WezTerm**, or **iTerm2**.
* **Font Size:** Zoom out slightly (`Ctrl` + `-` or `Ctrl` + Scroll) to accommodate larger resolutions like 160 or 200 columns.

---

## 📝 License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for details.
