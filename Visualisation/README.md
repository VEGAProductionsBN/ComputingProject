# Video Metadata Explorer

A simple Flask web app for uploading a JSON metadata file and a video clip, then displaying the metadata in tabular and chart form alongside the video player.

## Features
- Upload JSON metadata and video file
- Parse and show key metadata statistics
- Display a chart for numeric metadata values
- In-browser video playback
- Demonstrates simple relation: video time updates reflected in browser title

## Project structure
- `app.py` - Main Flask application
- `templates/index.html` - Single page UI
- `static/uploads/` - Uploaded files (created automatically)
- `requirements.txt` - Python dependencies

## Setup
1. Create a virtual env:

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS / Linux
```

2. Install requirements:

```bash
pip install -r requirements.txt
```

## Run locally

```bash
python app.py
```

Then open `http://localhost:5000`.

## Upload and use
1. Choose a JSON or JSONL metadata file (see samples below).
2. Choose a video clip (mp4/webm/ogg/mov).
3. Submit and view stats and video.

## Example JSON format

```json
{
  "duration": 22.5,
  "frames": 650,
  "average_brightness": 120.2,
  "scene_changes": 5,
  "camera_name": "FrontDoorCam"
}
```

## Example JSONL format

```
{"timestamp": "2026-03-17T14:58:26.008797", "type": "light_change", "brightness": 255, "color": "Color Temp: 2000K"}
{"timestamp": "2026-03-17T14:58:26.009916", "type": "flic_press", "state": "on", "attributes": {"address": "80:e4:da:79:f7:12", "friendly_name": "flic_80e4da79f712"}}
{"timestamp": "2026-03-17T14:58:43.814490", "type": "flic_press", "state": "on"}
```

## Optional improvements
- Add connection between video timestamp and time-series metadata
- Support JSONL and nested metadata via recursive parsing
- Add security checks for large uploads
