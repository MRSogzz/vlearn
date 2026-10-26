from __future__ import annotations

import base64
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent

from app.context import AppContext
from app.evidence.arbiter import arbitrate
from app.keyframes.selector import select_keyframes, select_keyframes_seek
from app.mcp.jobs import JobRunner
from app.schemas import EvidenceBundle, SourceType


def _to_bool(value, default: bool = False) -> bool:
    """MCP 客戶端傳參可能把 bool 序列化成字符串，需要歸一化。

    - True / False / 1 / 0 → 保持原值
    - "true" / "True" / "1" / "yes" → True
    - "false" / "False" / "0" / "no" / "" → False
    - None / 其他 → default
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off", ""):
            return False
    return default


def register(mcp: MCPServer, ctx: AppContext) -> None:
    runner = JobRunner(ctx)

    # ============================================================
    # 趨勢 / 列表 / 查詢
    # ============================================================

    @mcp.tool()
    def import_trend_csv(path: str | None = None) -> dict:
        """導入短影音熱度 CSV。"""
        p = path or ctx.config["trend"]["csv_path"]
        n = ctx.db.import_trend_csv(p)
        return {"imported": n, "path": p}

    @mcp.tool()
    def list_trend_top(n: int = 20) -> list[dict]:
        """按熱度返回前 n 條。"""
        return ctx.db.trend_top(n)

    @mcp.tool()
    def list_videos(limit: int = 20) -> list[dict]:
        """列出已攝取視頻。"""
        return ctx.db.list_videos(limit)

    @mcp.tool()
    def get_video(video_id: str) -> dict:
        """視頻元數據 + 源片段統計。"""
        meta = ctx.db.get_video(video_id)
        if not meta:
            return {"error": f"video {video_id} not found"}
        meta["segment_counts"] = ctx.db.segment_counts(video_id)
        meta["triage"] = ctx.db.get_triage(video_id)
        return meta

    @mcp.tool()
    def get_report(run_id: str) -> dict:
        """讀取 Markdown 報告。"""
        row = ctx.db.get_report(run_id)
        return row or {"error": f"report {run_id} not found"}

    @mcp.tool()
    def get_conflicts(run_id: str, only_unresolved: bool = True) -> list[dict]:
        """衝突列表；unresolved 保留雙版本。"""
        only_unresolved = _to_bool(only_unresolved, default=True)
        return ctx.db.list_conflicts(run_id, only_unresolved=only_unresolved)

    # ============================================================
    # 關鍵幀預覽（純函數，不讀視頻）
    # ============================================================

    @mcp.tool()
    def preview_keyframe_selection(
        scene_points: list[float], duration: float, fps: float = 30.0,
        max_window_sec: float = 8.0, min_gap_sec: float = 1.0,
    ) -> list[dict]:
        """預覽右邊界截斷結果（幀級精確，本地完整視頻場景）。"""
        out = select_keyframes(scene_points, duration, fps, max_window_sec, min_gap_sec)
        return [f.__dict__ for f in out]

    @mcp.tool()
    def preview_keyframe_selection_seek(
        scene_points: list[float], duration: float,
        max_window_sec: float = 8.0, min_gap_sec: float = 1.0,
        right_margin_sec: float = 0.4, left_candidates: int = 3,
    ) -> list[dict]:
        """預覽 seek 版的 margin 截斷結果（遠程 seek 場景）。"""
        out = select_keyframes_seek(
            scene_points, duration,
            max_window_sec=max_window_sec, min_gap_sec=min_gap_sec,
            right_margin_sec=right_margin_sec,
            left_candidates=left_candidates,
        )
        return [f.__dict__ for f in out]

    # ============================================================
    # 仲裁 / 成本 / 修正
    # ============================================================

    @mcp.tool()
    def arbitrate_evidence(
        bundle_id: str, video_id: str, time_range: list[float],
        summaries: list[dict],
    ) -> dict:
        """對給定證據執行仲裁。summaries: [{source_type, confidence, quality_flags}]"""
        b = EvidenceBundle(id=bundle_id, video_id=video_id,
                           time_range=(time_range[0], time_range[1]),
                           summary_ids=[s.get("id", "") for s in summaries])
        items = []
        for s in summaries:
            item = dict(s)
            st = item.get("source_type")
            if isinstance(st, str):
                try:
                    item["source_type"] = SourceType(st)
                except ValueError:
                    item["source_type"] = SourceType.KEYFRAME
            items.append(item)
        return arbitrate(b, items).model_dump()

    @mcp.tool()
    def get_cost_summary(daily: bool = True) -> dict:
        """成本與預算餘量。"""
        daily = _to_bool(daily, default=True)
        s = ctx.ledger.summary(daily=daily)
        s["budget_daily_usd"] = ctx.config["cost"]["daily_usd"]
        return s

    @mcp.tool()
    def submit_correction(
        run_id: str, assertion_ref: str, old_value: str,
        new_value: str, user_note: str = "",
    ) -> dict:
        """提交人工修正。"""
        cid = ctx.db.insert_correction(run_id, assertion_ref,
                                       old_value, new_value, user_note)
        return {"correction_id": cid, "ok": True}

    # ============================================================
    # 攝取 / 分析（異步）
    # ============================================================

    @mcp.tool()
    def ingest_video(url: str, platform: str = "youtube") -> dict:
        """攝取元數據 + 字幕。"""
        from app.ingest.pipeline import ingest_url
        return ingest_url(ctx, url, platform)

    @mcp.tool()
    def analyze_video(video_id: str, profile: str = "standard") -> dict:
        """啟動異步分析，返回 job_id。"""
        return {"job_id": runner.submit_analyze(video_id, profile)}

    @mcp.tool()
    def get_job_status(job_id: str) -> dict:
        """輪詢 job。"""
        return ctx.db.get_job(job_id) or {"error": f"job {job_id} not found"}

    # ============================================================
    # 按需讀幀（雙重視角：VLM 描述 + 原始圖片）
    # ============================================================

    @mcp.tool()
    def read_frame_at(video_id: str, timestamp: float,
                      quality: str = "720p",
                      include_image: bool = True) -> list:
        """按需讀單幀，返回 [本地 VLM 描述 + 原始圖片] 雙重視角。

        include_image 參數（支持字符串形式 "true"/"false"）：
          - True（默認）：返回 [TextContent, ImageContent]
          - False：只返回 [TextContent]——適合客戶端處理圖片有 bug 的場景

        無論 include_image 是 True 還是 False，TextContent 裡始終包含
        Qwen3-VL 27B 生成的完整畫面描述 + 提取的斷言。

        - 只下載 timestamp ±2 秒的片段（~200KB），不整片下載
        - 命中 cache/frames/{video_id}/{rounded_ts}_{quality}.jpg 則直接返回
        - quality 可選：240p | 360p | 720p（默認）
        """
        from app.adapters.base import VideoMeta
        from app.keyframes.describe import _KEYFRAME_PROMPT
        from app.summarize.local import _filter_llm_assertions, _parse_llm_json

        # ★ MCP 客戶端可能把 False 序列化為字符串 "False"
        include_image = _to_bool(include_image, default=True)

        video = ctx.db.get_video(video_id)
        if not video:
            return [TextContent(
                type="text",
                text=f"video {video_id} not found",
            )]

        meta = VideoMeta(
            video_id=video_id, platform=video["platform"],
            url=video["url"], title=video["title"],
            duration=float(video["duration"]),
            author=video.get("author", ""),
            description=video.get("description", ""),
        )
        adapter = ctx.adapter_for(video["platform"])
        path = adapter.extract_frame_at(meta, timestamp, quality)

        if not path or not Path(path).exists():
            return [TextContent(
                type="text",
                text=f"frame extraction failed at {timestamp:.1f}s "
                     f"(quality={quality})",
            )]

        # ── 本地 VLM 描述（Qwen3-VL 27B）──────────────────────
        vlm_desc = "(VLM unavailable)"
        vlm_assertions_text = ""
        try:
            prompt = _KEYFRAME_PROMPT.format(ts=timestamp)
            raw_resp = ctx.router.call(
                "keyframe_desc", "mcp_read_frame",
                messages=[{"role": "user", "content": prompt}],
                images=[path],
                max_tokens=1200,
                temperature=0.1,
            )

            if raw_resp and raw_resp.strip():
                data = _parse_llm_json(raw_resp)
                if (data and isinstance(data.get("summary"), str)
                        and data["summary"].strip()):
                    vlm_desc = data["summary"].strip()
                    asserts = data.get("assertions") or []
                    normalized = []
                    for a in asserts:
                        if not isinstance(a, dict) or not a.get("claim"):
                            continue
                        kind = a.get("kind", "other")
                        if kind not in {"number", "color", "name",
                                        "direction", "other"}:
                            kind = "other"
                        normalized.append({
                            "claim": str(a["claim"]).strip(),
                            "kind": kind,
                        })
                    normalized = _filter_llm_assertions(normalized)
                    if normalized:
                        lines = [f"  - [{a['kind']}] {a['claim']}"
                                 for a in normalized[:8]]
                        vlm_assertions_text = "\n".join(lines)
                else:
                    cleaned = raw_resp.strip()
                    if cleaned.startswith("```"):
                        lines = cleaned.splitlines()
                        body = []
                        for ln in lines[1:]:
                            if ln.strip().startswith("```"):
                                break
                            body.append(ln)
                        cleaned = "\n".join(body).strip()
                    vlm_desc = cleaned[:800] if len(cleaned) > 800 else cleaned
                    if not vlm_desc:
                        vlm_desc = "(VLM returned empty)"
        except Exception as e:
            vlm_desc = f"(VLM error: {type(e).__name__}: {str(e)[:200]})"

        size_kb = Path(path).stat().st_size / 1024

        # ── 拼裝 TextContent ─────────────────────────────────
        text_parts = [
            f"Frame at {timestamp:.1f}s ({quality}, {size_kb:.0f} KB)",
            f"video_id={video_id}",
            f"title={video['title'][:80]}",
            "",
            "=== LOCAL VLM DESCRIPTION (Qwen3-VL 27B) ===",
            vlm_desc,
        ]
        if vlm_assertions_text:
            text_parts.append("")
            text_parts.append("VLM-extracted assertions:")
            text_parts.append(vlm_assertions_text)

        if include_image:
            text_parts.extend([
                "",
                "=== RAW IMAGE (attached) ===",
                "If your model supports vision, look at the attached image directly.",
                "",
                "=== Cross-check instructions ===",
                "You now have TWO independent views of the same moment:",
                "  (1) the local VLM description above",
                "  (2) the raw image attached",
                "",
                "If what you see in the image DIFFERS from the VLM description, "
                "report the discrepancy explicitly. This is valuable signal, not an error.",
                "",
                "If you cannot see the image (no vision capability), say "
                "\"I only have the VLM description\" and do not speculate.",
            ])
        else:
            text_parts.extend([
                "",
                "=== NOTE ===",
                "This call returned text only (include_image=false). "
                "The VLM description above is the authoritative view of this frame. "
                "Answer based on the description, do not speculate about visual details "
                "not mentioned in it.",
            ])

        result: list = [TextContent(type="text", text="\n".join(text_parts))]

        if include_image:
            try:
                with open(path, "rb") as f:
                    data_b64 = base64.b64encode(f.read()).decode("ascii")
                result.append(
                    ImageContent(type="image", data=data_b64, mime_type="image/jpeg")
                )
            except Exception as e:
                result.append(TextContent(
                    type="text",
                    text=f"(image read failed: {e})",
                ))

        return result
