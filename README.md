<div align="center">

# vlearn

### Give image-capable LLMs the ability to understand video.

**Turn any YouTube video into a structured, timestamped, verifiable report, using local models and a 15-tool MCP server. No API fees.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-yellow.svg)](LICENSE)
[![MCP Server](https://img.shields.io/badge/MCP-15%20tools-purple.svg)](#mcp-server)
[![Local LLM](https://img.shields.io/badge/LLM-llama.cpp%20%7C%20Ollama-orange.svg)](https://github.com/ggerganov/llama.cpp)

**English** · [繁體中文](README.zh-TW.md)

[Quickstart](#quickstart) · [MCP Server](#mcp-server) · [How it works](#how-it-works) · [Configuration](#configuration) · [FAQ](#faq)

</div>

---

vlearn is an open-source **YouTube video summarizer and MCP server** for people who want to *check* a summary, not just read it. It combines subtitles, keyframes and a local vision-language model (VLM) into a report where **every claim carries a timestamp and a source**, and where disagreements between sources are **flagged instead of silently merged**.

It also lets AI agents (Claude Desktop, Hermes and other MCP clients) work with video even when their model **can read images but has no native video input**. Instead of a raw video, the agent gets a timestamped timeline of subtitles and keyframe descriptions, and can pull **any single frame on demand**.

## Demo

> 🎬 *Demo GIF coming soon.*

```text
$ vlearn ingest "https://youtube.com/watch?v=qp0HIF3SfI4" --platform youtube
{'video_id': 'qp0HIF3SfI4', 'title': 'How Great Leaders Inspire Action', 'duration': 1115.0, 'subtitle_segments': 43}

$ vlearn run qp0HIF3SfI4
{'run_id': 'run_abc123', 'bundles': 13, 'conflicts': 0, 'image_frames': 9, 'cost_usd': 0.0}

$ vlearn report run_abc123
# How Great Leaders Inspire Action | Simon Sinek | TED

## Core Content
### 00:45 – 02:14
- [official_subtitle] Why is Apple so innovative? ...

## Key Moments
### 09:45 – 11:14
- [name]   Orville and Wilbur Wright
- [number] December 17th, 1903
- [number] 2.5%
- [color]  deep red curtain
- [other]  On-screen text: "Number of talks: 1"
...
```
*(abridged; every line carries its source tag and time range)*

## Why vlearn?

Most YouTube summarizers return a paragraph you have to trust. vlearn is built around three ideas:

- **Verifiable.** Every assertion is tagged with a timestamp and a source type (`official_subtitle`, `keyframe_ocr`, `keyframe_vlm`, `asr`, `danmaku`). You can jump back to the evidence.
- **Honest about conflicts.** When the subtitles say one thing and a keyframe shows another, vlearn arbitrates by source reliability and, if unresolved, **keeps both versions**.
- **It looks at the video, not just the transcript.** Keyframes are chosen by scene change and described by a local VLM. The image pipeline is independent of subtitles, so silent videos work too.

| | Typical summarizer | **vlearn** |
|---|---|---|
| Output | Prose paragraph | Structured report with assertions |
| Traceability | Usually none | Timestamp + source ref on every claim |
| Source disagreement | Not surfaced | Detected, arbitrated, both versions kept |
| Visual content | Often transcript only | Keyframes described by a VLM |
| Where data goes | Usually a cloud service | Your machine (SQLite + files) |
| Cost | API fees or subscription | $0 with local models |
| Agent integration | Rarely | 15 MCP tools |
| Corrections | Manual editing | Persistent correction loop (`vlearn review`) |

## Quickstart

**Prerequisites:** Python 3.10+, FFmpeg, [Deno](https://deno.com/) (needed by yt-dlp). A local LLM server is optional but recommended.

```bash
# 1. Install
git clone https://github.com/MRSogzz/vlearn.git
cd vlearn
pip install -e ".[media]"

# 2. (Recommended) start a local LLM; any OpenAI-compatible server works
#    Without one, vlearn falls back to regex extraction (lower quality, still free)
llama-server -m models/gemma-4-e4b.gguf --port 8080

# 3. Analyze a video
python -m app ingest "https://youtube.com/watch?v=qp0HIF3SfI4" --platform youtube
python -m app run qp0HIF3SfI4
python -m app report <run_id>
```

Expect roughly 2–5 minutes for an 18-minute video, mostly LLM inference. No GPU is required, but one makes summaries much better.

## MCP Server

vlearn exposes its pipeline through the [Model Context Protocol](https://modelcontextprotocol.io/), so an agent can ingest a video, read the report, inspect conflicts and **request a single frame at any timestamp**.

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "vlearn": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "env": {
        "VLEARN_CONFIG": "/path/to/vlearn/config/default.yaml",
        "PYTHONPATH": "/path/to/vlearn"
      }
    }
  }
}
```

<details>
<summary><b>Hermes Desktop config</b></summary>

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  vlearn:
    command: "/path/to/venv/bin/python"        # Windows: C:/path/to/venv/Scripts/python.exe
    args: ["-m", "app.mcp.server"]
    env:
      VLEARN_CONFIG: "/path/to/vlearn/config/default.yaml"
      PYTHONPATH: "/path/to/vlearn"
    enabled: true
    timeout: 600
    connect_timeout: 60
```
</details>

Then ask your agent: *"Analyze this YouTube video and list any conflicts: <url>"*.

<details>
<summary><b>All 15 tools, resources and prompts</b></summary>

| Tool | Purpose |
|---|---|
| `ingest_video(url, platform)` | Fetch metadata and subtitles |
| `analyze_video(video_id)` | Start async analysis |
| `get_job_status(job_id)` | Poll job progress |
| `get_report(run_id)` | Read the Markdown report |
| `get_conflicts(run_id)` | List detected conflicts |
| `read_frame_at(video_id, ts)` | Extract a single frame on demand |
| `submit_correction(...)` | Submit a manual correction |
| `list_videos(limit)` / `get_video(video_id)` | Browse ingested videos |
| `get_cost_summary(daily)` | Cost ledger |
| `import_trend_csv(path)` / `list_trend_top(n)` | Trending-video workflow |
| `preview_keyframe_selection(...)` | Debug frame-level selection |
| `preview_keyframe_selection_seek(...)` | Debug seek-margin selection |
| `arbitrate_evidence(...)` | Manual arbitration |

**Resources:** `vlearn://videos/{video_id}` (metadata JSON), `vlearn://reports/{run_id}` (full report)
**Prompts:** `analyze_youtube(url)`, `trend_digest()`
</details>

## How it works

```text
YouTube URL
    │
    ▼
INGEST        metadata + subtitles (3-tier fallback: timedtext → yt-dlp → empty)
    │
    ▼
ANALYZE       ┌─ Subtitle pipeline:  triage → window split → LLM summary
(orchestrator)├─ Image pipeline:     probe → classify → scan → VLM description   (independent of subtitles)
              └─ Fusion:             evidence bundles → consistency check
                                     → arbitration → backtrace → final summary
    │
    ▼
Structured Markdown report + SQLite
```

Design decisions that matter:

- **Keyframes are fetched on demand, not by downloading the whole video.** Remote videos use a seek-margin strategy; frame-exact selection is kept for locally downloaded files (`download_media: true`).
- **Right-boundary truncation.** A keyframe window never reaches into the next scene.
- **Evidence bundles use bidirectional overlap**, so a short window is not swallowed by a long one.
- **Reliability-weighted arbitration:** `official_subtitle > keyframe_ocr > keyframe_vlm > asr > danmaku`. Unresolved conflicts keep both versions.
- **Semantic color normalization.** `red curtain` and `深紅色帷幕` count as consistent, but the report preserves the original wording.
- **Fully local state.** Everything lives in SQLite plus files under `out/`; no external API is required.

## Configuration

Swap models by editing `config/models.yaml`; no code changes.

```yaml
providers:
  local:
    base_url: http://127.0.0.1:8080/v1
    api_key: sk-local
    models:
      gemma:
        role: cheap
        supports_vision: true
        input_usd: 0.0
        output_usd: 0.0

routing:
  triage:        {provider: local, model: gemma}
  local_summary: {provider: local, model: gemma}
  keyframe_desc: {provider: local, model: gemma}
```

<details>
<summary><b>Use a text-only model for summaries and a VLM for frames (e.g. Qwen3 27B via Ollama)</b></summary>

```yaml
providers:
  local-qwen:
    base_url: http://127.0.0.1:11434/v1
    api_key: sk-local
    models:
      qwen3-27b:
        role: cheap
        supports_vision: false
        input_usd: 0.0
        output_usd: 0.0

routing:
  triage:        {provider: local-qwen, model: qwen3-27b}
  local_summary: {provider: local-qwen, model: qwen3-27b}
  keyframe_desc: {provider: local,      model: gemma}   # vision stays on Gemma
```
</details>

<details>
<summary><b><code>config/default.yaml</code> reference</b></summary>

```yaml
platform:
  primary: youtube
  youtube:
    download_media: false    # true = full download
  bilibili:
    enabled: false

keyframes:
  scene_threshold: 0.35      # FFmpeg scene-detection threshold
  max_window_sec: 8.0        # max window for the last change point
  min_gap_sec: 1.0           # merge dense change points
  fixed_interval_sec: 90     # fallback sampling interval
  max_frames_per_10min: 30   # frame budget

vision:
  policy: on_demand          # always | on_demand | none
  max_images_per_video: 25

cost:
  daily_usd: 2.0
  per_video_usd: 0.10
  on_exceed: degrade         # degrade | stop

publish:
  comment_enabled: false
```
</details>

## CLI

```bash
vlearn ingest <url> --platform youtube          # metadata + subtitles
vlearn run <video_id> --profile standard        # full pipeline
vlearn report <run_id> --format md              # read the report
vlearn review <run_id> --ref <assertion_ref> --old "old" --new "new" --note "why"
vlearn cost --daily                             # cost ledger
vlearn videos --limit 20
vlearn trend import <csv> && vlearn trend run --top 20
```

## Known limitations

- Small local models (e.g. a 4B VLM) vary run to run: assertion counts can range from about 16 to 48 on the same input. A larger model or `temperature=0` helps.
- VLMs can over-interpret frames (for example "dark red" for "red"). Use `vlearn review` to correct it; corrections persist across re-runs.
- `apply_corrections` does plain substring replacement, and the `assertions` field does not reflect corrections.
- The video-type classifier may misjudge some talks (e.g. TED) as slide presentations.
- CLI/MCP only; there is no web UI yet. Live streams are not supported.

## FAQ

<details>
<summary><b>Do I need a GPU?</b></summary>

No. Without a local LLM, vlearn falls back to regex-based assertion extraction (lower quality, zero cost). Any OpenAI-compatible runtime works: llama.cpp, Ollama, LM Studio, vLLM.
</details>

<details>
<summary><b>Can I use a different or hosted model?</b></summary>

Yes, edit `config/models.yaml`. Common swaps: Qwen3 27B (more stable assertions, no vision), a cheap cloud model such as DeepSeek, or GPT-4o / Claude for the highest quality at higher cost.
</details>

<details>
<summary><b>Does it work offline?</b></summary>

Mostly. After a video has been ingested, `vlearn run` works fully offline. Only the first `ingest` needs the network, and not even that if subtitles are cached in `cache/subs/<video_id>/`.
</details>

<details>
<summary><b>Which languages are supported?</b></summary>

Subtitles: any language YouTube provides. Assertion extraction works best in English and Chinese; other languages fall back to regex. Output language depends on the model you route to.
</details>

<details>
<summary><b>Why does the report say "deep red" when the frame shows "red"?</b></summary>

Two reasons: small VLMs over-interpret, and conflict detection normalizes `deep red curtain`, `red curtain` and `深紅色帷幕` to the same value while keeping the original text in the report. Fix wording with `vlearn review`.
</details>

<details>
<summary><b>How do I add a platform (Bilibili, Vimeo, ...)?</b></summary>

Create an adapter in `app/adapters/` and register it in `AppContext.from_config()` (`app/context.py`). The pipeline is platform-agnostic.

```python
from app.adapters.base import PlatformAdapter, VideoMeta

class VimeoAdapter(PlatformAdapter):
    name = "vimeo"
    capabilities = {"metadata", "subtitles"}

    def get_metadata(self, url: str) -> VideoMeta: ...
    def get_subtitles(self, meta: VideoMeta) -> list[dict]: ...
```
</details>

<details>
<summary><b>Where is everything stored?</b></summary>

```text
out/
├── vlearn.db          # SQLite (all structured data)
├── run_xxx.md         # Markdown reports
└── frames/<video_id>/ # Extracted keyframes
```
Delete `out/` to start fresh. `vlearn.db` can be backed up on its own.
</details>

<details>
<summary><b>Is there a hosted version or a web UI?</b></summary>

No. vlearn is a local-first tool for technical users, which keeps videos on your machine and costs at zero. A multi-user web service would need auth, queues, storage isolation and cost attribution, which is a different product. The AGPL license lets you build one.
</details>

## Development

```bash
pytest -q
```

```text
app/
├── adapters/    platform adapters
├── keyframes/   keyframe selection (selector.py: right-boundary truncation)
├── summarize/   local LLM summarization (5-level JSON rescue)
├── evidence/    bundling, consistency, arbitration
├── fusion/      interleaved context + final summary
├── cost/        ledger, budget, router
├── storage/     SQLite + cache
├── mcp/         MCP server
└── orchestrator.py
```

## Roadmap

- [x] **M0** Subtitle extraction, keyframes, local summaries, Markdown report
- [x] **M1** Triage, right-boundary truncation, evidence bundling, cost ledger
- [x] **M2** Conflict detection, arbitration, image pipeline, manual corrections
- [ ] **M3** OCR (PaddleOCR), Bilibili adapter, trending-CSV workflow
- [ ] **M4** FastAPI layer + web UI
- [ ] Docker image

## Contributing

PRs are welcome; please open an issue first for major changes. Every new behavior needs a test.

```bash
git checkout -b feature/my-feature
pytest -q
git commit -m "feat: my feature"
```

## Disclaimer

vlearn uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to fetch subtitles and frames; it does **not** use YouTube's official API. It is intended for personal learning and research. You are responsible for complying with the terms of service of the platforms you use and with copyright law in your jurisdiction. The software is provided as-is, without warranty.

## License

[AGPL-3.0](LICENSE). Network services built on vlearn must publish their source. For commercial licensing: `<MRSogzz@gmail.com>`

## Acknowledgments

[yt-dlp](https://github.com/yt-dlp/yt-dlp) · [llama.cpp](https://github.com/ggerganov/llama.cpp) · [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) · [pydantic](https://github.com/pydantic/pydantic)

---

<div align="center">

**If vlearn saves you time, a ⭐ helps others find it.**

</div>
