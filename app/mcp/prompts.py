from mcp.server.mcpserver import MCPServer


def register(mcp: MCPServer) -> None:

    @mcp.prompt()
    def analyze_youtube(url: str) -> str:
        return (
            f"請按以下順序操作：\n"
            f"1. 調用 ingest_video(url='{url}', platform='youtube')\n"
            f"2. 調用 analyze_video(video_id) 得到 job_id\n"
            f"3. 每 5 秒 get_job_status(job_id) 輪詢，直到 status=done\n"
            f"4. get_report(run_id)，把 get_conflicts 的未解決項逐條列出\n"
            f"5. 若需要，用 vlearn://reports/{{run_id}} 資源直接取全文"
        )

    @mcp.prompt()
    def trend_digest() -> str:
        return (
            "1. list_trend_top(20)\n"
            "2. 按主題聚類，標註熱度與來源\n"
            "3. 每個主題給一句：為什麼今天熱門（可用 report 斷言佐證）"
        )
