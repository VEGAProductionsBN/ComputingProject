import json
import os
import tkinter as tk
from tkinter import filedialog, scrolledtext
import tkinter.ttk as ttk
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from moviepy.video.io.VideoFileClip import VideoFileClip
from faster_whisper import WhisperModel
import tempfile

# Suppress Hugging Face symlink warnings on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# -----------------------------
# Load Whisper model on CPU
model = WhisperModel("tiny", device="cpu")  # CPU only to avoid CUDA errors

# Tkinter UI
root = tk.Tk()
root.title("Video Metadata + Timestamped Transcript → JSONL")

frame = tk.Frame(root)
frame.pack(pady=10)

text_box = scrolledtext.ScrolledText(root, width=100, height=30)
text_box.pack(padx=10, pady=10)

# Progress bar for transcription
progress_bar = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate")
progress_bar.pack(pady=5)

# -----------------------------
# Functions
# -----------------------------
def extract_jsonl(video_path):
    parser = createParser(video_path)
    metadata = extractMetadata(parser)
    jsonl_lines = []

    if metadata:
        for line in metadata.exportPlaintext():
            if ":" in line:
                key, value = line.split(":", 1)
                record = {"field": key.strip(), "value": value.strip()}
                jsonl_lines.append(json.dumps(record))

    return jsonl_lines


def transcribe_video(video_path):
    # Extract audio to temporary WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
        video_clip = VideoFileClip(video_path)
        video_clip.audio.write_audiofile(tmp_audio.name, logger=None)
        video_clip.close()

        # Transcribe with faster-whisper (generator)
        segment_generator, info = model.transcribe(tmp_audio.name)

        jsonl_segments = []
        progress_bar["value"] = 0
        root.update_idletasks()

        # Iterate segments
        for i, segment in enumerate(segment_generator, start=1):
            record = {
                "field": "Transcript Segment",
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            }
            jsonl_segments.append(json.dumps(record))

            # Update progress bar incrementally
            progress_bar["value"] += 1
            root.update_idletasks()

        progress_bar["value"] = 0  # Reset after done
        return jsonl_segments


def open_file():
    file_path = filedialog.askopenfilename(
        filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm")]
    )
    if not file_path:
        return

    # Extract metadata
    text_box.delete("1.0", tk.END)
    jsonl_data = extract_jsonl(file_path)

    # Transcribe video
    text_box.insert(tk.END, "Transcribing video, please wait...\n")
    root.update()
    jsonl_segments = transcribe_video(file_path)

    # Add timestamped segments to JSONL
    jsonl_data.extend(jsonl_segments)

    # Display all JSONL
    text_box.delete("1.0", tk.END)
    text_box.insert(tk.END, "\n".join(jsonl_data))


def save_jsonl():
    data = text_box.get("1.0", tk.END)
    file_path = filedialog.asksaveasfilename(
        defaultextension=".jsonl",
        filetypes=[("JSONL Files", "*.jsonl")]
    )
    if file_path:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(data)


# -----------------------------
# Buttons
# -----------------------------
open_button = tk.Button(frame, text="Open Video", command=open_file)
open_button.pack(side=tk.LEFT, padx=5)

save_button = tk.Button(frame, text="Save JSONL", command=save_jsonl)
save_button.pack(side=tk.LEFT, padx=5)

# -----------------------------
# Run Tkinter UI
# -----------------------------
root.mainloop()