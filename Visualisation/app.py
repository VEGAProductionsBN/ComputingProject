import os
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from moviepy.video.io.VideoFileClip import VideoFileClip
from faster_whisper import WhisperModel
import tempfile

app = Flask(__name__)
app.secret_key = "supersecretkey"  # for flash messages

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel("tiny", device="cpu")
    return _whisper_model


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


def generate_jsonl_from_video(video_path):
    records = []
    parser = createParser(video_path)
    if parser:
        meta = extractMetadata(parser)
        if meta:
            for line in meta.exportPlaintext():
                if ":" in line:
                    key, value = line.split(":", 1)
                    records.append({"field": key.strip(), "value": value.strip()})

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_path = tmp_audio.name
        clip = VideoFileClip(video_path)
        clip.audio.write_audiofile(tmp_path, logger=None)
        clip.close()
        model = get_whisper_model()
        segment_generator, _ = model.transcribe(tmp_path)
        for segment in segment_generator:
            records.append({
                "field": "Transcript Segment",
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
            })
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return records


def extract_transcript_segments(records):
    segments = []
    if not isinstance(records, list):
        return segments

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("field") != "Transcript Segment":
            continue

        try:
            start = float(record.get("start"))
            end = float(record.get("end", start))
        except (TypeError, ValueError):
            continue

        text = str(record.get("text", "")).strip()
        if not text:
            continue

        segments.append({"start": start, "end": end, "text": text})

    return segments


def shorten_topic(text, max_words=12):
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def match_transcript_segment(second, segments, max_distance=8.0):
    if second is None or not segments:
        return None

    for seg in segments:
        if seg["start"] <= second <= seg["end"]:
            return seg

    nearest = min(
        segments,
        key=lambda seg: min(abs(second - seg["start"]), abs(second - seg["end"])),
    )
    distance = min(abs(second - nearest["start"]), abs(second - nearest["end"]))
    return nearest if distance <= max_distance else None


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
        if "video_file" not in request.files:
            flash("Please upload a video file.")
            return redirect(request.url)

        video_file = request.files["video_file"]
        json_file = request.files.get("json_file")
        use_json_file = json_file is not None and json_file.filename != ""

        if video_file.filename == "":
            flash("No video file selected.")
            return redirect(request.url)

        if use_json_file and not allowed_file(json_file.filename, ALLOWED_JSON_EXTENSIONS):
            flash("Invalid JSON file extension")
            return redirect(request.url)

        if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            flash("Invalid video file extension")
            return redirect(request.url)

        video_filename = secure_filename(video_file.filename)
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

        video_file.save(video_path)

        # Always generate fresh video metadata + transcript for raw JSONL display.
        try:
            generated_metadata = generate_jsonl_from_video(str(video_path))
            raw_jsonl_lines = [json.dumps(record) for record in generated_metadata]
            transcript_segments = extract_transcript_segments(generated_metadata)
        except Exception as e:
            flash(f"Failed to generate metadata from video: {e}")
            return redirect(request.url)

        if use_json_file:
            json_filename = secure_filename(json_file.filename)
            json_path = UPLOAD_FOLDER / json_filename
            json_file.save(json_path)
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
        else:
            json_filename = "(auto-generated from video)"
            metadata = generated_metadata

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
                elif "start" in event:
                    tsecs = float(event["start"])
                    time_text = f"{tsecs:.2f}s"

                # Skip pure metadata records with no time information
                if tsecs is None and not ts:
                    continue

                readable_type = event.get("type") or event.get("field", "unknown")
                description = f"{readable_type.replace('_', ' ').title()}"
                if event.get("state"):
                    description += f" - state {event.get('state')}"
                if event.get("text"):
                    description += f": {event['text']}"

                details = []
                if isinstance(event, dict):
                    for k, v in event.items():
                        if k not in ("timestamp", "type", "text"):
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

            # Link each event to nearby spoken transcript context.
            for ev in event_list:
                matched_segment = match_transcript_segment(ev.get("x_val"), transcript_segments)
                if not matched_segment:
                    continue

                inferred_topic = shorten_topic(matched_segment["text"])
                ev["inferred_topic"] = inferred_topic
                ev["inferred_transcript"] = matched_segment["text"]
                ev["inferred_window"] = f"{matched_segment['start']:.2f}s - {matched_segment['end']:.2f}s"
                ev["description"] = f"{ev['description']} | Context: {inferred_topic}"

        return render_template(
            "index.html",
            metadata=metadata,
            raw_jsonl_lines=raw_jsonl_lines,
            stats=stats,
            events=event_list,
            video_url=url_for("static", filename=f"uploads/{video_filename}"),
            video_type=video_type,
            json_filename=json_filename,
        )

    return render_template("index.html", events=[], stats=[], metadata=None, raw_jsonl_lines=[])


if __name__ == "__main__":
    # Disable watchdog reloader on Windows to avoid repeated false reload events.
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)
