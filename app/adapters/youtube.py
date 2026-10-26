"""YouTube：extract_info 提字幕 + 三檔降級抽幀 + 3 幀探針。"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yt_dlp

from app.adapters.base import PlatformAdapter, VideoMeta


class YouTubeAdapter(PlatformAdapter):
    name = "youtube"
    capabilities = {"metadata", "subtitles", "media"}

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    # ---------- 元數據 ----------
    def get_metadata(self, url: str) -> VideoMeta:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return VideoMeta(
            video_id=info["id"], platform="youtube", url=url,
            title=info.get("title", ""), duration=float(info.get("duration", 0)),
            author=info.get("uploader", ""), description=info.get("description", ""),
        )

    # ---------- 字幕 ----------
    def get_subtitles(self, meta: VideoMeta) -> list[dict]:
        subs = self._fetch_via_urls(meta)
        if subs:
            return subs
        return self._fetch_via_download(meta)

    def _fetch_via_urls(self, meta: VideoMeta) -> list[dict]:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(meta.url, download=False)
        except Exception:
            return []
        for pool in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
            for lang in ("en", "en-US", "en-orig", "zh-Hans"):
                if lang not in pool:
                    continue
                entries = pool[lang]
                url = None
                for e in entries:
                    if e.get("ext") == "json3":
                        url = e["url"]
                        break
                if not url and entries:
                    url = entries[0]["url"]
                if not url:
                    continue
                text = self._http_get(url)
                if not text:
                    continue
                parsed = self._parse_subtitle_text(text, lang)
                if parsed:
                    return parsed
        return []

    def _http_get(self, url: str) -> str | None:
        try:
            r = httpx.get(url, timeout=30,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; vlearn/0.1)"})
            if r.status_code == 200 and r.text.strip():
                return r.text
        except Exception:
            pass
        return None

    def _parse_subtitle_text(self, text: str, lang: str) -> list[dict]:
        s = text.lstrip()
        if s.startswith("{"):
            try:
                return self._parse_json3(json.loads(text), lang)
            except Exception:
                return []
        if s.startswith("WEBVTT") or "WEBVTT" in text[:100]:
            return self._parse_vtt(text, lang)
        return []

    def _parse_json3(self, data: dict, lang: str) -> list[dict]:
        out = []
        for ev in data.get("events", []):
            segs = ev.get("segs")
            if not segs:
                continue
            t = "".join(s.get("utf8", "") for s in segs).strip()
            if not t:
                continue
            start = ev.get("tStartMs", 0) / 1000.0
            dur = ev.get("dDurationMs", 0) / 1000.0
            out.append({"start": start, "end": start + dur, "text": t,
                        "source_type": "official_subtitle", "lang": lang})
        return out

    def _parse_vtt(self, text: str, lang: str) -> list[dict]:
        out = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if "-->" in line:
                try:
                    left, right = line.split("-->")
                    start = self._vtt_ts(left.strip())
                    end = self._vtt_ts(right.strip().split()[0])
                except Exception:
                    i += 1
                    continue
                i += 1
                parts = []
                while i < len(lines) and lines[i].strip():
                    parts.append(lines[i].strip())
                    i += 1
                t = " ".join(parts).strip()
                if t:
                    out.append({"start": start, "end": end, "text": t,
                                "source_type": "official_subtitle", "lang": lang})
            i += 1
        return out

    @staticmethod
    def _vtt_ts(s: str) -> float:
        parts = s.split(":")
        if len(parts) == 3:
            h, m, sec = parts
            return int(h) * 3600 + int(m) * 60 + float(sec)
        if len(parts) == 2:
            m, sec = parts
            return int(m) * 60 + float(sec)
        return float(s)

    def _fetch_via_download(self, meta: VideoMeta) -> list[dict]:
        tmp = Path(f"./cache/subs/{meta.video_id}")
        tmp.mkdir(parents=True, exist_ok=True)
        opts = {
            "quiet": True, "skip_download": True,
            "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "json3",
            "outtmpl": str(tmp / "%(id)s.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([meta.url])
        except Exception:
            return []
        files = list(tmp.glob("*.json3"))
        if not files:
            return []
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
        except Exception:
            return []
        return self._parse_json3(data, "en")

    # ---------- 完整下載（可選，用於場景檢測） ----------
    def download_media(self, meta: VideoMeta) -> str | None:
        if not self.cfg.get("download_media"):
            return None
        out_dir = Path("./cache/media")
        out_dir.mkdir(parents=True, exist_ok=True)
        tmpl = str(out_dir / f"{meta.video_id}.%(ext)s")
        opts = {
            "quiet": True,
            "format": "worst[ext=mp4]/worst",
            "outtmpl": tmpl,
            "noplaylist": True,
            "remote_components": ["ejs:github"],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([meta.url])
        except Exception:
            return None
        for p in out_dir.glob(f"{meta.video_id}.*"):
            return str(p)
        return None

    # ---------- 三檔降級抽幀 ----------

    def extract_frame_at(self, meta: VideoMeta, timestamp: float,
                         quality: str = "720p",
                         window: float = 2.0) -> str | None:
        """三檔降級：片段下載 → ffmpeg URL → None。

        磁盤佔用：~200KB/幀（片段下載）或 0（URL 直取，但可能偏 2s）。
        緩存：cache/frames/{video_id}/{rounded_ts}_{quality}.jpg
        """
        rounded_ts = round(timestamp)
        frame_dir = Path("./cache/frames") / meta.video_id
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_path = frame_dir / f"{rounded_ts}_{quality}.jpg"
        if frame_path.exists() and frame_path.stat().st_size > 0:
            return str(frame_path)

        fmt = self._quality_to_format(quality)

        # 檔 1：片段下載
        frame = self._download_section_and_extract(meta, timestamp, frame_path, window, fmt)
        if frame:
            return frame

        # 檔 2：ffmpeg 直吃 URL
        return self._ffmpeg_url_seek(meta, timestamp, frame_path, fmt)

    @staticmethod
    def _quality_to_format(quality: str) -> str:
        if quality == "240p":
            return "worst[height<=240]/worst"
        if quality == "360p":
            return "worst[height<=360]/worst"
        if quality == "720p":
            return "best[height<=720]/best"
        return "best[height<=720]/best"

    def _download_section_and_extract(
        self, meta: VideoMeta, timestamp: float,
        frame_path: Path, window: float, fmt: str,
    ) -> str | None:
        tmp = Path("./cache/tmp")
        tmp.mkdir(parents=True, exist_ok=True)
        stem = f"{meta.video_id}_{timestamp:.3f}"
        start = max(0, timestamp - window)
        end = timestamp + window
        opts = {
            "quiet": True,
            "format": fmt,
            "outtmpl": str(tmp / f"{stem}.%(ext)s"),
            "download_ranges": yt_dlp.utils.download_range_func(None, [(start, end)]),
            "force_keyframes_at_cuts": True,
            "remote_components": ["ejs:github"],
        }
        actual: Path | None = None
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([meta.url])
            files = list(tmp.glob(f"{stem}.*"))
            if not files:
                return None
            actual = files[0]
        except Exception:
            return None

        # 抽幀：片段起點 = timestamp - window，取相對位置 window
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostats",
                 "-ss", f"{window:.3f}",
                 "-i", str(actual),
                 "-frames:v", "1", "-q:v", "3", "-y", str(frame_path)],
                capture_output=True, timeout=60,
            )
        finally:
            try:
                actual.unlink()
            except Exception:
                pass

        return str(frame_path) if r.returncode == 0 and frame_path.exists() else None

    def _ffmpeg_url_seek(
        self, meta: VideoMeta, timestamp: float,
        frame_path: Path, fmt: str,
    ) -> str | None:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                                    "format": fmt,
                                    "remote_components": ["ejs:github"]}) as ydl:
                info = ydl.extract_info(meta.url, download=False)
                url = info.get("url") or (
                    info.get("formats", [{}])[-1].get("url") if info.get("formats") else None
                )
            if not url:
                return None
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostats",
                 "-ss", f"{timestamp:.3f}",
                 "-i", url,
                 "-frames:v", "1", "-q:v", "3", "-y", str(frame_path)],
                capture_output=True, timeout=120,
            )
            return str(frame_path) if r.returncode == 0 and frame_path.exists() else None
        except Exception:
            return None

    # ---------- 探針：3 幀 + 早停 + 並行 ----------

    def probe_frames(self, meta: VideoMeta,
                     n: int = 3,
                     early_stop: bool = True) -> list[dict]:
        """探針幀：20% / 50% / 80% 位置，前 2 幀同結論則跳過第 3 幀。

        返回 [{timestamp, path, quality}]。並行取幀。
        """
        if meta.duration <= 0:
            return []
        # 短視頻跳過探針（< 3 分鐘由調用方判斷，這裡只返回位置）
        positions = [0.20, 0.50, 0.80][:n]
        timestamps = [meta.duration * p for p in positions]

        # 並行取前 2 幀
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.extract_frame_at, meta, ts, "240p")
                       for ts in timestamps[:2]]
            results = [f.result() for f in futures]

        frames = [
            {"timestamp": ts, "path": p, "quality": "240p"}
            for ts, p in zip(timestamps[:2], results, strict=False) if p
        ]

        # 早停判斷由 classifier 決定；這裡只取第 3 幀如果前 2 幀都有
        if n >= 3 and len(frames) == 2 and not early_stop:
            p3 = self.extract_frame_at(meta, timestamps[2], "240p")
            if p3:
                frames.append({"timestamp": timestamps[2], "path": p3, "quality": "240p"})
        elif n >= 3 and len(frames) == 2:
            # early_stop=True 時，交給 classifier 決定是否需要第 3 幀
            # 這裡只取前 2 幀，第 3 幀由 classifier 按需請求
            pass

        return frames
