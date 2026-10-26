from __future__ import annotations

import logging
import os
import sys

# mcp 2.x：FastMCP → MCPServer，模塊 mcp.server.fastmcp → mcp.server.mcpserver
from mcp.server.mcpserver import MCPServer

from app.context import AppContext
from app.mcp import prompts, resources, tools

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_server(config_path: str | None = None) -> MCPServer:
    config_path = config_path or os.environ.get("VLEARN_CONFIG", "config/default.yaml")
    ctx = AppContext.from_config(config_path)

    mcp = MCPServer(
        name="vlearn",
        instructions=(
            "vlearn 是本地影片學習分析工具。推薦流程：\n"
            "ingest_video(url) → analyze_video(video_id) → "
            "get_job_status(job_id) 輪詢(5s) → get_report(run_id)。\n"
            "衝突用 get_conflicts；修正用 submit_correction。\n"
            "公開評論默認關閉，本服務不會自動發佈。"
        ),
    )
    tools.register(mcp, ctx)
    resources.register(mcp, ctx)
    prompts.register(mcp)
    return mcp


def main() -> None:
    config = os.environ.get("VLEARN_CONFIG", "config/default.yaml")
    build_server(config).run(transport="stdio")


if __name__ == "__main__":
    main()
