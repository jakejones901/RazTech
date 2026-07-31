# RazTech Ingestion Agent

First stage of the **RazTech AI Content Pipeline**.

Detects newly completed stream recordings, validates them, extracts metadata, organizes assets, writes a machine-readable manifest, and notifies the **Clip Detection Agent**.

This agent does **not**:

- Edit, re-encode, or upload videos
- Analyze viral moments
- Create clips
- Implement downstream agents

## Features

- Watches `/streams/recordings/`, `/obs/output/`, and `/imports/` (configurable)
- Supports `mp4`, `mkv`, `mov`, `avi`
- Ignores temp, partial, and hidden files
- Waits until file size is unchanged for 60 seconds
- Validates via `ffprobe` (video/audio streams, duration > 2 minutes, codec, resolution, frame rate)
- Extracts rich metadata and stream context (game, OBS scene, platform, OS)
- Prepares placeholders and lightweight indexes (thumbnail, waveform, silence map, loudness, scenes, chapters)
- Stores under `/content/YYYY/MM/DD/<RAZ-YYYYMMDD-NNN>/`
- Failed files go to `/failed/` with `failure_report.json`
- Structured JSON logging
- Docker + Windows/Linux path support
- Async processing with concurrency limits

## Quick start

### Requirements

- Python 3.11+
- `ffmpeg` / `ffprobe` on `PATH`

### Install

```bash
cd ingestion_agent
pip install -e ".[dev]"
```

### Configure

Edit `config/default.yaml` or create `config/local.yaml`. Paths and behavior can also be overridden with environment variables:

| Variable | Purpose |
|----------|---------|
| `INGESTION_CONFIG` | Path to YAML override |
| `INGESTION_CONTENT_ROOT` | Content store root |
| `INGESTION_FAILED_ROOT` | Failed ingestions root |
| `INGESTION_WATCH_DIRS` | `os.pathsep`-separated watch dirs |
| `INGESTION_STABILITY_SECONDS` | Size-stability window |
| `INGESTION_MIN_DURATION_SECONDS` | Minimum duration gate |
| `INGESTION_MAX_CONCURRENT` | Parallel ingestions |
| `INGESTION_LOG_LEVEL` | Log level |

### Run (watch mode)

```bash
ingestion-agent watch
```

### Process one file

```bash
ingestion-agent process /path/to/recording.mp4 --skip-stability
```

### Docker

```bash
docker compose up --build
```

Mount host folders over the named volumes as needed.

## Output layout

Successful ingestion:

```
/content/YYYY/MM/DD/RAZ-YYYYMMDD-NNN/
  video.mp4
  manifest.json
  metadata.json
  processing.log
  hash.txt
  preview.jpg
  content_prep.json
  .pipeline/RAZ-YYYYMMDD-NNN.notify.json
```

Failure:

```
/failed/<timestamp>_<name>/
  <original file>
  failure_report.json
  processing.log
```

## Success contract

```
SUCCESS
Video ID: RAZ-20260731-001
Duration: 3600.0
Game: Valorant
Output directory: /content/2026/07/31/RAZ-20260731-001
Manifest location: /content/2026/07/31/RAZ-20260731-001/manifest.json
Next Agent:
Clip Detection Agent
```

## Tests

```bash
cd ingestion_agent
pytest -q
```

## Package layout

```
ingestion_agent/
  config/default.yaml
  src/ingestion_agent/
    config.py
    watcher.py
    validator.py
    metadata.py
    stream_detection.py
    content_prep.py
    storage.py
    manifest.py
    id_generator.py
    pipeline.py
    notifier.py
    ffprobe.py
    logging_setup.py
    models.py
  tests/
  Dockerfile
  docker-compose.yml
```
