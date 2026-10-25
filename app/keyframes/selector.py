"""
關鍵幀歸屬：

- select_keyframes()       幀級精確版（本地完整視頻可用時）
- select_keyframes_seek()  margin 版（seek 場景，±0.4s 精度）
- select_keyframes_dispatch()  統一入口

兩者共用 SelectedFrame 輸出 schema，下游不感知內部實現。
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Literal, Sequence


@dataclass
class FrameScore:
    timestamp: float
    sharpness: float


@dataclass
class SelectedFrame:
    scene_time: float
    chosen_ts: float
    window_start: float
    window_end: float
    degraded: bool = False
    trigger_type: str = "scene_change"   # 便於下游區分


# ---------- 幀級精確版 ----------

def _frame_before(ts: float, fps: float) -> float:
    if ts <= 0:
        return 0.0
    idx = math.ceil(ts * fps) - 1
    return max(idx, 0) / fps


def merge_dense_points(points: Sequence[float], min_gap: float) -> list[float]:
    if not points:
        return []
    merged = [points[0]]
    for t in points[1:]:
        if t - merged[-1] < min_gap:
            continue
        merged.append(t)
    return merged


def select_keyframes(
    scene_points: Sequence[float],
    duration: float,
    fps: float,
    max_window_sec: float,
    min_gap_sec: float,
    frame_scores: dict[float, float] | None = None,
) -> list[SelectedFrame]:
    points = merge_dense_points(sorted(set(scene_points)), min_gap_sec)
    results: list[SelectedFrame] = []
    for i, t in enumerate(points):
        start = t
        if i + 1 < len(points):
            right = _frame_before(points[i + 1], fps)
        else:
            right = min(t + max_window_sec, duration)
        if right <= start:
            right = start
        candidates = [ts for ts in (frame_scores or {}) if start <= ts < right]
        if candidates:
            chosen = max(candidates, key=lambda ts: frame_scores[ts])
            degraded = False
        else:
            chosen = start
            degraded = True
        results.append(SelectedFrame(
            scene_time=t, chosen_ts=chosen,
            window_start=start, window_end=right,
            degraded=degraded, trigger_type="scene_change",
        ))
    return results


# ---------- margin 版（seek 場景） ----------

def select_keyframes_seek(
    scene_points: Sequence[float],
    duration: float,
    max_window_sec: float = 8.0,
    min_gap_sec: float = 1.0,
    right_margin_sec: float = 0.4,
    left_candidates: int = 3,
    long_window_sec: float = 30.0,
    sharpness_fn=None,     # callable(ts) -> float；None 時返回中間點
) -> list[SelectedFrame]:
    """
    在 seek 場景下，用 margin 替代幀級精確。
    
    - 右邊界 = t_{i+1} - right_margin_sec
    - 窗口內候選幀：前 1/3 均勻取 left_candidates 個
    - 窗口 > long_window_sec：只在窗口前 1/3 取樣
    - 無 sharpness_fn 時退化取窗口中點
    """
    points = merge_dense_points(sorted(set(scene_points)), min_gap_sec)
    results: list[SelectedFrame] = []
    for i, t in enumerate(points):
        start = t
        if i + 1 < len(points):
            right = max(start, points[i + 1] - right_margin_sec)
        else:
            right = min(t + max_window_sec, duration)
        if right <= start:
            right = start

        # 有效採樣區間：窗口 > long_window_sec 時只取前 1/3
        if (right - start) > long_window_sec:
            effective_end = start + (right - start) / 3
        else:
            effective_end = right

        if effective_end <= start:
            chosen = start
            degraded = True
        elif left_candidates <= 1:
            chosen = (start + effective_end) / 2
            degraded = False
        else:
            candidates = [
                start + (effective_end - start) * j / (left_candidates - 1)
                for j in range(left_candidates)
            ]
            if sharpness_fn is not None:
                scores = {ts: sharpness_fn(ts) for ts in candidates}
                chosen = max(scores, key=scores.get)
            else:
                chosen = candidates[len(candidates) // 2]
            degraded = False

        results.append(SelectedFrame(
            scene_time=t, chosen_ts=chosen,
            window_start=start, window_end=right,
            degraded=degraded, trigger_type="seek_margin",
        ))
    return results


# ---------- dispatcher ----------

def select_keyframes_dispatch(
    scene_points: Sequence[float],
    duration: float,
    *,
    mode: Literal["frame_exact", "seek"],
    fps: float = 30.0,
    max_window_sec: float = 8.0,
    min_gap_sec: float = 1.0,
    right_margin_sec: float = 0.4,
    frame_scores: dict[float, float] | None = None,
    sharpness_fn=None,
) -> list[SelectedFrame]:
    """
    統一入口：由調用端根據 download_media / 來源可 seek 決定 mode。
    
    - mode="frame_exact": 本地完整視頻，幀級精確（複用現有 select_keyframes）
    - mode="seek":        遠程 seek，margin 化（select_keyframes_seek）
    """
    if mode == "frame_exact":
        return select_keyframes(
            scene_points, duration, fps=fps,
            max_window_sec=max_window_sec, min_gap_sec=min_gap_sec,
            frame_scores=frame_scores,
        )
    return select_keyframes_seek(
        scene_points, duration,
        max_window_sec=max_window_sec, min_gap_sec=min_gap_sec,
        right_margin_sec=right_margin_sec,
        sharpness_fn=sharpness_fn,
    )
