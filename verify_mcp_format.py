import asyncio
from app.context import AppContext
from app.mcp.tools import register
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent, ImageContent

async def main():
    ctx = AppContext.from_config("config/default.yaml")
    mcp = MCPServer(name="test")
    register(mcp, ctx)

    tools = mcp._tool_manager._tools
    print(f"registered tools: {len(tools)}")
    print(f"has read_frame_at: {'read_frame_at' in tools}")
    print()

    fn = tools["read_frame_at"].fn
    result = fn(video_id="8S0FDjFBj8o", timestamp=113.0)
    for b in result:
        if isinstance(b, ImageContent):
            n = len(b.data)
            print(f"base64 字元數: {n}")
            print(f"粗估 token (÷2.5): {n/2.5:.0f}")

    print(f"return type: {type(result).__name__}")
    print(f"block count: {len(result)}")
    print("=" * 70)

    for i, block in enumerate(result):
        print(f"[BLOCK {i}] class={type(block).__name__}")
        if isinstance(block, TextContent):
            print(f"  type: text ✅")
            print(f"  text length: {len(block.text)} chars")
            print(f"  text:")
            for line in block.text.split("\n"):
                print(f"    | {line}")
        elif isinstance(block, ImageContent):
            print(f"  type: image ✅")
            print(f"  mime_type: {block.mime_type}")    
            print(f"  data length: {len(block.data)} chars")
            print(f"  bytes: {len(block.data) * 3 // 4}")
        print()

asyncio.run(main())
