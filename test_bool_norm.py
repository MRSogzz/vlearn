import asyncio
from app.context import AppContext
from app.mcp.tools import register
from mcp.server.mcpserver import MCPServer

async def main():
    ctx = AppContext.from_config("config/default.yaml")
    mcp = MCPServer(name="test")
    register(mcp, ctx)
    fn = mcp._tool_manager._tools["read_frame_at"].fn

    for val in [False, "False", "false", "0", True, "true"]:
        r = fn(video_id="8S0FDjFBj8o", timestamp=113.0, include_image=val)
        kinds = [type(b).__name__ for b in r]
        print(f"include_image={val!r:10} → {kinds}")

asyncio.run(main())
