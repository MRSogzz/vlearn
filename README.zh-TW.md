<div align="center">

# vlearn

### 讓能讀圖、但不能讀影片的 LLM 也能理解 YouTube 影片

**開源、模型無關的 MCP 服務器，把 YouTube 影片轉成結構化、帶時間戳、可驗證的報告。支援任何 OpenAI 相容端點，雲端或本地皆可；完全本地執行時零成本。**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-yellow.svg)](LICENSE)
[![MCP Server](https://img.shields.io/badge/MCP-15%20tools-purple.svg)](#mcp-server)
[![OpenAI-compatible](https://img.shields.io/badge/LLM-OpenAI--compatible-orange.svg)](#設定)

[English](README.md) · **繁體中文**

[快速開始](#快速開始) · [MCP Server](#mcp-server) · [運作原理](#運作原理) · [設定](#設定) · [FAQ](#faq)

</div>

---

vlearn 是開源的 **YouTube 影片摘要工具與 MCP Server**，適合想要「驗證」摘要而不只是閱讀的人。它結合字幕、關鍵幀與視覺語言模型（VLM，本地或雲端皆可），產出**每條斷言都帶時間戳與來源**的報告；來源之間互相矛盾時會**明確標示，而不是悄悄合併**。

它也讓 AI Agent（Claude Desktop、Hermes 等 MCP 用戶端）即使底層模型**能讀圖但沒有原生影片輸入**，也能處理影片：Agent 拿到的不是原始影片，而是帶時間戳的字幕與關鍵幀描述時間軸，並且可以**隨時按需取任意單幀**。

## 演示

> 🎬 *Demo GIF 製作中。*

```text
$ vlearn ingest "https://youtube.com/watch?v=qp0HIF3SfI4" --platform youtube
{'video_id': 'qp0HIF3SfI4', 'title': 'How Great Leaders Inspire Action', 'duration': 1115.0, 'subtitle_segments': 43}

$ vlearn run qp0HIF3SfI4
{'run_id': 'run_abc123', 'bundles': 13, 'conflicts': 0, 'image_frames': 9, 'cost_usd': 0.0}

$ vlearn report run_abc123
# How Great Leaders Inspire Action | Simon Sinek | TED

## 核心內容
### 00:45 – 02:14
- [official_subtitle] Why is Apple so innovative? ...

## 關鍵時間點
### 09:45 – 11:14
- [name]   Orville and Wilbur Wright
- [number] December 17th, 1903
- [number] 2.5%
- [color]  深紅色帷幕
- [other]  螢幕顯示 "Number of talks: 1"
...
```
*（節錄；每一行都帶來源標籤與時間區間）*

## 為什麼選 vlearn？

多數 YouTube 摘要工具只給你一段必須「相信」的文字。vlearn 圍繞三個原則設計：

- **可驗證。** 每條斷言都標註時間戳與來源類型（`official_subtitle`、`keyframe_ocr`、`keyframe_vlm`、`asr`、`danmaku`），可以直接回到證據。
- **誠實面對衝突。** 字幕說一套、畫面顯示另一套時，vlearn 依來源可靠性仲裁；無法裁決時**保留雙版本**。
- **不只看逐字稿，也看畫面。** 關鍵幀依場景變化挑選，由 VLM 描述。圖片管線獨立於字幕，無聲影片也能處理。

| | 一般摘要工具 | **vlearn** |
|---|---|---|
| 輸出 | 一段散文 | 結構化報告 + 斷言 |
| 可回溯 | 通常沒有 | 每條斷言帶時間戳 + 來源 |
| 來源矛盾 | 不呈現 | 檢出、仲裁、保留雙版本 |
| 畫面內容 | 常只處理逐字稿 | VLM 描述關鍵幀 |
| 資料去向 | 多為雲端服務 | 留在你的機器（SQLite + 檔案） |
| 成本 | API 費用或訂閱 | 本地模型 $0 |
| Agent 整合 | 少見 | 15 個 MCP 工具 |
| 人工修正 | 手動編輯 | 持久化修正閉環（`vlearn review`） |

## 快速開始

**前置需求：** Python 3.10+、FFmpeg、[Deno](https://deno.com/)（yt-dlp 需要）。LLM 端點（本地服務或雲端 API）為可選，但建議設定。畫面分析需要支援視覺的模型；字幕摘要用純文字模型即可。

```bash
# 1. 安裝
git clone https://github.com/MRSogzz/vlearn
cd vlearn
pip install -e ".[media]"

# 2.（建議）啟動本地 LLM，任何 OpenAI 相容服務皆可
#    未啟動時會降級為正則抽取（品質較低，仍然免費）
llama-server -m models/gemma-4-e4b.gguf --port 8080

# 3. 分析影片
python -m app ingest "https://youtube.com/watch?v=qp0HIF3SfI4" --platform youtube
python -m app run qp0HIF3SfI4
python -m app report <run_id>
```

18 分鐘的影片約需 2–5 分鐘，時間主要花在 LLM 推理。不需要 GPU，但有的話摘要品質會好很多。

## MCP Server

vlearn 透過 [Model Context Protocol](https://modelcontextprotocol.io/) 開放整條管線，Agent 可以攝取影片、讀取報告、檢視衝突，並**在任意時間點按需取單幀**。

**Claude Desktop**（`claude_desktop_config.json`）：

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
<summary><b>Hermes Desktop 設定</b></summary>

加入 `~/.hermes/config.yaml`：

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

接著對 Agent 說：*「分析這支 YouTube 影片並列出衝突：<url>」*。

<details>
<summary><b>15 個工具、資源與提示詞</b></summary>

| 工具 | 用途 |
|---|---|
| `ingest_video(url, platform)` | 攝取元數據 + 字幕 |
| `analyze_video(video_id)` | 啟動非同步分析 |
| `get_job_status(job_id)` | 輪詢 job 進度 |
| `get_report(run_id)` | 讀取 Markdown 報告 |
| `get_conflicts(run_id)` | 衝突列表 |
| `read_frame_at(video_id, ts)` | 按需讀取單幀 |
| `submit_correction(...)` | 提交人工修正 |
| `list_videos(limit)` / `get_video(video_id)` | 瀏覽已攝取影片 |
| `get_cost_summary(daily)` | 成本帳本 |
| `import_trend_csv(path)` / `list_trend_top(n)` | 熱度流程 |
| `preview_keyframe_selection(...)` | 除錯幀級選擇 |
| `preview_keyframe_selection_seek(...)` | 除錯 seek margin 選擇 |
| `arbitrate_evidence(...)` | 手動仲裁 |

**資源：** `vlearn://videos/{video_id}`（元數據 JSON）、`vlearn://reports/{run_id}`（完整報告）
**提示詞：** `analyze_youtube(url)`、`trend_digest()`
</details>

## 運作原理

```text
YouTube URL
    │
    ▼
INGEST（攝取）  元數據 + 字幕（三級降級：timedtext → yt-dlp → 空）
    │
    ▼
ANALYZE（分析） ┌─ 字幕管線：初篩 → 窗口切分 → LLM 摘要
(orchestrator)  ├─ 圖片管線：探針 → 分類 → 掃描 → VLM 描述（獨立於字幕）
                └─ 融合：證據束 → 一致性校驗 → 仲裁 → 回溯 → 最終融合
    │
    ▼
結構化 Markdown 報告 + SQLite
```

關鍵設計：

- **關鍵幀按需取得，不必完整下載影片。** 遠端影片用 seek margin 策略；幀級精確選擇保留給本地已下載的檔案（`download_media: true`）。
- **右邊界截斷。** 關鍵幀窗口不會跨進下一個場景。
- **證據束採雙向重疊判定**，避免小窗口被大窗口吞併。
- **可靠性加權仲裁：** `official_subtitle > keyframe_ocr > keyframe_vlm > asr > danmaku`，無法裁決時保留雙版本。
- **顏色語義歸一化。** `red curtain` 與 `深紅色帷幕` 判定為一致，但報告保留原文。
- **狀態在本地。** 所有資料在 `out/` 的 SQLite 與檔案中；推理在你指定的地方執行，也可以完全本地。

## 設定

換模型只需改 `config/models.yaml`，不用改程式碼。任何 OpenAI 相容端點都可以。`keyframe_desc` 階段需要支援視覺的模型，其他階段用純文字模型即可。

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
<summary><b>摘要用純文字模型、畫面用 VLM（例如 Ollama 上的 Qwen3 27B）</b></summary>

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
  keyframe_desc: {provider: local,      model: gemma}   # 視覺仍用 Gemma
```
</details>

<details>
<summary><b><code>config/default.yaml</code> 參考</b></summary>

```yaml
platform:
  primary: youtube
  youtube:
    download_media: false    # true = 完整下載
  bilibili:
    enabled: false

keyframes:
  scene_threshold: 0.35      # FFmpeg 場景檢測閾值
  max_window_sec: 8.0        # 最後一個變化點的最大窗口
  min_gap_sec: 1.0           # 密集變化點合併
  fixed_interval_sec: 90     # 兜底採樣間隔
  max_frames_per_10min: 30   # 幀預算

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
vlearn ingest <url> --platform youtube          # 攝取元數據 + 字幕
vlearn run <video_id> --profile standard        # 完整管線
vlearn report <run_id> --format md              # 讀取報告
vlearn review <run_id> --ref <assertion_ref> --old "舊" --new "新" --note "原因"
vlearn cost --daily                             # 成本帳本
vlearn videos --limit 20
vlearn trend import <csv> && vlearn trend run --top 20
```

## 驗證狀態

vlearn 目前在三支不同類型的影片上做過抽樣檢查：每支影片抽 30 條斷言（共 90 條），逐條對照來源驗證。所有檢查都使用本地 4B 模型，其他模型尚未量測。樣本很小，請把它當成冒煙測試，而不是基準測試。

| 指標 | 結果 |
|---|---|
| 抽樣斷言數 | 90（每支 30 條），逐條檢查 |
| 可追溯率（時間戳 + 來源 ref 能對應到證據） | **100%**（90/90） |
| VLM 原始輸出中的錯誤斷言 | **3/90**（3.3%；95% 信賴區間約 1% 至 9%） |
| 進入最終摘要的錯誤斷言 | **未觀察到**（95% 上界約 4%） |
| 樣本中來自圖表與案例圖片的斷言 | 檢查均正確（樣本中僅四張圖表） |

**關於那 3 條錯誤斷言：** 每一條都是 VLM 對同一個畫面給出兩種互相矛盾的描述。例如一次說講者拿著綠色麥克風、另一次說黑色麥克風，而畫面實際上是貼著綠色標籤的黑色麥克風。衝突檢測標出了這個分歧，管線將這些斷言排除，摘要中沒有使用任何一條。

**涵蓋的影片類型**

| 類型 | 時長 | 特徵 |
|---|---|---|
| 幽默型研討會演講 | 約 6 分鐘 | 單鏡頭人像、大螢幕投影、少量文字 |
| 正式商業演講 | 約 18 分鐘 | 單鏡頭人像、案例圖片、一張圖表 |
| 音樂 MV | 約 3.5 分鐘 | 多場景剪輯、歌詞字幕、舞台與舞蹈 |

合起來涵蓋：字幕從極密到極疏、畫面從幾乎不變到頻繁剪輯、近 5 倍的長度跨度、兩種演講風格，以及重複文字的字幕。

**尚未測試**

| 內容類型 | 為什麼重要 | 可能風險（尚未驗證） |
|---|---|---|
| 教程、投影片、程式碼演示、螢幕錄製 | VLM 幻覺最可能嚴重的場景 | 小型 VLM 可能編造圖表數字或程式碼。目前只測過一張圖表，證據不足 |
| 無字幕影片（無聲示範、舞蹈） | 測試 `subtitle = 0` 的降級路徑 | 可能退化成只有關鍵幀斷言 |
| 2 分鐘以下的短影片 | 測試 `triage.min_duration_sec: 120` 邊界 | 可能被判為「不值得深讀」而只走輕量摘要 |
| 非英語影片 | 字幕語言覆蓋 | CJK 加權的斷言過濾只針對中英文調過 |
| 訪談與 Podcast（固定機位、以人臉為主） | 畫面冗餘 | 可能把幀預算花在資訊量很低的畫面上 |
| 新聞與紀錄片（多來源畫面混合） | 字幕與畫面高度相關 | 可能觸發更多衝突 |
| 直播錄影（超過 1 小時） | 超長輸入 | 窗口數很多，LLM 呼叫成本可能快速上升 |

**徵求協助：** 如果你在上述任一類型試用 vlearn，歡迎開 issue 回報影片類型、哪些有效、哪些無效。每份回報都會直接影響路線圖。

## 已知限制

- 小型本地模型（例如 4B VLM）每次輸出有波動：同一支影片的斷言數可能在 16–48 條之間浮動。換更大的模型或設 `temperature=0` 可改善。不同影片之間的條數差異屬正常，與此無關。
- 衝突檢測抓得到「不一致」的錯誤；如果 VLM 每次都犯同樣的錯，就不會被標出。
- VLM 可能過度解讀畫面（例如把「紅色」說成「深紅色」）。可用 `vlearn review` 修正，修正在重跑後仍會保留。
- `apply_corrections` 是純字串替換，`assertions` 欄位不會隨修正更新。
- 影片類型分類器可能把部分演講（如 TED）誤判為投影片簡報。
- 目前只有 CLI/MCP，沒有 Web UI；不支援直播。

## FAQ

<details>
<summary><b>需要 GPU 嗎？</b></summary>

不需要。未啟動本地 LLM 時會降級為正則抽取（品質較低，零成本）。任何 OpenAI 相容的執行環境都可以：llama.cpp、Ollama、LM Studio、vLLM。
</details>

<details>
<summary><b>能換其他模型或雲端模型嗎？</b></summary>

可以，修改 `config/models.yaml` 即可。任何 OpenAI 相容端點都能用，例如 GPT-4o、DeepSeek 等雲端模型，或本地的 Qwen3 27B（純文字，畫面需搭配視覺模型）。Claude 等非 OpenAI 格式的 API 可透過 OpenRouter、LiteLLM 這類相容閘道使用。目前只驗證過本地 4B 模型（見「驗證狀態」）。
</details>

<details>
<summary><b>能離線使用嗎？</b></summary>

大部分可以。影片攝取完成後，`vlearn run` 可完全離線。只有第一次 `ingest` 需要網路；若 `cache/subs/<video_id>/` 已有快取字幕，連攝取也能離線。
</details>

<details>
<summary><b>支援哪些語言？</b></summary>

字幕：YouTube 提供的任何語言。斷言抽取對英文與中文效果最好，其他語言會降級為正則。輸出語言取決於你路由到的模型。
</details>

<details>
<summary><b>畫面明明是「紅色帷幕」，報告為什麼寫「深紅色帷幕」？</b></summary>

兩個原因：小型 VLM 容易過度解讀；另外衝突檢測會把 `深紅色帷幕`、`紅色帷幕`、`red curtain` 歸一化為同一個值，但報告保留原文。可用 `vlearn review` 修正措辭。
</details>

<details>
<summary><b>如何新增平台（B 站、Vimeo 等）？</b></summary>

在 `app/adapters/` 新增適配器，並在 `app/context.py` 的 `AppContext.from_config()` 註冊。管線與平台無關。

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
<summary><b>資料存在哪？</b></summary>

```text
out/
├── vlearn.db          # SQLite（所有結構化資料）
├── run_xxx.md         # Markdown 報告
└── frames/<video_id>/ # 擷取的關鍵幀
```
刪掉 `out/` 即可重來；`vlearn.db` 可單獨備份。
</details>

<details>
<summary><b>為什麼把衝突的斷言排除，而不是選一個？</b></summary>

當來源可靠性排序能裁決分歧時，vlearn 會仲裁並採用較可靠的來源。無法裁決時，vlearn 保留雙版本、標記為未解決，且不在摘要中把任何一方當成事實陳述；可用 `get_conflicts(run_id)` 查看。代價是報告的斷言數可能少於模型原始輸出。這是刻意的取捨：缺一條斷言，比多一條沒人看得出來的錯誤斷言更容易接受。
</details>

<details>
<summary><b>有託管版或 Web UI 嗎？</b></summary>

沒有。vlearn 定位為面向技術用戶的本地工具，影片不離開你的機器，成本為零。多用戶 Web 服務需要鑑權、任務佇列、儲存隔離與成本歸屬，那是另一個產品；AGPL 授權允許你自行打造。
</details>

## 開發

```bash
pytest -q
```

```text
app/
├── adapters/    平台適配器
├── keyframes/   關鍵幀選擇（selector.py：右邊界截斷）
├── summarize/   本地 LLM 摘要（五級 JSON 搶救）
├── evidence/    證據束、一致性、仲裁
├── fusion/      交錯上下文 + 最終摘要
├── cost/        帳本、預算、路由
├── storage/     SQLite + 快取
├── mcp/         MCP 服務
└── orchestrator.py
```

## 路線圖

- [x] **M0** 字幕抽取、關鍵幀、本地摘要、Markdown 報告
- [x] **M1** 初篩、右邊界截斷、證據束、成本帳本
- [x] **M2** 衝突檢測、仲裁、圖片管線、人工修正
- [ ] **M3** OCR（PaddleOCR）、B 站適配器、短影音熱度流程
- [ ] **M4** FastAPI 層 + Web UI
- [ ] Docker 映像

## 貢獻

歡迎 PR；重大改動請先開 issue 討論。每個新行為都需要測試。

```bash
git checkout -b feature/my-feature
pytest -q
git commit -m "feat: my feature"
```

## 免責聲明

vlearn 使用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 抓取字幕與畫面，**不使用** YouTube 官方 API。本工具定位為個人學習與研究用途。你需自行遵守所使用平台的服務條款與所在地的著作權法。軟體以現狀提供，不附任何保證。

## 授權

[AGPL-3.0](LICENSE)。基於 vlearn 提供的網路服務必須公開原始碼。商業授權諮詢：`<MRSogzz@gmail.com>`

## 致謝

[yt-dlp](https://github.com/yt-dlp/yt-dlp) · [llama.cpp](https://github.com/ggerganov/llama.cpp) · [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) · [pydantic](https://github.com/pydantic/pydantic)

---

<div align="center">

**如果 vlearn 幫你省了時間，一顆 ⭐ 能讓更多人找到它。**

</div>
