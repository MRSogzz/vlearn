"""文本清洗：去標籤、合併空行、去除純音效/純符號標記。"""
from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_MUSIC = re.compile(
    r"^[\[(（【](音樂|Music|掌聲|Applause|笑聲|Laughter)[^\])）】]*[\])）】]$", re.I
)
# 純符號 / 純音符 / 純標點 / 純括號：清洗後只剩這些字符的段直接丟棄
# 注意：必須包含方括號 [] 和圓括號 ()，否則 [♪♪♪] 這類不會被過濾
_SYMBOLS_ONLY = re.compile(r"^[\s♪♫♬♩\-_.·…、,。，!?！？~～\[\]()（）【】{}]+$")


def clean_text(text: str) -> str:
    if not text:
        return ""
    s = _TAG.sub("", text).replace("\u200b", "").replace("\xa0", " ")
    s = _WS.sub(" ", s).strip()
    if _MUSIC.match(s):
        return ""
    if _SYMBOLS_ONLY.match(s):
        return ""
    return s


def dedup_adjacent(segments: list[dict]) -> list[dict]:
    """合併相鄰且文本相同的碎片字幕。"""
    out: list[dict] = []
    for s in segments:
        if out and out[-1]["text"] == s["text"] and abs(out[-1]["end"] - s["start"]) < 0.3:
            out[-1]["end"] = s["end"]
            continue
        out.append(dict(s))
    return out
