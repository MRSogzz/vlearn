import re
from app.context import AppContext
from app.fusion.final import _generate_overview

ctx = AppContext.from_config("config/default.yaml")

# 用 Simon Sinek 的 18 分鐘演講（內容最豐富，最適合測概覽）
run_id = "run_2cb8c70252"
report = ctx.db.get_report(run_id)
video = ctx.db.get_video(report["video_id"])
md = report["report_md"]

# 只提取 ## 核心內容 段裡的分段摘要（## 關鍵時間點 之前的）
content_match = re.search(r'## 核心內容\n\n(.*?)\n## ', md, re.DOTALL)
summaries = []
if content_match:
    content_section = content_match.group(1)
    # 格式：### mm:ss – mm:ss\n- [source_type] summary
    pattern = r'### (\d+):(\d+) [–-] (\d+):(\d+)\n((?:- \[[^\]]+\] .+\n?)+)'
    for m in re.finditer(pattern, content_section):
        h1, m1, h2, m2, body = m.groups()
        lo = int(h1) * 60 + int(m1)
        hi = int(h2) * 60 + int(m2)
        text_parts = []
        for line in body.strip().split('\n'):
            sub = re.match(r'- \[[^\]]+\] (.+)', line)
            if sub:
                text_parts.append(sub.group(1).strip())
        if text_parts:
            summaries.append({
                "summary": " ".join(text_parts),
                "time_range": (lo, hi),
            })

print(f"video: {video['title']}")
print(f"extracted {len(summaries)} summaries")
for s in summaries[:3]:
    print(f"  {s['time_range']}: {s['summary'][:80]}")
print()

overview = _generate_overview(ctx, run_id, video, summaries)
print("=== overview ===")
print(overview if overview else "(None — LLM 未返回)")

