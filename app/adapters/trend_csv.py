"""TrendSource：從 CSV 讀取熱度清單。"""
from __future__ import annotations
from pathlib import Path


class TrendCsvSource:
    name = "trend_csv"
    capabilities = {"import"}

    def read(self, path: str) -> list[dict]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        import csv
        rows = []
        with p.open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "id": r.get("id") or r.get("video_id") or r.get("url", ""),
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "heat": float(r.get("heat", 0) or 0),
                    "source": r.get("source", "csv"),
                })
        return rows
