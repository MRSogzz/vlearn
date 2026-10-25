"""對 suspect/conflict 窗口回溯原始字幕與原圖。"""
from __future__ import annotations
from app.context import AppContext


def backtrace(ctx: AppContext, run_id: str, video_id: str,
              time_range: tuple[float, float], *,
              max_segments: int = 6, max_keyframes: int = 3) -> dict:
    lo, hi = time_range
    subs = [s for s in ctx.db.segments(video_id)
            if s["start"] < hi and s["end"] > lo]
    frames = [f for f in ctx.db.keyframes(video_id)
              if lo <= f["timestamp"] <= hi][:max_keyframes]
    return {
        "time_range": [lo, hi],
        "subtitle_snippets": [{"start": s["start"], "end": s["end"],
                               "text": s["text"], "source_type": s["source_type"],
                               "id": s["id"]} for s in subs[:max_segments]],
        "keyframe_paths": [f["image_path"] for f in frames if f.get("image_path")],
        "keyframe_ts": [f["timestamp"] for f in frames],
    }
