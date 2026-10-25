"""報告渲染：把 final fusion 結果落成 Markdown 文件。"""
from __future__ import annotations
from pathlib import Path


def render_report(final_md: str, out_dir: str, run_id: str) -> str:
    p = Path(out_dir) / f"{run_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(final_md, encoding="utf-8")
    return str(p)


def apply_corrections(md: str, corrections: list[dict]) -> str:
    """應用修正到 Markdown（字符串替換）。

    限制：如果 old_value 是常見詞的一部分（如 "red" 是 "hundred" 的一部分），
    會誤替換。MVP 階段接受這個限制，後續可改為基於 ref 的精準替換。

    corrections: [{old_value, new_value, target_ref, user_note}, ...]
    """
    for c in corrections:
        old = (c.get("old_value") or "").strip()
        new = (c.get("new_value") or "").strip()
        if not old:
            continue
        md = md.replace(old, new)
    return md
