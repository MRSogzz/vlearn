"""視頻內容分類器：3 幀探針 + metadata + 字幕密度，決定掃描策略與幀預算。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image


SEMANTIC_TRIGGERS = {
    "zh": [
        "如圖所示", "如圖", "這張圖", "看這裡", "看這張", "這個圖表",
        "這個圖", "這裡可以看到", "大家看", "請看",
    ],
    "en": [
        "as you can see", "look at this", "let me show you",
        "this chart", "this graph", "this slide", "this picture",
        "if you look at", "notice the", "here's the",
    ],
}

TITLE_SIGNALS = {
    "interview": ["interview", "conversation", "podcast", "訪談", "對談", "對話"],
    "presentation": ["tutorial", "lecture", "how to", "教學", "教學", "course", "lesson"],
    "editing": ["vlog", "documentary", "trailer", "紀錄片", "紀錄片"],
}

SHORT_VIDEO_SEC = 180.0     # 3 分鐘以下跳過探針
PROBE_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class ClassResult:
    video_class: str            # interview | presentation | mixed | editing | unknown
    confidence: float           # 0.0 - 1.0
    probes_used: int
    signals: dict               # 各信號明細，便於審計


def edge_density(image_path: str) -> float:
    """用 Sobel 邊緣密度近似"文字/圖表密度"（不需要 OCR）。

    返回 0.0-1.0。規則排版 → 高；人臉 → 低。
    """
    try:
        img = Image.open(image_path).convert("L").resize((320, 180))
        arr = np.asarray(img, dtype=float)
        gx = np.abs(np.diff(arr, axis=1))
        gy = np.abs(np.diff(arr, axis=0))
        # 歸一化：邊緣強度 > 30 視為"有邊緣"
        threshold = 30.0
        edges = ((gx > threshold).mean() + (gy > threshold).mean()) / 2
        return float(min(1.0, edges * 3.0))    # 經驗縮放
    except Exception:
        return 0.0


def _title_hint(title: str) -> Optional[str]:
    title_lower = title.lower()
    for cls, keywords in TITLE_SIGNALS.items():
        if any(kw in title_lower for kw in keywords):
            return cls
    return None


def _trigger_density(subtitles: list[dict]) -> float:
    if not subtitles:
        return 0.0
    hits = 0
    for seg in subtitles:
        text_lower = seg.get("text", "").lower()
        if any(t in text_lower for lang in SEMANTIC_TRIGGERS.values() for t in lang):
            hits += 1
    return hits / len(subtitles)


def classify_video(
    meta,
    probes: list[dict],
    subtitles: list[dict],
    adapter=None,
    early_stop: bool = True,
) -> ClassResult:
    """
    三信號分類：
      1. metadata title 關鍵詞
      2. 探針幀邊緣密度（文字/圖表 vs 人臉）
      3. 字幕提示詞密度
    """
    signals: dict = {}

    # 短視頻直接 unknown（走通用策略）
    if meta.duration < SHORT_VIDEO_SEC:
        return ClassResult(video_class="unknown", confidence=0.3,
                            probes_used=len(probes),
                            signals={"reason": "short_video_skip"})

    # 信號 1：title
    title_cls = _title_hint(meta.title)
    signals["title_hint"] = title_cls

    # 信號 2：探針幀邊緣密度
    text_densities = [edge_density(p["path"]) for p in probes if p.get("path")]
    avg_text = float(np.mean(text_densities)) if text_densities else 0.0
    signals["avg_text_density"] = avg_text

    # 早停判斷：前 2 幀是否有明確結論
    if early_stop and len(text_densities) == 2:
        if all(d > 0.20 for d in text_densities):
            signals["early_stop"] = "both_text_heavy"
            return ClassResult("presentation", 0.85, 2, signals)
        if all(d < 0.05 for d in text_densities):
            signals["early_stop"] = "both_text_sparse"
            # 可能是訪談，但要結合字幕確認
            pass

    # 信號 3：字幕提示詞密度
    trigger_density = _trigger_density(subtitles)
    signals["trigger_density"] = trigger_density

    # 決策
    if trigger_density > 0.05:
        return ClassResult("presentation", 0.90, len(probes), signals)
    if avg_text > 0.20:
        return ClassResult("presentation", 0.85, len(probes), signals)
    if title_cls:
        return ClassResult(title_cls, 0.70, len(probes), signals)
    if avg_text < 0.05 and trigger_density < 0.01:
        # 畫面稀疏 + 無提示詞 → 訪談或純人像
        return ClassResult("interview", 0.65, len(probes), signals)

    # 無法判定
    return ClassResult("unknown", 0.30, len(probes), signals)


def budget_for_class(video_class: str, has_subtitles: bool) -> dict:
    """根據分類返回掃描策略與幀預算。"""
    if video_class == "interview":
        # 訪談：無字幕時提高到 6-8 幀
        if has_subtitles:
            return {"scan": False, "budget": 3, "min_interval_sec": None}
        return {"scan": False, "budget": 7, "min_interval_sec": None}
    if video_class == "presentation":
        return {"scan": True, "budget": 40, "min_interval_sec": 30.0}
    if video_class == "editing":
        return {"scan": True, "budget": 20, "min_interval_sec": 45.0}
    if video_class == "mixed":
        return {"scan": True, "budget": 20, "min_interval_sec": 45.0}
    # unknown
    return {"scan": True, "budget": 10, "min_interval_sec": 60.0}
