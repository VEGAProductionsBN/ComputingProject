# ComputingProject

Event-synchronised video analysis pipeline for Home Assistant sessions.

The project contains:
- Metadata collection scripts for Home Assistant entities.
- A Flask dashboard to upload video + logs, align events to media time, auto-edit clips, and export ELAN-style timeline outputs.

## Project Structure

- `MetadataCollection/`: scripts that poll Home Assistant and write JSONL logs.
- `Visualisation/`: Flask app that visualises events/transcript and generates auto-edited exports.
- `home_assistant_logs/`: generated session logs.

## Security First

Home Assistant tokens must not be hardcoded in source files.

This repository now reads credentials from environment variables or `MetadataCollection/.env`, and `.gitignore` excludes local secret files.

If a token was previously committed, rotate it in Home Assistant immediately.

## Configuration

Create `MetadataCollection/.env` with your local values:

```env
HA_URL=http://homeassistant.local:8123
HA_TOKEN=YOUR_LONG_LIVED_ACCESS_TOKEN
LIGHT_ENTITY_ID=light.eveready_rgbcct_led_bc_gls
FLIC_ENTITY_ID=binary_sensor.flic_80e4da79f712
TAPO_ENTITY_ID=switch.tapo_P110
LOG_DIR=home_assistant_logs
```

Environment variable names used by the collectors:
- `HA_URL`
- `HA_TOKEN`
- `LIGHT_ENTITY_ID`
- `FLIC_ENTITY_ID`
- `TAPO_ENTITY_ID`
- `LOG_DIR`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies for each area you use.

Example:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install aiohttp flask hachoir moviepy faster-whisper
```

Or install dashboard dependencies with:

```powershell
pip install -r Visualisation/requirements.txt
```

## Running Metadata Collection

Run the Home Assistant session logger:

```powershell
python MetadataCollection/pull_home_metadata.py
```

This writes a timestamped JSONL session file to `home_assistant_logs/`.

## Running the Dashboard

```powershell
python Visualisation/app.py
```

Open `http://localhost:5000` and:
- Upload a video.
- Choose or upload a JSON/JSONL event log.
- Align timeline offsets if needed.
- Generate an auto-edited export.

## Auto-Edit and ELAN-Style Export

The dashboard supports exporting:
- Auto-edited video (`.mp4`)
- ELAN annotation file (`.eaf`)
- Timeline table (`.csv`)
- Combined package (`.zip`) containing all outputs

This is designed for annotation workflows similar to ELAN while preserving the edited media output.

## Notes

- `home_assistant_logs/` can become large over time; archive or clean old sessions as needed.
- If transcript generation is slow, consider a smaller/faster Whisper model configuration.
