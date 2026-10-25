"""圖片 pipeline：探針 → 分類 → 掃描 → 抽幀 → 描述 → 斷言。

獨立於字幕 pipeline，輸出 summaries 列表，與字幕 summaries 在
EvidenceBundle 層合流。

關鍵：
- 圖片斷言的時間範圍是 chosen_ts ± 3 秒，不沿用窗口邊界
- frames_meta 記錄每張實際抽到的幀（id / timestamp / trigger_type / image_path），
  供 orchestrator 回寫 keyframes 表，保證回溯鏈完整
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.context import AppContext
from app.keyframes.classifier import (
    ClassResult, budget_for_class, classify_video, edge_density,
)
from app.keyframes.describe import describe_frame
from app.keyframes.scanner import scan_candidates
from app.keyframes.selector import select_keyframes_dispatch
from app.adapters.base import VideoMeta


@dataclass
class ImagePipelineResult:
    summaries: list[dict]
    class_result: ClassResult
    frames_used: int
    cost_usd: float
    frames_meta: list[dict] = field(default_factory=list)


def run_image_pipeline(
    ctx: AppContext,
    run_id: str,
    video_id: str,
    meta: VideoMeta,
    subtitles: list[dict],
    _progress=None,
) -> ImagePipelineResult:
    """完整圖片 pipeline，獨立運行。"""
    adapter = ctx.adapter_for(meta.platform)

    # 1) 探針
    if _progress:
        _progress("probe", 0.1)
    probes = adapter.probe_frames(meta, n=3, early_stop=True)

    # 2) 分類（早停時按需第 3 幀）
    class_result = classify_video(meta, probes, subtitles, adapter)
    if (class_result.probes_used == 2
            and class_result.confidence < 0.6
            and len(probes) == 2):
        p3 = adapter.extract_frame_at(meta, meta.duration * 0.80, "240p")
        if p3:
            probes.append({"timestamp": meta.duration * 0.80,
                           "path": p3, "quality": "240p"})
            class_result = classify_video(meta, probes, subtitles, adapter)

    budget = budget_for_class(class_result.video_class, bool(subtitles))

    # 3) 掃描（由粗到細）+ 關鍵幀選擇
    if _progress:
        _progress("scan", 0.3)

    if budget["scan"]:
        candidates = scan_candidates(
            meta, adapter,
            interval_sec=budget["min_interval_sec"] or 45.0,
        )
    else:
        candidates = []

    # 保底幀：按分類決定
    if class_result.video_class == "interview":
        base_n = budget["budget"]
        positions = ([0.03, 0.33, 0.66] if base_n <= 3
                     else [0.03, 0.20, 0.40, 0.60, 0.80, 0.95])
        fallback_ts = [meta.duration * p for p in positions[:base_n]]
        candidates.extend(fallback_ts)

    # 用 select_keyframes_dispatch 做窗口歸屬
    scene_points = sorted(set(candidates + [c for c in candidates if c > 0]))
    selected = select_keyframes_dispatch(
        scene_points, meta.duration,
        mode="seek",
        max_window_sec=ctx.config["keyframes"]["max_window_sec"],
        min_gap_sec=ctx.config["keyframes"]["min_gap_sec"],
        right_margin_sec=0.4,
    )[:budget["budget"]]

    # 4) 精取 + 描述
    if _progress:
        _progress("describe", 0.5)

    summaries: list[dict] = []
    frames_meta: list[dict] = []
    frames_used = 0

    for f in selected:
        frame_path = adapter.extract_frame_at(meta, f.chosen_ts, "720p")
        if not frame_path:
            continue
        frames_used += 1
        frame_ref = f"kf_{uuid.uuid4().hex[:8]}"

        # ★ 先記錄幀元數據（即使 describe 失敗也要留圖，保證可回溯）
        frames_meta.append({
            "id": frame_ref,
            "timestamp": f.chosen_ts,
            "trigger_type": f.trigger_type,
            "image_path": frame_path,
        })

        # 圖片斷言只覆蓋 chosen_ts ± 3 秒，不用窗口邊界
        image_tr = (
            max(0.0, f.chosen_ts - 3.0),
            min(meta.duration, f.chosen_ts + 3.0),
        )
        result = describe_frame(
            ctx, run_id, frame_path,
            timestamp=f.chosen_ts,
            time_range=image_tr,
            frame_ref=frame_ref,
        )
        if not result or not result.get("summary"):
            continue

        summaries.append({
            "id": f"ws_kf_{uuid.uuid4().hex[:8]}",
            "video_id": video_id,
            "time_range": image_tr,
            "source_type": "keyframe_vlm",
            "summary": result["summary"],
            "assertions": result.get("assertions", []),
            "raw_ref": frame_ref,
            "trigger_type": f.trigger_type,
            "frame_timestamp": f.chosen_ts,
        })

    if _progress:
        _progress("describe_done", 0.9)

    return ImagePipelineResult(
        summaries=summaries,
        class_result=class_result,
        frames_used=frames_used,
        cost_usd=ctx.ledger.run_spend(run_id),
        frames_meta=frames_meta,
    )
