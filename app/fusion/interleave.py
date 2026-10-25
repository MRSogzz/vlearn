"""多源交錯序列：按時間排序，交錯不同源斷言。"""
from __future__ import annotations


def interleave(video: dict, bundles: list[dict],
               summaries_by_id: dict[str, dict],
               conflicts: list[dict]) -> dict:
    rows = []
    for b in bundles:
        lo, hi = b["time_range"]
        for sid in b["summary_ids"]:
            s = summaries_by_id.get(sid)
            if not s:
                continue
            for a in s.get("assertions", []):
                rows.append({
                    "time": a.get("time_range", [lo, hi])[0],
                    "bundle": b["id"],
                    "source": a.get("source_type", s.get("source_type")),
                    "claim": a["claim"],
                    "kind": a["kind"],
                    "ref": a.get("ref", ""),
                })
    rows.sort(key=lambda r: r["time"])
    return {"video": video, "timeline": rows,
            "bundles": bundles, "conflicts": conflicts}
