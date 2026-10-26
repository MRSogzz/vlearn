"""摄取管线：元数据 + 字幕 + 清洗 + 统一时间轴。"""
from __future__ import annotations

import uuid

from app.context import AppContext


def ingest_url(ctx: AppContext, url: str, platform: str = "youtube") -> dict:
    adapter = ctx.adapter_for(platform)
    meta = adapter.get_metadata(url)
    ctx.db.upsert_video(meta.__dict__)

    from app.preprocess.clean import clean_text, dedup_adjacent
    from app.preprocess.timeline import merge_close, unify_timeline

    raw = adapter.get_subtitles(meta)
    cleaned = []
    for s in raw:
        t = clean_text(s.get("text", ""))
        if not t:
            continue
        cleaned.append({
            "id": f"sub_{uuid.uuid4().hex[:8]}",
            "video_id": meta.video_id,
            "source_type": s.get("source_type", "official_subtitle"),
            "start": float(s["start"]), "end": float(s["end"]),
            "text": t, "confidence": 1.0, "reliability": 5,
            "quality_flags": [],
        })
    cleaned = dedup_adjacent(cleaned)
    cleaned = merge_close(unify_timeline(cleaned), max_gap=0.5)
    ctx.db.insert_segments(cleaned)

    return {
        "video_id": meta.video_id, "title": meta.title,
        "duration": meta.duration, "subtitle_segments": len(cleaned),
    }