"""統一時間軸：合併/排序、按 min_gap 合併碎片。"""
from __future__ import annotations


def unify_timeline(segments: list[dict]) -> list[dict]:
    return sorted(segments, key=lambda s: (s["start"], s["end"]))


def merge_close(segments: list[dict], max_gap: float = 0.5) -> list[dict]:
    if not segments:
        return []
    out = [dict(segments[0])]
    for s in segments[1:]:
        if s["start"] - out[-1]["end"] <= max_gap:
            out[-1]["end"] = max(out[-1]["end"], s["end"])
            out[-1]["text"] = (out[-1]["text"] + " " + s["text"]).strip()
        else:
            out.append(dict(s))
    return out
