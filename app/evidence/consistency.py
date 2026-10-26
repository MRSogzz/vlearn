"""一致性校驗：同一證據束內不同源斷言是否矛盾。

關鍵原則：
- 顏色語義歸一化（"red"/"紅"/"深紅色帷幕" 視為同一顏色）
- 數字差異 > 20% 才算 suspect
- 方向互斥才算衝突
"""
from __future__ import annotations

import re
from typing import Literal

Verdict = Literal["consistent", "suspect", "conflict", "pending"]


# 顏色歸一化表：核心色 → 別名列表
_COLOR_ALIASES = {
    "red": ["red", "紅", "紅", "dark red", "深紅", "鮮紅", "鮮紅", "crimson", "scarlet"],
    "blue": ["blue", "藍", "藍", "dark blue", "深藍", "light blue", "淺藍", "navy", "cyan"],
    "green": ["green", "綠", "綠", "深綠", "淺綠", "emerald", "olive"],
    "yellow": ["yellow", "黃", "黃", "金黃", "金黃", "gold"],
    "orange": ["orange", "橙", "橘", "橙色", "橘色"],
    "purple": ["purple", "紫", "深紫", "violet", "magenta"],
    "black": ["black", "黑", "黑色", "深黑"],
    "white": ["white", "白", "白色", "雪白"],
    "gray": ["gray", "grey", "灰", "灰色", "銀灰"],
    "pink": ["pink", "粉", "粉紅", "粉紅", "rose"],
    "brown": ["brown", "棕", "褐", "深棕", "咖啡"],
}


def _normalize_color(claim: str) -> str | None:
    """把任意顏色描述歸一化到核心色；無顏色匹配返回 None。"""
    claim_lower = claim.lower()
    for core, aliases in _COLOR_ALIASES.items():
        for alias in aliases:
            if alias in claim_lower:
                return core
    return None


def _normalize_number(claim: str) -> float | None:
    """從 claim 裡抽出第一個數值；帶單位換算；純描述返回 None。"""
    m = re.search(r"-?\d+(?:[.,]\d+)?", claim)
    if not m:
        return None
    try:
        v = float(m.group().replace(",", ""))
    except ValueError:
        return None
    claim_lower = claim.lower()
    if "萬" in claim or "萬" in claim:
        v *= 10_000
    if "億" in claim or "億" in claim:
        v *= 100_000_000
    if "million" in claim_lower:
        v *= 1_000_000
    if "billion" in claim_lower:
        v *= 1_000_000_000
    if "thousand" in claim_lower:
        v *= 1_000
    return v


def check_bundle(bundle: dict, summaries_by_id: dict[str, dict]) -> Verdict:
    members = [summaries_by_id[sid] for sid in bundle["summary_ids"]
               if sid in summaries_by_id]
    if len(members) < 2:
        return "consistent"

    # 收集斷言，按 kind 分組
    by_kind: dict[str, list[tuple[str, str, str]]] = {}
    for m in members:
        src = m.get("source_type", "official_subtitle")
        for a in m.get("assertions", []):
            by_kind.setdefault(a["kind"], []).append(
                (src, a["claim"], a.get("ref", ""))
            )

    # ---------- 顏色衝突：歸一化後再比 ----------
    normalized_colors: set[str] = set()
    for _, claim, _ in by_kind.get("color", []):
        c = _normalize_color(claim)
        if c:
            normalized_colors.add(c)
    if len(normalized_colors) >= 2:
        return "conflict"

    # ---------- 方向衝突：直接比 ----------
    dirs = {a[1].lower() for a in by_kind.get("direction", [])}
    if len(dirs) >= 2:
        return "conflict"

    # ---------- 數字差異 > 20% → suspect ----------
    nums = []
    for _, claim, _ in by_kind.get("number", []):
        v = _normalize_number(claim)
        if v is not None and v > 0:
            nums.append(v)
    if len(nums) >= 2:
        lo, hi = min(nums), max(nums)
        if lo > 0 and hi / lo > 1.2:
            return "suspect"

    return "consistent"
