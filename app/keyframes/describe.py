"""VLM 描述關鍵幀 → 斷言。"""
from __future__ import annotations

from app.context import AppContext
from app.summarize.local import _filter_llm_assertions, _parse_llm_json

_KEYFRAME_PROMPT = (
    "這是一段視頻在 {ts:.1f}s 處的關鍵幀。"
    "請描述畫面中可見的具體內容，並抽取 2-5 條斷言。"
    "斷言必須描述畫面中可驗證的視覺事實："
    "具體的顏色、文字、數字、人物、物體、場景結構、方向關係。"
    "即使是場景描述（如'穿藍色襯衫的男人'、'紅色帷幕背景'），也算斷言。"
    "禁止抽象詞（smart/important 等）。"
    "只輸出 JSON，不要 markdown 代碼塊："
    '{{"summary": "一句話描述", "assertions": ['
    '{{"claim": "穿深藍色襯衫的男人", "kind": "color"}}, '
    '{{"claim": "深紅色帷幕", "kind": "color"}}]}}'
)


def describe_frame(
    ctx: AppContext,
    run_id: str,
    image_path: str,
    timestamp: float,
    time_range: tuple[float, float],
    frame_ref: str,
) -> dict | None:
    """返回 {summary, assertions}；不可用時返回 None。"""
    if not ctx.router.available("keyframe_desc"):
        return None

    prompt = _KEYFRAME_PROMPT.format(ts=timestamp)
    resp = ctx.router.call(
        "keyframe_desc", run_id,
        messages=[{"role": "user", "content": prompt}],
        images=[image_path],
        max_tokens=1200,          # 600 → 1200：容納 5 條斷言的完整 JSON
        temperature=0.1,
    )
    if not resp:
        return None

    data = _parse_llm_json(resp)
    if not data or not isinstance(data.get("summary"), str):
        return None

    raw_assertions = data.get("assertions") or []
    normalized: list[dict] = []
    for a in raw_assertions:
        if not isinstance(a, dict) or not a.get("claim"):
            continue
        kind = a.get("kind", "other")
        if kind not in {"number", "color", "name", "direction", "other"}:
            kind = "other"
        normalized.append({
            "claim": str(a["claim"]).strip(),
            "kind": kind,
            "ref": frame_ref,
            "source_type": "keyframe_vlm",
            "time_range": list(time_range),
        })
    normalized = _filter_llm_assertions(normalized)

    return {
        "summary": data["summary"].strip(),
        "assertions": normalized,
    }
