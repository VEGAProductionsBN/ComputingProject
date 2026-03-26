import os
import json
import re
import math
import time
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy import concatenate_videoclips
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
LOG_FOLDER = BASE_DIR.parent / "home_assistant_logs"

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


def get_available_logs():
    """List available JSON/JSONL files from the logs folder."""
    available = []
    if LOG_FOLDER.exists() and LOG_FOLDER.is_dir():
        for file_path in sorted(LOG_FOLDER.glob("*")):
            if file_path.is_file() and allowed_file(file_path.name, ALLOWED_JSON_EXTENSIONS):
                available.append({"name": file_path.name, "path": str(file_path)})
    return available


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


def parse_duration_to_seconds(duration_text):
    """Parse strings like '41 sec 60 ms' into total seconds."""
    if not duration_text:
        return None

    text = str(duration_text).strip().lower()
    if not text:
        return None

    total = 0.0

    hour_match = re.search(r"([\d.]+)\s*h(?:ours?)?", text)
    minute_match = re.search(r"([\d.]+)\s*min(?:utes?)?", text)
    second_match = re.search(r"([\d.]+)\s*sec(?:onds?)?", text)
    ms_match = re.search(r"([\d.]+)\s*ms", text)

    if hour_match:
        total += float(hour_match.group(1)) * 3600
    if minute_match:
        total += float(minute_match.group(1)) * 60
    if second_match:
        total += float(second_match.group(1))
    if ms_match:
        total += float(ms_match.group(1)) / 1000.0

    return total if total > 0 else None


def extract_video_duration_seconds(records):
    if not isinstance(records, list):
        return None

    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("field", "")).strip().lower() != "- duration":
            continue
        duration_seconds = parse_duration_to_seconds(record.get("value"))
        if duration_seconds is not None:
            return duration_seconds
    return None


def extract_video_creation_datetime(records):
    if not isinstance(records, list):
        return None

    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("field", "")).strip().lower() != "- creation date":
            continue

        value = str(record.get("value", "")).strip()
        if not value:
            continue

        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return None

    return None


def choose_clip_window(event_list, creation_dt, duration_seconds):
    """Derive the clip window from the creation datetime and duration.

    The creation date reported by video metadata is the time the file was
    finalised (recording ended), not when recording began.  Subtracting the
    duration gives the true recording start time.
    """
    if creation_dt is None or duration_seconds is None or duration_seconds <= 0:
        return None, None, None

    creation_epoch = creation_dt.timestamp()
    clip_start = creation_epoch - duration_seconds
    clip_end = creation_epoch
    return clip_start, clip_end, "creation_as_end"


def shorten_topic(text, max_words=12):
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def match_transcript_segment(second, segments, max_distance=2.0):
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


def tokenize_text(text):
    return re.findall(r"[a-zA-Z0-9']+", str(text).lower())


def build_transcript_idf(segments):
    """Build a lightweight transcript-specific IDF map for semantic scoring."""
    stopwords = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
        "is", "it", "this", "that", "we", "i", "im", "you", "now", "will",
        "be", "as", "are", "was", "were", "by", "at", "from", "so", "then",
    }

    total_docs = max(1, len(segments))
    doc_freq = {}
    for seg in segments:
        tokens = {t for t in tokenize_text(seg.get("text", "")) if len(t) > 2 and t not in stopwords}
        for token in tokens:
            doc_freq[token] = doc_freq.get(token, 0) + 1

    idf = {}
    for token, df in doc_freq.items():
        idf[token] = 1.0 + (total_docs / max(1, df))
    return idf


