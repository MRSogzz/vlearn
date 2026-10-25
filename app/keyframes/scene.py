"""FFmpeg scdet 場景檢測。"""
from __future__ import annotations
import re
import subprocess


def detect_scene_points(video_path: str, threshold: float = 0.35) -> list[float]:
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_path, "-an",
           "-vf", f"select='gt(scene,{threshold})',showinfo",
           "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    return [float(x) for x in re.findall(r"pts_time:\s*([0-9.]+)", p.stderr)]


def measure_sharpness(video_path: str, ts: float) -> float:
    """簡化：截一幀，用 Laplacian 方差近似清晰度。"""
    try:
        import subprocess as sp
        import numpy as np
        from PIL import Image
        import io
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{ts:.3f}",
               "-i", video_path, "-frames:v", "1", "-f", "image2pipe",
               "-vcodec", "png", "-"]
        p = sp.run(cmd, capture_output=True, timeout=30)
        if p.returncode != 0:
            return 0.0
        img = Image.open(io.BytesIO(p.stdout)).convert("L")
        arr = np.asarray(img, dtype=float)
        lap = (arr[:-2, 1:-1] + arr[2:, 1:-1] + arr[1:-1, :-2]
               + arr[1:-1, 2:] - 4 * arr[1:-1, 1:-1])
        return float(lap.var())
    except Exception:
        return 0.0
