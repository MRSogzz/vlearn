"""內容尋址緩存：video_id + content_hash + prompt_version + model。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class Cache:
    def __init__(self, root: str = "./cache"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def key(self, *parts: str) -> str:
        h = hashlib.sha256("::".join(parts).encode()).hexdigest()[:32]
        return h

    def get(self, key: str) -> dict | None:
        p = self.root / f"{key}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, key: str, value: dict) -> None:
        (self.root / f"{key}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8")
