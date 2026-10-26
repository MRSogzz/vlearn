"""固定間隔兜底 + pHash 去重。"""
from __future__ import annotations

import subprocess
from pathlib import Path


def fixed_interval_points(duration: float, interval: float = 90.0,
                          cap: int = 30, per_10min: int = 30) -> list[float]:
    if duration <= 0 or interval <= 0:
        return []
    limit = min(cap, max(1, int(duration / 600 * per_10min) or 1))
    pts, t = [], interval / 2
    while t < duration and len(pts) < limit:
        pts.append(round(t, 3))
        t += interval
    return pts


def extract_frame(video_path: str, ts: float, out_dir: str) -> str | None:
    out = Path(out_dir) / f"frame_{ts:.3f}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-nostats",
           "-ss", f"{ts:.3f}", "-i", video_path,
           "-frames:v", "1", "-q:v", "3", "-y", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception:
        return None
    return str(out) if r.returncode == 0 and out.exists() else None


def phash_dedup(paths: list[str], threshold: int = 6) -> list[str]:
    try:
        import imagehash
        from PIL import Image
    except ImportError:
        return paths
    kept: list[tuple[str, imagehash.ImageHash]] = []
    for p in paths:
        try:
            h = imagehash.phash(Image.open(p))
        except Exception:
            continue
        if all((h - prev) > threshold for _, prev in kept):
            kept.append((p, h))
    return [p for p, _ in kept]
