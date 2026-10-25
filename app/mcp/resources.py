from __future__ import annotations
import json

from mcp.server.mcpserver import MCPServer

from app.context import AppContext


def register(mcp: MCPServer, ctx: AppContext) -> None:

    @mcp.resource("vlearn://videos/{video_id}")
    def video_meta(video_id: str) -> str:
        """影片元數據 JSON。"""
        return json.dumps(ctx.db.get_video(video_id) or {}, ensure_ascii=False)

    @mcp.resource("vlearn://reports/{run_id}")
    def report_md(run_id: str) -> str:
        """報告 Markdown 全文。"""
        row = ctx.db.get_report(run_id)
        return row["report_md"] if row else ""