def infer_semantic_topic(tokens, intent, idf_map):
    """Infer higher-level semantic topic from transcript language patterns."""
    topic_rules = {
        "Session Initialization and Baseline Capture": {
            "start", "session", "initial", "begin", "metadata", "process", "logs"
        },
        "Interactive Device Control Sequence": {
            "press", "click", "button", "turn", "switch", "on", "off", "control"
        },
        "Lighting and Color Calibration": {
            "brightness", "light", "color", "temperature", "hs", "warm", "cool"
        },
        "Session Wrap-Up and Recording End": {
            "end", "finish", "stop", "done", "video", "recording"
        },
    }

    intent_hint = {
        "session_setup": "Session Initialization and Baseline Capture",
        "device_control": "Interactive Device Control Sequence",
        "light_adjustment": "Lighting and Color Calibration",
        "session_end": "Session Wrap-Up and Recording End",
    }.get(intent)

    scores = {}
    for topic, rule_words in topic_rules.items():
        overlap = rule_words.intersection(tokens)
        weighted = sum(idf_map.get(token, 1.0) for token in overlap)
        if topic == intent_hint:
            weighted += 2.0
        scores[topic] = weighted

    best_topic = max(scores, key=scores.get)
    if scores[best_topic] <= 0:
        ranked_tokens = sorted(tokens, key=lambda token: idf_map.get(token, 1.0), reverse=True)
        fallback_keywords = [t for t in ranked_tokens if len(t) > 2][:3]
        if fallback_keywords:
            fallback_topic = f"Narration about {' and '.join(fallback_keywords)}"
            return fallback_topic, 0.2, fallback_keywords
        return "Uncategorized spoken activity", 0.0, []

    cue_tokens = sorted(
        topic_rules[best_topic].intersection(tokens),
        key=lambda token: idf_map.get(token, 1.0),
        reverse=True,
    )[:3]
    return best_topic, round(scores[best_topic], 3), cue_tokens


def infer_segment_intent(tokens):
    intent_rules = {
        "session_setup": {"start", "session", "initial", "begin"},
        "device_control": {"turn", "on", "off", "switch", "click", "button", "press"},
        "light_adjustment": {"brightness", "color", "light", "temperature", "hs"},
        "session_end": {"end", "finish", "stop", "done", "complete"},
    }

    scores = {
        intent: len(rule_words.intersection(tokens))
        for intent, rule_words in intent_rules.items()
    }
    best_intent = max(scores, key=scores.get)
    return best_intent if scores[best_intent] > 0 else "narration"


def enrich_transcript_segments(segments):
    if not segments:
        return []

    idf_map = build_transcript_idf(segments)

    action_words = {
        "start", "press", "click", "turn", "change", "adjust", "end", "stop", "record", "recording"
    }
    entity_words = {
        "light", "brightness", "button", "switch", "session", "video", "logs", "color", "temperature"
    }

    enriched = []
    total = len(segments)
    for idx, seg in enumerate(segments):
        tokens = set(tokenize_text(seg.get("text", "")))
        actions = sorted(tokens.intersection(action_words))
        entities = sorted(tokens.intersection(entity_words))
        intent = infer_segment_intent(tokens)
        semantic_topic, semantic_score, semantic_cues = infer_semantic_topic(tokens, intent, idf_map)

        stage_ratio = idx / max(1, total - 1)
        if stage_ratio < 0.34:
            stage = "early"
        elif stage_ratio < 0.67:
            stage = "middle"
        else:
            stage = "late"

        summary_parts = [semantic_topic, f"{stage} segment"]
        if entities:
            summary_parts.append(f"entities: {', '.join(entities[:3])}")
        if actions:
            summary_parts.append(f"actions: {', '.join(actions[:3])}")
        if semantic_cues:
            summary_parts.append(f"cues: {', '.join(semantic_cues)}")

        enriched_seg = dict(seg)
        enriched_seg["intent"] = intent
        enriched_seg["actions"] = actions
        enriched_seg["entities"] = entities
        enriched_seg["stage"] = stage
        enriched_seg["semantic_topic"] = semantic_topic
        enriched_seg["semantic_score"] = semantic_score
        enriched_seg["semantic_cues"] = semantic_cues
        enriched_seg["context_summary"] = " | ".join(summary_parts)
        enriched.append(enriched_seg)

    return enriched


def context_confidence(second, segment):
    if second is None or not segment:
        return 0.0
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start))
    if start <= second <= end:
        return 1.0
    edge_distance = min(abs(second - start), abs(second - end))
    return max(0.0, 1.0 - min(edge_distance / 2.0, 1.0))


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


def merge_intervals(intervals):
    if not intervals:
        return []

    intervals = sorted(intervals, key=lambda x: x["start"])
    merged = [intervals[0].copy()]

    for current in intervals[1:]:
        prev = merged[-1]
        if current["start"] <= prev["end"]:
            prev["end"] = max(prev["end"], current["end"])
            prev["reasons"].update(current.get("reasons", set()))
        else:
            merged.append(current.copy())

    return merged


