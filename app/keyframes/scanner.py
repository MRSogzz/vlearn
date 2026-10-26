"""由粗到細掃描：240p 每 N 秒 seek → dHash 對比 → 差異大區間遞歸細分。"""
from __future__ import annotations

import numpy as np
from PIL import Image


def dhash(image_path: str, size: int = 8) -> str | None:
    """返回 16 進制 dhash 字符串（64 bit）。"""
    try:
        img = Image.open(image_path).convert("L").resize((size + 1, size))
        arr = np.asarray(img, dtype=int)
        diff = arr[:, 1:] > arr[:, :-1]
        bits = diff.flatten()
        hex_str = "".join("1" if b else "0" for b in bits)
        return f"{int(hex_str, 2):016x}"
    except Exception:
        return None


def hamming(hex_a: str, hex_b: str) -> int:
    try:
        return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")
    except Exception:
        return 999


def scan_candidates(
    meta,
    adapter,
    *,
    interval_sec: float = 45.0,
    threshold: int = 12,
    max_seeks: int = 60,
) -> list[float]:
    """由粗到細：均勻 seek，dHash 差異大的區間收集為候選。

    返回候選時間點列表（秒）。
    """
    if meta.duration <= 0:
        return []

    n_seeks = min(max_seeks, max(3, int(meta.duration / interval_sec)))
    step = meta.duration / n_seeks
    timestamps = [step * (i + 0.5) for i in range(n_seeks)]

    prev_hash: str | None = None
    candidates: list[float] = []
    for ts in timestamps:
        frame = adapter.extract_frame_at(meta, ts, "240p")
        if not frame:
            continue
        h = dhash(frame)
        if not h:
            continue
        if prev_hash is None:
            candidates.append(ts)    # 首個採樣點作為起點
        elif hamming(prev_hash, h) > threshold:
            candidates.append(ts)
        prev_hash = h
    return candidates
