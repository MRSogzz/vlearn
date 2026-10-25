"""端到端冒煙測試：驗證核心鏈路在真實數據上可用。

用法：python scripts/smoke_test.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.context import AppContext


def main() -> int:
    print("=== vlearn smoke test ===\n")

    # 1. AppContext
    try:
        ctx = AppContext.from_config("config/default.yaml")
        print(f"[OK] AppContext: project_root={ctx.project_root}")
        print(f"     db={ctx.db.path}")
    except Exception as e:
        print(f"[FAIL] AppContext init: {e}")
        return 1

    # 2. SQLite 表
    try:
        with ctx.db.conn() as c:
            tables = c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        names = [t["name"] for t in tables]
        required = {"videos", "segments", "keyframes", "reports",
                    "conflicts", "corrections", "jobs", "cost_entries"}
        missing = required - set(names)
        if missing:
            print(f"[FAIL] missing tables: {missing}")
            return 1
        print(f"[OK] SQLite: {len(names)} tables")
    except Exception as e:
        print(f"[FAIL] SQLite: {e}")
        return 1

    # 3. Router
    try:
        local_ok = ctx.router.available("local_summary")
        vision_ok = ctx.router.available("keyframe_desc")
        print(f"[OK] ModelRouter: local_summary={local_ok}, keyframe_desc={vision_ok}")
        if not local_ok:
            print("     (no LLM, falls back to regex)")
    except Exception as e:
        print(f"[FAIL] ModelRouter: {e}")
        return 1

    # 4. 視頻
    try:
        videos = ctx.db.list_videos(5)
        print(f"[OK] videos: {len(videos)} in DB")
        for v in videos[:3]:
            print(f"     - {v['video_id']} | {v['title'][:50]}")
    except Exception as e:
        print(f"[FAIL] list_videos: {e}")
        return 1

    # 5. 報告
    try:
        with ctx.db.conn() as c:
            row = c.execute(
                "SELECT run_id, video_id FROM reports ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row:
            r = ctx.db.get_report(row["run_id"])
            arr = json.loads(r["assertions"])
            assert isinstance(arr, list), "assertions not list"
            if arr:
                assert isinstance(arr[0], dict), "assertions[0] not dict"
            print(f"[OK] report: {row['run_id']} | {len(arr)} assertions")
        else:
            print("[SKIP] no reports yet")
    except Exception as e:
        print(f"[FAIL] report check: {e}")
        return 1

    # 6. MCP
    try:
        from app.mcp.server import build_server
        mcp = build_server("config/default.yaml")
        tools = list(mcp._tool_manager.list_tools())
        print(f"[OK] MCP server: {len(tools)} tools")
    except Exception as e:
        print(f"[FAIL] MCP server build: {e}")
        return 1

    # 7. corrections
    try:
        with ctx.db.conn() as c:
            n = c.execute("SELECT COUNT(*) n FROM corrections").fetchone()["n"]
        print(f"[OK] corrections: {n} total")
    except Exception as e:
        print(f"[FAIL] corrections: {e}")
        return 1

    print("\n=== smoke test PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