def build_autoedit_intervals(events, transcript_segments, duration_seconds, offset_seconds=0.0):
    intervals = []

    # Keep all spoken transcript windows.
    for seg in transcript_segments or []:
        try:
            start = max(0.0, float(seg.get("start", 0.0)))
            end = min(duration_seconds, float(seg.get("end", start)))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        intervals.append({"start": start, "end": end, "reasons": {"transcript"}})

    # Keep windows around important events.
    for event in events or []:
        if event.get("include_in_timeline") is False:
            continue

        base_x = event.get("x_val")
        if base_x is None:
            continue

        try:
            x = float(base_x) + float(offset_seconds)
        except (TypeError, ValueError):
            continue

        if not math.isfinite(x):
            continue

        start = max(0.0, x - 1.2)
        end = min(duration_seconds, x + 2.0)
        if end <= start:
            continue
        intervals.append({"start": start, "end": end, "reasons": {"event"}})

    merged = merge_intervals(intervals)
    compact = []
    for item in merged:
        compact.append({
            "start": round(item["start"], 3),
            "end": round(item["end"], 3),
            "reasons": sorted(item.get("reasons", set())),
        })
    return compact


def make_subclip(clip, start_time, end_time):
    """Compatibility wrapper for MoviePy 1.x/2.x clip slicing APIs."""
    if hasattr(clip, "subclip"):
        return clip.subclip(start_time, end_time)
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start_time, end_time)
    raise AttributeError("No compatible subclip API found on VideoFileClip")


@app.route("/api/available-logs", methods=["GET"])
def api_available_logs():
    """Return list of available JSON/JSONL files from logs folder."""
    return jsonify(get_available_logs())


@app.route("/api/auto-edit", methods=["POST"])
def api_auto_edit():
    payload = request.get_json(silent=True) or {}
    video_url = str(payload.get("video_url", "")).strip()
    events = payload.get("events", [])
    transcript_segments = payload.get("transcript_segments", [])
    offset_seconds = float(payload.get("offset_seconds", 0.0) or 0.0)

    if not video_url.startswith("/static/uploads/"):
        return jsonify({"error": "Invalid video URL."}), 400

    video_name = Path(video_url.replace("/static/uploads/", "")).name
    video_path = UPLOAD_FOLDER / video_name
    if not video_path.exists():
        return jsonify({"error": "Source video not found."}), 404

    try:
        src_clip = VideoFileClip(str(video_path))
        duration_seconds = float(src_clip.duration or 0.0)
        if duration_seconds <= 0:
            src_clip.close()
            return jsonify({"error": "Video has invalid duration."}), 400

        intervals = build_autoedit_intervals(events, transcript_segments, duration_seconds, offset_seconds)
        if not intervals:
            src_clip.close()
            return jsonify({"error": "No keep intervals generated."}), 400

        parts = []
        for seg in intervals:
            if seg["end"] - seg["start"] < 0.1:
                continue
            parts.append(make_subclip(src_clip, seg["start"], seg["end"]))

        if not parts:
            src_clip.close()
            return jsonify({"error": "No valid intervals to export."}), 400

        out_name = f"autoedit_{Path(video_name).stem}_{int(time.time())}.mp4"
        out_path = UPLOAD_FOLDER / out_name

        final_clip = concatenate_videoclips(parts, method="compose")
        src_fps = getattr(src_clip, "fps", None) or 24
        write_kwargs = {
            "codec": "libx264",
            "logger": None,
            "fps": src_fps,
        }
        if final_clip.audio is not None:
            write_kwargs["audio_codec"] = "aac"
        else:
            write_kwargs["audio"] = False
        final_clip.write_videofile(str(out_path), **write_kwargs)

        kept_duration = round(sum(seg["end"] - seg["start"] for seg in intervals), 3)

        final_clip.close()
        for part in parts:
            part.close()
        src_clip.close()

        return jsonify({
            "output_url": f"{url_for('static', filename=f'uploads/{out_name}')}?v={int(time.time())}",
            "intervals": intervals,
            "kept_duration": kept_duration,
            "source_duration": round(duration_seconds, 3),
        })
    except Exception as exc:
        return jsonify({"error": f"Auto-edit failed: {exc}"}), 500


