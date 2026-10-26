"""按時間窗口聚類 WindowSummary → EvidenceBundle。

聚類語義：兩個 summary 視為"同一時段的不同證據源"，
需要**雙向**重疊比例都達到閾值：
  - 從 A 的視角看：overlap / duration_a
  - 從 B 的視角看：overlap / duration_b
  - 取兩者的最小值，必須 ≥ overlap_ratio

這避免了"6 秒圖片窗口被 90 秒字幕窗口吞併"的錯誤：
  - 圖片 59-65s vs 字幕 45-135s
  - 圖片視角：6/6 = 100%
  - 字幕視角：6/90 = 6.7%
  - min = 6.7% < 50% → 不合併 ✓
"""
from __future__ import annotations

import uuid


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """兩個時間區間的重疊時長。"""
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return max(0.0, hi - lo)


def _overlap_ratio_min(a: tuple[float, float], b: tuple[float, float]) -> float:
    """雙向重疊比例取最小值。

    - a 視角：overlap / a_dur
    - b 視角：overlap / b_dur
    - 返回 min(...)
    意義：只有"兩個區間都顯著覆蓋對方"才算同一時段。
    """
    ov = _overlap(a, b)
    if ov <= 0:
        return 0.0
    a_dur = max(1e-9, a[1] - a[0])
    b_dur = max(1e-9, b[1] - b[0])
    return min(ov / a_dur, ov / b_dur)


def build_bundles(video_id: str, summaries: list[dict],
                  overlap_ratio: float = 0.5) -> list[dict]:
    """summaries: [{id, time_range, source_type, assertions, summary}]

    overlap_ratio=0.5 表示兩個區間必須互相覆蓋 50% 才合併。
    """
    if not summaries:
        return []
    ordered = sorted(summaries, key=lambda s: s["time_range"][0])
    bundles: list[dict] = []
    for s in ordered:
        s_tr = tuple(s["time_range"])
        placed = False
        for b in bundles:
            b_tr = tuple(b["time_range"])
            if _overlap_ratio_min(s_tr, b_tr) >= overlap_ratio:
                b["summary_ids"].append(s["id"])
                b["time_range"] = (
                    min(b_tr[0], s_tr[0]),
                    max(b_tr[1], s_tr[1]),
                )
                placed = True
                break
        if not placed:
            bundles.append({
                "id": f"bun_{uuid.uuid4().hex[:8]}",
                "video_id": video_id,
                "time_range": s_tr,
                "summary_ids": [s["id"]],
                "status": "pending",
            })
    return bundles
