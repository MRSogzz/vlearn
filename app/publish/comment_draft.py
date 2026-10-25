"""公開評論草稿：MVP 默認關閉，永不自動發佈。"""
from __future__ import annotations
from app.context import AppContext


def draft_comment(ctx: AppContext, run_id: str) -> dict:
    if not ctx.config["publish"]["comment_enabled"]:
        return {"enabled": False, "reason": "config.publish.comment_enabled=false"}
    row = ctx.db.get_report(run_id)
    if not row:
        return {"enabled": False, "reason": "report not found"}
    # 只返回草稿，實際發佈必須人工操作
    return {
        "enabled": True,
        "draft": f"[草稿，未發佈] 視頻要點：\n{row['report_md'][:400]}…",
        "requires_human_approval": True,
    }