@app.route("/", methods=["GET", "POST"])
def upload_page():
    if request.method == "POST":
        if "video_file" not in request.files:
            flash("Please upload a video file.")
            return redirect(request.url)

        video_file = request.files["video_file"]
        json_file = request.files.get("json_file")
        quick_select_file = request.form.get("quick_select_file", "")
        use_json_file = (json_file is not None and json_file.filename != "") or quick_select_file != ""

        if video_file.filename == "":
            flash("No video file selected.")
            return redirect(request.url)

        if use_json_file and not quick_select_file and not allowed_file(json_file.filename, ALLOWED_JSON_EXTENSIONS):
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
            transcript_segments = enrich_transcript_segments(transcript_segments)
            video_duration_seconds = extract_video_duration_seconds(generated_metadata)
            video_creation_datetime = extract_video_creation_datetime(generated_metadata)
        except Exception as e:
            flash(f"Failed to generate metadata from video: {e}")
            return redirect(request.url)

        if use_json_file:
            if quick_select_file:
                # Handle quick-select file from logs folder
                json_path = Path(quick_select_file)
                if not json_path.exists() or not json_path.is_file():
                    flash("Selected log file not found.")
                    return redirect(request.url)
                json_filename = json_path.name
            else:
                # Handle uploaded file
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
                event_dt = None
                if ts:
                    try:
                        # RFC3339-compatible datetime parse
                        event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        tsecs = event_dt.timestamp()
                        time_text = event_dt.strftime("%Y-%m-%d %H:%M:%S")
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
                    "event_dt": event_dt.isoformat() if event_dt else None,
                    "type": readable_type,
                    "description": description,
                    "details": details,
                    "payload": event,
                })

            base = min((ev["tsecs"] for ev in event_list if ev["tsecs"] is not None), default=None)
            creation_epoch = video_creation_datetime.timestamp() if video_creation_datetime else None
            clip_start_epoch, clip_end_epoch, clip_window_mode = choose_clip_window(
                event_list,
                video_creation_datetime,
                video_duration_seconds,
            )
            for ev in event_list:
                if base is not None and ev["tsecs"] is not None:
                    ev["relative_secs"] = max(0.0, ev["tsecs"] - base)
                else:
                    ev["relative_secs"] = float(ev["index"])

            for ev in event_list:
                if clip_start_epoch is not None and ev["tsecs"] is not None:
                    # True-time alignment: event offset from inferred clip start.
                    ev["x_val"] = ev["tsecs"] - clip_start_epoch
                    ev["timeline_basis"] = clip_window_mode
                    ev["in_clip_window"] = clip_start_epoch <= ev["tsecs"] <= clip_end_epoch
                elif creation_epoch is not None and ev["tsecs"] is not None:
                    ev["x_val"] = ev["tsecs"] - creation_epoch
                    ev["timeline_basis"] = "creation_only"
                    ev["in_clip_window"] = None
                else:
                    ev["x_val"] = ev["relative_secs"]
                    ev["timeline_basis"] = "relative"
                    ev["in_clip_window"] = None

            # Link each event to nearby spoken transcript context.
            for ev in event_list:
                matched_segment = match_transcript_segment(ev.get("x_val"), transcript_segments)
                if not matched_segment:
                    continue

                inferred_topic = matched_segment.get("semantic_topic") or shorten_topic(matched_segment["text"])
                inferred_intent = matched_segment.get("intent", "narration")
                inferred_actions = matched_segment.get("actions", [])
                inferred_entities = matched_segment.get("entities", [])
                inferred_stage = matched_segment.get("stage", "unknown")
                inferred_summary = matched_segment.get("context_summary", inferred_topic)
                inferred_semantic_score = matched_segment.get("semantic_score", 0.0)
                inferred_semantic_cues = matched_segment.get("semantic_cues", [])
                inferred_confidence = context_confidence(ev.get("x_val"), matched_segment)
                ev["inferred_topic"] = inferred_topic
                ev["inferred_transcript"] = matched_segment["text"]
                ev["inferred_window"] = f"{matched_segment['start']:.2f}s - {matched_segment['end']:.2f}s"
                ev["inferred_intent"] = inferred_intent
                ev["inferred_actions"] = inferred_actions
                ev["inferred_entities"] = inferred_entities
                ev["inferred_stage"] = inferred_stage
                ev["inferred_summary"] = inferred_summary
                ev["inferred_semantic_score"] = inferred_semantic_score
                ev["inferred_semantic_cues"] = inferred_semantic_cues
                ev["inferred_confidence"] = round(inferred_confidence, 3)
                ev["description"] = f"{ev['description']} | Context: {inferred_summary}"
                ev.setdefault("details", []).extend([
                    f"context_intent: {inferred_intent}",
                    f"context_stage: {inferred_stage}",
                    f"context_entities: {', '.join(inferred_entities) if inferred_entities else 'none'}",
                    f"context_actions: {', '.join(inferred_actions) if inferred_actions else 'none'}",
                    f"context_semantic_score: {inferred_semantic_score:.3f}",
                    f"context_semantic_cues: {', '.join(inferred_semantic_cues) if inferred_semantic_cues else 'none'}",
                    f"context_confidence: {ev['inferred_confidence']:.3f}",
                ])

            # Add a mini event at the start of every transcript segment.
            next_index = max((ev.get("index", -1) for ev in event_list), default=-1) + 1
            for seg in transcript_segments:
                seg_start = float(seg.get("start", 0.0))
                seg_end = float(seg.get("end", seg_start))
                seg_text = str(seg.get("text", "")).strip()
                topic = shorten_topic(seg_text) if seg_text else "Transcript start"

                event_list.append({
                    "index": next_index,
                    "timestamp": None,
                    "time_text": f"{seg_start:.2f}s",
                    "tsecs": seg_start,
                    "event_dt": None,
                    "type": "transcript_start",
                    "description": f"Transcript Start: {topic}",
                    "details": [
                        f"start: {seg_start:.2f}s",
                        f"end: {seg_end:.2f}s",
                    ],
                    "payload": {
                        "field": "Transcript Segment",
                        "start": seg_start,
                        "end": seg_end,
                        "text": seg_text,
                    },
                    "relative_secs": seg_start,
                    "x_val": seg_start,
                    "timeline_basis": "transcript_start",
                    "in_clip_window": None,
                    "inferred_topic": topic,
                    "inferred_transcript": seg_text,
                    "inferred_window": f"{seg_start:.2f}s - {seg_end:.2f}s",
                    "inferred_intent": seg.get("intent", "narration"),
                    "inferred_actions": seg.get("actions", []),
                    "inferred_entities": seg.get("entities", []),
                    "inferred_stage": seg.get("stage", "unknown"),
                    "inferred_summary": seg.get("context_summary", topic),
                    "inferred_semantic_score": seg.get("semantic_score", 0.0),
                    "inferred_semantic_cues": seg.get("semantic_cues", []),
                    "inferred_confidence": 1.0,
                    "is_mini_event": True,
                    "include_in_timeline": False,
                })
                next_index += 1

        return render_template(
            "index.html",
            metadata=metadata,
            raw_jsonl_lines=raw_jsonl_lines,
            stats=stats,
            events=event_list,
            transcript_segments=transcript_segments,
            video_url=url_for("static", filename=f"uploads/{video_filename}"),
            video_type=video_type,
            json_filename=json_filename,
            video_duration_seconds=video_duration_seconds,
            video_creation_datetime=(video_creation_datetime.isoformat() if video_creation_datetime else None),
            clip_start_epoch=clip_start_epoch,
            clip_end_epoch=clip_end_epoch,
            clip_window_mode=clip_window_mode,
        )

    return render_template(
        "index.html",
        events=[],
        stats=[],
        metadata=None,
        raw_jsonl_lines=[],
        transcript_segments=[],
        video_duration_seconds=None,
        video_creation_datetime=None,
        clip_start_epoch=None,
        clip_end_epoch=None,
        clip_window_mode=None,
    )


if __name__ == "__main__":
    # Disable watchdog reloader on Windows to avoid repeated false reload events.
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)
