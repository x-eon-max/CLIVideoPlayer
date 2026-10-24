# 🚀 High-Performance ASCII Video Player

> A blazing fast, multi-threaded terminal video player written in Python. It converts video frames to colored ASCII art in real-time with perfect audio synchronization.

## ✨ Features

* **⚡ Zero-Loop Rendering:** Uses **NumPy vectorization** and broadcasting to map pixels to ASCII/ANSI colors. No Python loops are used for pixel processing, ensuring high FPS.
* **🧵 Multi-threaded Decoding:** Video frames are read and resized in a background thread to prevent I/O blocking.
* **🎵 Perfect Audio Sync:** Frames are synchronized to the audio timestamp (Pygame Mixer) rather than the system clock, ensuring lip-sync accuracy even if the CPU lags.
* **🚀 Raw Buffer Output:** Writes bytes directly to `stdout` buffer for maximum throughput.

## 🛠️ Prerequisites

You need **Python 3** and the following libraries:

```bash
pip install opencv-python numpy pygame

```

## 📂 Setup

1. **Clone the repository** (or download the script).
2. **Prepare your media files**:
The script requires the video and audio to be in separate files (this avoids the overhead of decoding audio from the video container in real-time).
* Place your video file as `video.mp4`.
* Place your audio file as `audio.mp3`.


> **Tip:** You can extract audio from a video using FFmpeg:


> ```bash
> ffmpeg -i input.mp4 -q:a 0 -map a audio.mp3
> mv input.mp4 video.mp4
> 
> ```
> 
> 



## 🚀 Usage

Run the script from your terminal:

```bash
python Player.py
```

*Note: For the best experience, zoom out your terminal (Ctrl + Scroll) or reduce the font size to fit the width.*

## ⚙️ Configuration

You can tweak the constants at the top of the `main.py` file:

```python
WIDTH = 120       # Width of the ASCII output (in characters)
QUEUE_SIZE = 64   # Frame buffer size

```

## 🧠 How it works (The Optimization)

Unlike standard ASCII converters that iterate over every pixel (`for x in width...`), this engine uses **NumPy** to process the entire image matrix at once:

1. **Grayscale & Resize:** OpenCV handles the heavy lifting.
2. **Vectorized Mapping:** * Calculates Euclidean distance between every pixel and the ANSI color palette in a single matrix operation.
* Maps luminance to ASCII characters using array indexing.


3. **Broadcasting:** Combines the ANSI color codes and ASCII characters into a single byte stream.

## 📝 License

Distributed under the MIT License. See `LICENSE` for more information.

---

### 💡 Tips for best performance

* Use a terminal with GPU acceleration (like **Alacritty**, **Windows Terminal**, or **iTerm2**).
* Avoid using the default CMD on old Windows versions; PowerShell or Git Bash is recommended.
