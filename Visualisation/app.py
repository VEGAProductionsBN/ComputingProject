import os
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "supersecretkey"  # for flash messages

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"

# Clear any existing files on first startup
if UPLOAD_FOLDER.exists():
    for file_path in UPLOAD_FOLDER.iterdir():
        if file_path.is_file():
            try:
                file_path.unlink()
            except Exception:
                pass
else:
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_JSON_EXTENSIONS = {"json", "jsonl"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "ogg", "mkv"}


def allowed_file(filename, allowed_exts):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_exts


def extract_stats(metadata):
    stats = []

    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if isinstance(value, (int, float)):
                stats.append({"key": key, "value": value, "type": "numeric"})
            else:
                stats.append({"key": key, "value": value, "type": type(value).__name__})

    elif isinstance(metadata, list):
        stats.append({"key": "items", "value": len(metadata), "type": "numeric"})

        if metadata and all(isinstance(item, dict) for item in metadata):
            type_counts = {}
            for entry in metadata:
                t = entry.get("type", "unknown")
                type_counts[t] = type_counts.get(t, 0) + 1

            for t, c in type_counts.items():
                stats.append({"key": f"event_{t}_count", "value": c, "type": "numeric"})

            # aggregate simple numeric fields in events
            numeric_agg = {}
            for entry in metadata:
                for k, v in entry.items():
                    if isinstance(v, (int, float)):
                        numeric_agg.setdefault(k, []).append(v)

            for k, values in numeric_agg.items():
                if k != "timestamp":
                    stats.append({"key": f"average_{k}", "value": sum(values) / len(values), "type": "numeric"})

    else:
        stats.append({"key": "value", "value": metadata, "type": type(metadata).__name__})

    return stats


@app.route("/", methods=["GET", "POST"])
def upload_page():
    if request.method == "POST":
        if "json_file" not in request.files or "video_file" not in request.files:
            flash("Please upload both a JSON metadata file and a video file.")
            return redirect(request.url)

        json_file = request.files["json_file"]
        video_file = request.files["video_file"]

        if json_file.filename == "" or video_file.filename == "":
            flash("No selected file")
            return redirect(request.url)

        if not allowed_file(json_file.filename, ALLOWED_JSON_EXTENSIONS):
            flash("Invalid JSON file extension")
            return redirect(request.url)

        if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            flash("Invalid video file extension")
            return redirect(request.url)

        json_filename = secure_filename(json_file.filename)
        video_filename = secure_filename(video_file.filename)

        json_path = UPLOAD_FOLDER / json_filename
        video_path = UPLOAD_FOLDER / video_filename

        video_ext = video_filename.rsplit('.', 1)[1].lower() if '.' in video_filename else ''
        video_type_map = {
            'mp4': 'video/mp4',
            'webm': 'video/webm',
            'ogg': 'video/ogg',
            'mov': 'video/quicktime',
            'mkv': 'video/x-matroska'
        }
        video_type = video_type_map.get(video_ext, 'video/mp4')

        json_file.save(json_path)
        video_file.save(video_path)

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                if json_filename.lower().endswith(".jsonl"):
                    lines = [line.strip() for line in f if line.strip()]
                    metadata = [json.loads(line) for line in lines]
                else:
                    metadata = json.load(f)
        except Exception as e:
            flash(f"Failed to parse JSON/JSONL: {e}")
            return redirect(request.url)

        stats = extract_stats(metadata)

        event_list = []

        if isinstance(metadata, list):
            for idx, event in enumerate(metadata):
                ts = event.get("timestamp")
                tsecs = None
                time_text = "n/a"
                if ts:
                    try:
                        # RFC3339-compatible datetime parse
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        tsecs = dt.timestamp()
                        time_text = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        tsecs = None

                readable_type = event.get("type", "unknown")
                description = f"{readable_type.replace('_', ' ').title()}"
                if event.get("state"):
                    description += f" - state {event.get('state')}"

                details = []
                if isinstance(event, dict):
                    for k, v in event.items():
                        if k not in ("timestamp", "type"):
                            details.append(f"{k}: {v}")

                event_list.append({
                    "index": idx,
                    "timestamp": ts,
                    "time_text": time_text,
                    "tsecs": tsecs,
                    "type": readable_type,
                    "description": description,
                    "details": details,
                    "payload": event,
                })

            base = min((ev["tsecs"] for ev in event_list if ev["tsecs"] is not None), default=None)
            for ev in event_list:
                x_val = ev["tsecs"] - base if (base is not None and ev["tsecs"] is not None) else ev["index"]
                ev["x_val"] = x_val

        return render_template(
            "index.html",
            metadata=metadata,
            stats=stats,
            events=event_list,
            video_url=url_for("static", filename=f"uploads/{video_filename}"),
            video_type=video_type,
            json_filename=json_filename,
        )

    return render_template("index.html", events=[], stats=[], metadata=None)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
