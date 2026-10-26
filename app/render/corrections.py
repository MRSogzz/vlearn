"""人工修正應用到報告。

流程：
1. 從 corrections 表讀出該 run 的所有修正
2. 對報告 Markdown 做字符串替換
3. 寫回 report_md（保留 assertions / unresolved 的原始結構，不破壞 JSON）
"""
from __future__ import annotations

import json
from pathlib import Path

from app.context import AppContext
from app.render.markdown import apply_corrections, render_report


def _safe_json_load(raw: str | list | None, default: list) -> list:
    """兼容兩種存法：
    - 舊格式：JSON 字符串 '"[{...}]"'
    - 已被破壞的嵌套格式：'["[{...}]"]'
    - 已是 list
    """
    if raw is None:
        return default
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return default
    # 若解析出來是字符串（被嵌套過），再解析一次
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return default
    if isinstance(parsed, list):
        # 若第一個元素是字符串但看起來像 JSON（舊 bug 遺留），嘗試展開
        if parsed and isinstance(parsed[0], str) and parsed[0].strip().startswith(("[", "{")):
            try:
                inner = json.loads(parsed[0])
                if isinstance(inner, list):
                    return inner
            except json.JSONDecodeError:
                pass
        return parsed
    return default


def re_render_with_corrections(ctx: AppContext, run_id: str) -> str:
    """應用該 run 的所有人工修正，重新渲染報告。"""
    row = ctx.db.get_report(run_id)
    if not row:
        raise ValueError(f"report {run_id} not found")

    corrections = ctx.db.corrections(run_id)
    out_dir = ctx.config["output"]["output_dir"]

    if not corrections:
        path = Path(out_dir) / f"{run_id}.md"
        if path.exists():
            return str(path)
        # 沒有修正也沒有文件時，用原 report_md 重新落盤
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(row["report_md"], encoding="utf-8")
        return str(path)

    md = apply_corrections(row["report_md"], corrections)
    path = render_report(md, out_dir, run_id)

    assertions = _safe_json_load(row.get("assertions"), [])
    unresolved = _safe_json_load(row.get("unresolved"), [])
    ctx.db.save_report(run_id, row["video_id"], md, assertions, unresolved)

    return path
